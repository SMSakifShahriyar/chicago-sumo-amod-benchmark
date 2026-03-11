import csv
import json
import math
import re
from collections import defaultdict, deque
from pathlib import Path
import xml.etree.ElementTree as ET

root = Path(r"E:\project_sakif_chicago")
log_file = root / "output" / "smoke_test_reduced_no_bike.log"
net_file = root / "net" / "map_reduced_no_bike.net.xml"
out_json = root / "output" / "teleport_hotspots_no_bike.json"
out_txt = root / "output" / "teleport_hotspots_no_bike.txt"
out_csv = root / "output" / "teleport_cleanup_targets_no_bike.csv"

if not log_file.exists() or not net_file.exists():
    print("missing input files")
    raise SystemExit(1)

text = log_file.read_text(encoding="utf-8", errors="ignore")
lines = text.splitlines()

start_re = re.compile(r"Teleporting vehicle '([^']+)'; waited too long \(([^)]+)\), lane='([^']+)', time=([0-9.]+)\.")
end_re = re.compile(r"Vehicle '([^']+)' ends teleporting on edge '([^']+)', time=([0-9.]+)\.")
summary_re = re.compile(r"Teleports:\s*(\d+)\s*\(([^)]*)\)")

start_events = []
end_by_vehicle = defaultdict(list)
summary = None
for line in lines:
    m = start_re.search(line)
    if m:
        vehicle_id, reason, lane_id, t = m.groups()
        start_events.append({
            "vehicle_id": vehicle_id,
            "reason": reason.strip(),
            "lane_id": lane_id,
            "time": float(t),
        })
        continue
    m = end_re.search(line)
    if m:
        vehicle_id, edge_id, t = m.groups()
        end_by_vehicle[vehicle_id].append({"edge_id": edge_id, "time": float(t)})
        continue
    m = summary_re.search(line)
    if m:
        summary = {"count": int(m.group(1)), "breakdown": m.group(2)}

for v in end_by_vehicle.values():
    v.sort(key=lambda x: x["time"])

teleports = []
for ev in start_events:
    lane_id = ev["lane_id"]
    if "_" in lane_id:
        edge_id = lane_id.rsplit("_", 1)[0]
    else:
        edge_id = lane_id
    end_event = None
    for cand in end_by_vehicle.get(ev["vehicle_id"], []):
        if cand["time"] >= ev["time"]:
            end_event = cand
            break
    teleports.append({
        "vehicle_id": ev["vehicle_id"],
        "start_time": ev["time"],
        "reason": ev["reason"],
        "start_lane_id": lane_id,
        "start_edge_id": edge_id,
        "end_time": None if end_event is None else end_event["time"],
        "end_edge_id": None if end_event is None else end_event["edge_id"],
    })

tree = ET.parse(net_file)
net = tree.getroot()

junctions = {}
for j in net.findall("junction"):
    jid = j.get("id", "")
    try:
        x = float(j.get("x", "0") or 0)
        y = float(j.get("y", "0") or 0)
    except ValueError:
        x, y = 0.0, 0.0
    junctions[jid] = {
        "id": jid,
        "type": j.get("type", ""),
        "x": x,
        "y": y,
        "incLanes": [v for v in (j.get("incLanes", "") or "").split(" ") if v],
        "intLanes": [v for v in (j.get("intLanes", "") or "").split(" ") if v],
    }

edges = {}
lane_to_edge = {}
for e in net.findall("edge"):
    if e.get("function"):
        continue
    eid = e.get("id", "")
    fr = e.get("from", "")
    to = e.get("to", "")
    lane_objs = e.findall("lane")
    lane_ids = []
    lane_lengths = []
    for lane in lane_objs:
        lid = lane.get("id", "")
        lane_ids.append(lid)
        lane_to_edge[lid] = eid
        try:
            lane_lengths.append(float(lane.get("length", "0") or 0))
        except ValueError:
            lane_lengths.append(0.0)
    length = lane_lengths[0] if lane_lengths else 0.0
    edges[eid] = {
        "id": eid,
        "from": fr,
        "to": to,
        "lane_ids": lane_ids,
        "lane_count": len(lane_ids),
        "length": length,
    }

edge_out = defaultdict(set)
lane_out = defaultdict(set)
for c in net.findall("connection"):
    fe = c.get("from", "")
    te = c.get("to", "")
    fl = c.get("fromLane")
    tl = c.get("toLane")
    if fe and te:
        edge_out[fe].add(te)
    if fe and fl is not None:
        lane_out[f"{fe}_{fl}"]
        if te and tl is not None:
            lane_out[f"{fe}_{fl}"].add(f"{te}_{tl}")

