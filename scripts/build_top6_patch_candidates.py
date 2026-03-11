import csv
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET

root = Path(r"E:\project_sakif_chicago")
net_file = root / "net" / "map_reduced_clean_auto_v2.net.xml"
out_csv = root / "output" / "top6_patch_candidates.csv"
out_json = root / "output" / "top6_patch_candidates.json"
out_txt = root / "output" / "top6_patch_summary.txt"
out_remove = root / "data" / "remove_edges_top6_candidates.txt"

focus_ids = [
    "27446720",
    "27446708",
    "28290256",
    "27446709",
    "28290296",
    "28289974",
]

if not net_file.exists():
    print("network file not found")
    raise SystemExit(1)

tree = ET.parse(net_file)
net = tree.getroot()

junctions = {}
all_x = []
all_y = []
for j in net.findall("junction"):
    jid = j.get("id", "")
    if jid.startswith(":") or j.get("type", "") == "internal":
        continue
    x = float(j.get("x", "0") or 0)
    y = float(j.get("y", "0") or 0)
    inc_lanes = [v for v in (j.get("incLanes", "") or "").split(" ") if v]
    int_lanes = [v for v in (j.get("intLanes", "") or "").split(" ") if v]
    junctions[jid] = {
        "id": jid,
        "x": x,
        "y": y,
        "type": j.get("type", ""),
        "inc_lane_count": len(inc_lanes),
        "int_lane_count": len(int_lanes),
    }
    all_x.append(x)
    all_y.append(y)

xmin = min(all_x)
xmax = max(all_x)
ymin = min(all_y)
ymax = max(all_y)
margin = max(40.0, min(xmax - xmin, ymax - ymin) * 0.06)


def near_boundary(x, y):
    return x <= xmin + margin or x >= xmax - margin or y <= ymin + margin or y >= ymax - margin


def lane_allows_passenger(lane):
    allow = (lane.get("allow", "") or "").strip()
    disallow = (lane.get("disallow", "") or "").strip()
    if allow:
        return "passenger" in allow.split()
    if disallow:
        return "passenger" not in disallow.split()
    return True

edges = {}
incoming = {jid: [] for jid in junctions}
outgoing = {jid: [] for jid in junctions}
for e in net.findall("edge"):
    if e.get("function"):
        continue
    eid = e.get("id", "")
    fr = e.get("from", "")
    to = e.get("to", "")
    lane_objs = e.findall("lane")
    lane_count = len(lane_objs)
    length = 0.0
    speed = 0.0
    if lane_objs:
        try:
            length = float(lane_objs[0].get("length", "0") or 0)
        except Exception:
            length = 0.0
        try:
            speed = max(float(l.get("speed", "0") or 0) for l in lane_objs)
        except Exception:
            speed = 0.0
    priority = 0
    try:
        priority = int(e.get("priority", "0") or 0)
    except Exception:
        priority = 0

    motor_ok = any(lane_allows_passenger(l) for l in lane_objs) if lane_objs else True

    edges[eid] = {
        "id": eid,
        "from": fr,
        "to": to,
        "lane_count": lane_count,
        "length": length,
        "speed": speed,
        "priority": priority,
        "motor_ok": motor_ok,
    }
    if fr in outgoing:
        outgoing[fr].append(eid)
    if to in incoming:
        incoming[to].append(eid)

short_incident = {}
for jid in junctions:
    cnt = 0
    for eid in incoming.get(jid, []) + outgoing.get(jid, []):
        if eid in edges and edges[eid]["length"] <= 12.0 and edges[eid]["motor_ok"]:
            cnt += 1
    short_incident[jid] = cnt

records = []
structured = []