teleport_start_edges = sorted(set(t["start_edge_id"] for t in teleports if t["start_edge_id"]))
teleport_end_edges = sorted(set(t["end_edge_id"] for t in teleports if t["end_edge_id"]))
hotspot_edges = sorted(set(teleport_start_edges + teleport_end_edges))

seed_junctions = set()
for eid in hotspot_edges:
    e = edges.get(eid)
    if not e:
        continue
    seed_junctions.add(e["from"])
    seed_junctions.add(e["to"])

local_edges = set(hotspot_edges)
for eid, e in edges.items():
    if e["from"] in seed_junctions or e["to"] in seed_junctions:
        local_edges.add(eid)

local_junctions = set(seed_junctions)
for eid in local_edges:
    e = edges.get(eid)
    if not e:
        continue
    local_junctions.add(e["from"])
    local_junctions.add(e["to"])

short_local_edges = [eid for eid in local_edges if eid in edges and edges[eid]["length"] <= 12.0]

lane_context = {}
for t in teleports:
    lane = t["start_lane_id"]
    out_count = len(lane_out.get(lane, set()))
    lane_context[lane] = {
        "outgoing_connection_count": out_count,
        "outgoing_connections": sorted(lane_out.get(lane, set())),
    }

edge_path_cache = {}

def has_path(start_edge, target_edge, depth_limit=4):
    key = (start_edge, target_edge, depth_limit)
    if key in edge_path_cache:
        return edge_path_cache[key]
    if start_edge == target_edge:
        edge_path_cache[key] = True
        return True
    dq = deque([(start_edge, 0)])
    seen = {start_edge}
    while dq:
        cur, d = dq.popleft()
        if d >= depth_limit:
            continue
        for nxt in edge_out.get(cur, set()):
            if nxt == target_edge:
                edge_path_cache[key] = True
                return True
            if nxt not in seen:
                seen.add(nxt)
                dq.append((nxt, d + 1))
    edge_path_cache[key] = False
    return False

path_checks = []
for se in teleport_start_edges:
    for ee in teleport_end_edges:
        path_checks.append({
            "from_edge": se,
            "to_edge": ee,
            "path_within_4_steps": has_path(se, ee, 4),
        })

x_vals = []
y_vals = []
for jid in local_junctions:
    if jid in junctions:
        x_vals.append(junctions[jid]["x"])
        y_vals.append(junctions[jid]["y"])
bbox = None
if x_vals and y_vals:
    bbox = {
        "xmin": round(min(x_vals) - 40.0, 3),
        "xmax": round(max(x_vals) + 40.0, 3),
        "ymin": round(min(y_vals) - 40.0, 3),
        "ymax": round(max(y_vals) + 40.0, 3),
    }

problem_flags = {
    "wrong_lane_geometry": any(t["reason"] == "wrong lane" for t in teleports),
    "jam_local_bottleneck": any(t["reason"] == "jam" for t in teleports),
    "short_connector_artifact": len(short_local_edges) >= 2,
    "bad_turn_connectivity": any(not p["path_within_4_steps"] for p in path_checks) or any(v["outgoing_connection_count"] == 0 for v in lane_context.values()),
    "signalized_local_issue": any(junctions.get(j, {}).get("type") == "traffic_light" for j in local_junctions),
}

candidates = []

def add_candidate(kind, item_id, score, category, reason, action):
    candidates.append({
        "target_type": kind,
        "target_id": item_id,
        "score": round(score, 3),
        "category": category,
        "reason": reason,
        "suggested_action": action,
    })

for eid in hotspot_edges:
    if eid not in edges:
        continue
    role = []
    if eid in teleport_start_edges:
        role.append("teleport_start")
    if eid in teleport_end_edges:
        role.append("teleport_end")
    score = 10.0
    if eid in teleport_start_edges:
        score += 6.0
    if eid in teleport_end_edges:
        score += 5.0
    if edges[eid]["length"] <= 20:
        score += 2.0
    add_candidate("edge", eid, score, "teleport_hotspot_edge", "directly involved in teleport events: " + ",".join(role), "inspect only")

for lane_id, ctx in lane_context.items():
    if ctx["outgoing_connection_count"] <= 1:
        edge_id = lane_to_edge.get(lane_id, lane_id.rsplit("_", 1)[0] if "_" in lane_id else lane_id)
        add_candidate("edge", edge_id, 13.0 + (1 - ctx["outgoing_connection_count"]), "lane_connectivity_issue", f"teleport lane {lane_id} has {ctx['outgoing_connection_count']} outgoing lane-connections", "inspect lane-turn connectivity")

for eid in short_local_edges:
    if eid in hotspot_edges:
        continue
    e = edges[eid]
    score = 7.0 + max(0.0, (12.0 - e["length"])) * 0.2
    add_candidate("edge", eid, score, "short_connector_artifact", f"very short local edge ({round(e['length'],3)}m) near teleport hotspot", "consider merge/simplify")

for jid in local_junctions:
    j = junctions.get(jid)
    if not j:
        continue
    deg = 0
    for e in edges.values():
        if e["from"] == jid or e["to"] == jid:
            deg += 1
    if j["type"] == "traffic_light":
        score = 8.0 + min(4, deg * 0.3)
        add_candidate("junction", jid, score, "signalized_local_issue", f"traffic-light junction near teleport edges (degree={deg})", "inspect traffic-light node geometry")

dedup = {}
for c in candidates:
    key = (c["target_type"], c["target_id"])
    if key not in dedup or c["score"] > dedup[key]["score"]:
        dedup[key] = c
candidates = list(dedup.values())
candidates.sort(key=lambda x: x["score"], reverse=True)

if len(candidates) > 16:
    candidates = candidates[:16]

teleport_counts_by_edge = defaultdict(int)
for t in teleports:
    teleport_counts_by_edge[t["start_edge_id"]] += 1

nearby_junctions = []
for jid in sorted(local_junctions):
    j = junctions.get(jid)
    if not j:
        continue
    nearby_junctions.append({
        "junction_id": jid,
        "type": j["type"],
        "x": round(j["x"], 3),
        "y": round(j["y"], 3),
    })

first_batch = []
for c in candidates:
    if c["target_type"] == "edge" and len(first_batch) < 3:
        first_batch.append({
            "target_type": c["target_type"],
            "target_id": c["target_id"],
            "category": c["category"],
            "suggested_action": c["suggested_action"],
        })

result = {
    "network_file": str(net_file),
    "log_file": str(log_file),
    "teleport_summary_from_log": summary,
    "teleport_event_count": len(teleports),
    "teleport_events": teleports,
    "hotspot_edges": {
        "start_edges": teleport_start_edges,
        "end_edges": teleport_end_edges,
        "counts_by_start_edge": dict(sorted(teleport_counts_by_edge.items(), key=lambda kv: kv[1], reverse=True)),
    },
    "hotspot_local_area": {
        "bbox": bbox,
        "local_edge_count": len(local_edges),
        "local_junction_count": len(local_junctions),
        "short_local_edges_le_12m": len(short_local_edges),
        "short_local_edge_ids": sorted(short_local_edges)[:40],
        "nearby_junctions": nearby_junctions,
    },
    "lane_context": lane_context,
    "path_checks": path_checks,
    "problem_type_assessment": problem_flags,
    "cleanup_targets_ranked": candidates,
    "first_cleanup_batch_small": first_batch,
}

out_json.write_text(json.dumps(result, indent=2), encoding="utf-8")

with out_csv.open("w", newline="", encoding="utf-8") as f:
    fields = ["rank", "target_type", "target_id", "score", "category", "reason", "suggested_action"]
    w = csv.DictWriter(f, fieldnames=fields)
    w.writeheader()
    for i, c in enumerate(candidates, start=1):
        row = dict(c)
        row["rank"] = i
        w.writerow(row)

lines = []
lines.append("Teleport hotspot report (no-bike network)")
lines.append("")
lines.append(f"teleport_event_count={len(teleports)}")
if summary:
    lines.append(f"teleport_summary_line={summary['count']} ({summary['breakdown']})")
lines.append("")
lines.append("exact teleport events:")
for t in teleports:
    lines.append(f"- vehicle={t['vehicle_id']} time={t['start_time']} reason={t['reason']} lane={t['start_lane_id']} start_edge={t['start_edge_id']} end_edge={t['end_edge_id']} end_time={t['end_time']}")
lines.append("")
lines.append("hotspot edges:")
lines.append("- start_edges=" + ", ".join(teleport_start_edges))
lines.append("- end_edges=" + ", ".join(teleport_end_edges))
lines.append("")
lines.append("problem type assessment:")
for k, v in problem_flags.items():
    lines.append(f"- {k}: {str(v).lower()}")
lines.append("")
if bbox:
    lines.append(f"local inspection bbox: xmin={bbox['xmin']} xmax={bbox['xmax']} ymin={bbox['ymin']} ymax={bbox['ymax']}")
lines.append("")
lines.append("top cleanup targets:")
for i, c in enumerate(candidates[:10], start=1):
    lines.append(f"{i}. {c['target_type']} {c['target_id']} | {c['category']} | score={c['score']} | action={c['suggested_action']} | reason={c['reason']}")
lines.append("")
lines.append("small first cleanup batch suggestion:")
for c in first_batch:
    lines.append(f"- {c['target_type']} {c['target_id']} | {c['category']} | {c['suggested_action']}")

out_txt.write_text("\n".join(lines), encoding="utf-8")

print("done")
print("teleports", len(teleports))
print("hotspot_start_edges", teleport_start_edges)
print("hotspot_end_edges", teleport_end_edges)
print("candidates", len(candidates))