for fid in focus_ids:
    if fid not in junctions:
        structured.append({"focus_junction": {"junction_id": fid, "found": False}, "candidates": []})
        continue

    fj = junctions[fid]
    radius = 130.0
    local_junctions = []
    for jid, j in junctions.items():
        d = math.hypot(j["x"] - fj["x"], j["y"] - fj["y"])
        if d <= radius:
            local_junctions.append((jid, d))
    local_jids = {jid for jid, _ in local_junctions}

    local_edges = []
    seen = set()
    for jid in local_jids:
        for eid in incoming.get(jid, []) + outgoing.get(jid, []):
            if eid in seen:
                continue
            seen.add(eid)
            if eid in edges and edges[eid]["motor_ok"]:
                local_edges.append(eid)

    candidates = []

    for eid in local_edges:
        e = edges[eid]
        if e["from"] not in junctions or e["to"] not in junctions:
            continue
        fx, fy = junctions[e["from"]]["x"], junctions[e["from"]]["y"]
        tx, ty = junctions[e["to"]]["x"], junctions[e["to"]]["y"]
        mx, my = (fx + tx) / 2.0, (fy + ty) / 2.0
        dist = math.hypot(mx - fj["x"], my - fj["y"])
        if dist > radius + 20:
            continue

        score = 0.0
        reasons = []

        if e["length"] <= 3.0:
            score += 6.0
            reasons.append(f"very_short_edge:{round(e['length'],3)}m")
        elif e["length"] <= 6.0:
            score += 4.8
            reasons.append(f"short_edge:{round(e['length'],3)}m")
        elif e["length"] <= 10.0:
            score += 3.4
            reasons.append(f"short_edge:{round(e['length'],3)}m")
        elif e["length"] <= 12.0:
            score += 2.5
            reasons.append(f"short_edge:{round(e['length'],3)}m")

        if e["lane_count"] == 1 and e["length"] <= 12.0:
            score += 0.8
            reasons.append("single_lane_short_connector")

        from_short = short_incident.get(e["from"], 0)
        to_short = short_incident.get(e["to"], 0)
        if from_short >= 2 and to_short >= 2 and e["length"] <= 12.0:
            score += 2.1
            reasons.append("short_connector_chain")

        if e["from"] == fid or e["to"] == fid:
            if e["length"] <= 10.0:
                score += 1.9
                reasons.append("touches_focus_with_short_segment")
            elif e["lane_count"] >= 2 and e["length"] > 35:
                reasons.append("major_focus_approach")

        dead_end_neighbor = False
        for jid in [e["from"], e["to"]]:
            if jid in junctions:
                j = junctions[jid]
                deg = len(incoming.get(jid, [])) + len(outgoing.get(jid, []))
                if j["type"] == "dead_end" or (deg <= 2 and not near_boundary(j["x"], j["y"])):
                    dead_end_neighbor = True
        if dead_end_neighbor and e["length"] <= 12.0:
            score += 1.3
            reasons.append("near_dead_end_artifact")

        major_corridor = e["lane_count"] >= 2 and e["length"] > 35 and (e["speed"] >= 13.9 or e["priority"] >= 8)
        if major_corridor:
            candidates.append({
                "focus_junction_id": fid,
                "focus_x": round(fj["x"], 3),
                "focus_y": round(fj["y"], 3),
                "candidate_type": "edge",
                "candidate_id": eid,
                "candidate_x": round(mx, 3),
                "candidate_y": round(my, 3),
                "distance_to_focus_m": round(dist, 3),
                "junction_type": "",
                "edge_length_m": round(e["length"], 3),
                "lane_count": e["lane_count"],
                "score": 1.0,
                "why_suspicious": "major corridor approach; likely critical movement",
                "suggested_action": "leave alone",
            })
        elif score >= 4.0:
            action = "inspect only"
            if score >= 8.0:
                action = "likely safe to remove"
            elif score >= 6.0:
                action = "likely safe to simplify"
            candidates.append({
                "focus_junction_id": fid,
                "focus_x": round(fj["x"], 3),
                "focus_y": round(fj["y"], 3),
                "candidate_type": "edge",
                "candidate_id": eid,
                "candidate_x": round(mx, 3),
                "candidate_y": round(my, 3),
                "distance_to_focus_m": round(dist, 3),
                "junction_type": "",
                "edge_length_m": round(e["length"], 3),
                "lane_count": e["lane_count"],
                "score": round(score, 3),
                "why_suspicious": ";".join(reasons),
                "suggested_action": action,
            })

    for jid, d in local_junctions:
        if jid == fid:
            continue
        j = junctions[jid]
        deg = len(incoming.get(jid, [])) + len(outgoing.get(jid, []))
        score = 0.0
        reasons = []

        if j["type"] == "dead_end" and not near_boundary(j["x"], j["y"]):
            score += 4.2
            reasons.append("interior_dead_end")

        if j["type"] == "traffic_light" and deg >= 5 and j["int_lane_count"] <= 4:
            score += 3.5
            reasons.append("signalized_low_internal_lanes")

        if short_incident.get(jid, 0) >= 3:
            score += 2.2
            reasons.append("near_short_edge_cluster")

        if score >= 4.5:
            candidates.append({
                "focus_junction_id": fid,
                "focus_x": round(fj["x"], 3),
                "focus_y": round(fj["y"], 3),
                "candidate_type": "junction",
                "candidate_id": jid,
                "candidate_x": round(j["x"], 3),
                "candidate_y": round(j["y"], 3),
                "distance_to_focus_m": round(d, 3),
                "junction_type": j["type"],
                "edge_length_m": "",
                "lane_count": "",
                "score": round(score, 3),
                "why_suspicious": ";".join(reasons),
                "suggested_action": "inspect only",
            })

    by_key = {}
    for c in candidates:
        key = (c["candidate_type"], c["candidate_id"])
        if key not in by_key:
            by_key[key] = c
        else:
            old = by_key[key]
            if c["suggested_action"] == "leave alone" and old["suggested_action"] != "leave alone":
                continue
            if old["suggested_action"] == "leave alone" and c["suggested_action"] != "leave alone":
                by_key[key] = c
            elif float(c["score"]) > float(old["score"]):
                by_key[key] = c

    candidates = list(by_key.values())
    candidates.sort(key=lambda x: (x["suggested_action"] == "leave alone", -float(x["score"])))

    suspicious = [c for c in candidates if c["suggested_action"] != "leave alone"]
    keepers = [c for c in candidates if c["suggested_action"] == "leave alone"]

    focus_list = suspicious[:6] + keepers[:2]

    structured.append({
        "focus_junction": {
            "junction_id": fid,
            "x": round(fj["x"], 3),
            "y": round(fj["y"], 3),
            "junction_type": fj["type"],
        },
        "nearby_suspicious_edge_ids": [c["candidate_id"] for c in focus_list if c["candidate_type"] == "edge" and c["suggested_action"] != "leave alone"],
        "nearby_suspicious_junction_ids": [c["candidate_id"] for c in focus_list if c["candidate_type"] == "junction"],
        "candidates": focus_list,
    })

    records.extend(focus_list)

removal_edges = []
for c in records:
    if c["candidate_type"] != "edge":
        continue
    if c["suggested_action"] not in {"likely safe to remove", "likely safe to simplify"}:
        continue
    if float(c["score"]) < 7.0:
        continue
    removal_edges.append((c["candidate_id"], float(c["score"]), c["why_suspicious"]))

best_removal = {}
for eid, score, reason in removal_edges:
    if eid not in best_removal or score > best_removal[eid][0]:
        best_removal[eid] = (score, reason)

sorted_removal = sorted(best_removal.items(), key=lambda kv: kv[1][0], reverse=True)
final_removal_ids = [eid for eid, _ in sorted_removal[:20]]

out_remove.write_text("\n".join(final_removal_ids) + ("\n" if final_removal_ids else ""), encoding="utf-8")

with out_csv.open("w", newline="", encoding="utf-8") as f:
    fields = [
        "focus_junction_id",
        "focus_x",
        "focus_y",
        "candidate_type",
        "candidate_id",
        "candidate_x",
        "candidate_y",
        "distance_to_focus_m",
        "junction_type",
        "edge_length_m",
        "lane_count",
        "score",
        "why_suspicious",
        "suggested_action",
    ]
    w = csv.DictWriter(f, fieldnames=fields)
    w.writeheader()
    for r in records:
        w.writerow(r)

json_data = {
    "network": str(net_file),
    "focus_junction_ids": focus_ids,
    "per_focus": structured,
    "strong_removal_candidates": final_removal_ids,
}
out_json.write_text(json.dumps(json_data, indent=2), encoding="utf-8")

lines = []
lines.append("Top-6 patch candidate summary")
lines.append("")
lines.append("network: " + str(net_file))
lines.append("focus junctions: " + ", ".join(focus_ids))
lines.append("")
for section in structured:
    fj = section["focus_junction"]
    lines.append(f"{fj['junction_id']} ({fj['x']}, {fj['y']}) type={fj['junction_type']}")
    if not section["candidates"]:
        lines.append("- no focused candidates found")
    else:
        for c in section["candidates"]:
            lines.append(f"- {c['candidate_type']} {c['candidate_id']} | action={c['suggested_action']} | score={c['score']} | reason={c['why_suspicious']}")
    lines.append("")

lines.append("strongest removal candidates overall:")
if final_removal_ids:
    for eid in final_removal_ids:
        score, reason = best_removal[eid]
        lines.append(f"- {eid} | score={round(score,3)} | reason={reason}")
else:
    lines.append("- none")

out_txt.write_text("\n".join(lines), encoding="utf-8")

print("done")
print("records", len(records))
print("removal_candidates", len(final_removal_ids))
