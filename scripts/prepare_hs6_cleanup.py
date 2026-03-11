import csv
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET

root = Path(r"E:\project_sakif_chicago")
net_file = root / "net" / "map_reduced.net.xml"
out_csv = root / "output" / "hs6_cleanup_candidates.csv"
out_json = root / "output" / "hs6_cleanup_candidates.json"
out_txt = root / "output" / "hs6_cleanup_plan.txt"

xmin = 559.548
xmax = 749.58
ymin = 862.371
ymax = 1044.36
focus_ids = ["10922644190", "9913028598", "2284331776", "9913028592", "13328987946"]

if not net_file.exists():
    print("network file missing")
    raise SystemExit(1)

tree = ET.parse(net_file)
net = tree.getroot()

junctions = {}
for j in net.findall("junction"):
    jid = j.get("id", "")
    x = float(j.get("x", "0") or 0)
    y = float(j.get("y", "0") or 0)
    jtype = j.get("type", "")
    if jtype == "internal" or jid.startswith(":"):
        continue
    inclanes = [v for v in (j.get("incLanes", "") or "").split(" ") if v]
    intlanes = [v for v in (j.get("intLanes", "") or "").split(" ") if v]
    junctions[jid] = {
        "id": jid,
        "x": x,
        "y": y,
        "type": jtype,
        "inc_lane_count": len(inclanes),
        "int_lane_count": len(intlanes),
    }

incoming = {jid: [] for jid in junctions}
outgoing = {jid: [] for jid in junctions}
edge_map = {}

for e in net.findall("edge"):
    if e.get("function"):
        continue
    eid = e.get("id", "")
    fr = e.get("from", "")
    to = e.get("to", "")
    lanes = e.findall("lane")
    lane_count = len(lanes)
    length = 0.0
    if lanes:
        try:
            length = float(lanes[0].get("length", "0") or 0)
        except ValueError:
            length = 0.0
    edge_map[eid] = {
        "id": eid,
        "from": fr,
        "to": to,
        "length": length,
        "lane_count": lane_count,
    }
    if fr in outgoing:
        outgoing[fr].append(eid)
    if to in incoming:
        incoming[to].append(eid)

junctions_in_box = {}
for jid, j in junctions.items():
    if xmin <= j["x"] <= xmax and ymin <= j["y"] <= ymax:
        junctions_in_box[jid] = j

edges_touching_box = {}
for eid, e in edge_map.items():
    fr = e["from"]
    to = e["to"]
    fr_in = fr in junctions_in_box
    to_in = to in junctions_in_box
    if fr_in or to_in:
        edges_touching_box[eid] = e

short_edges = [e for e in edges_touching_box.values() if e["length"] <= 12.0]
short_edges.sort(key=lambda x: x["length"])

inner_margin = 18.0
inner_xmin = xmin + inner_margin
inner_xmax = xmax - inner_margin
inner_ymin = ymin + inner_margin
inner_ymax = ymax - inner_margin

interior_dead_end_junctions = []
for jid, j in junctions_in_box.items():
    deg = len(incoming.get(jid, [])) + len(outgoing.get(jid, []))
    in_inner = inner_xmin <= j["x"] <= inner_xmax and inner_ymin <= j["y"] <= inner_ymax
    if in_inner and (j["type"] == "dead_end" or deg <= 2):
        interior_dead_end_junctions.append({
            "junction_id": jid,
            "x": j["x"],
            "y": j["y"],
            "type": j["type"],
            "degree": deg,
        })

traffic_lights = []
for jid, j in junctions_in_box.items():
    if j["type"] == "traffic_light":
        in_edges = incoming.get(jid, [])
        out_edges = outgoing.get(jid, [])
        short_count = 0
        for eid in in_edges + out_edges:
            if eid in edge_map and edge_map[eid]["length"] <= 12.0:
                short_count += 1
        traffic_lights.append({
            "junction_id": jid,
            "x": j["x"],
            "y": j["y"],
            "in_edges": len(in_edges),
            "out_edges": len(out_edges),
            "short_edge_count": short_count,
            "int_lane_count": j["int_lane_count"],
        })

neighbors = {}
for jid, j in junctions_in_box.items():
    lst = []
    for oid, o in junctions_in_box.items():
        if oid == jid:
            continue
        d = math.hypot(j["x"] - o["x"], j["y"] - o["y"])
        if d <= 35:
            lst.append((oid, d))
    lst.sort(key=lambda t: t[1])
    neighbors[jid] = lst

tiny_chains = []
for e in short_edges:
    fr = e["from"]
    to = e["to"]
    if fr in junctions_in_box and to in junctions_in_box:
        fr_short = 0
        to_short = 0
        for feid in incoming.get(fr, []) + outgoing.get(fr, []):
            if feid in edges_touching_box and edge_map[feid]["length"] <= 12.0:
                fr_short += 1
        for teid in incoming.get(to, []) + outgoing.get(to, []):
            if teid in edges_touching_box and edge_map[teid]["length"] <= 12.0:
                to_short += 1
        if fr_short >= 2 and to_short >= 2:
            tiny_chains.append({
                "edge_id": e["id"],
                "from": fr,
                "to": to,
                "length": e["length"],
                "from_short_degree": fr_short,
                "to_short_degree": to_short,
            })

focus_positions = {fid: (junctions[fid]["x"], junctions[fid]["y"]) for fid in focus_ids if fid in junctions}

def nearest_focus_ids(x, y, limit=3):
    vals = []
    for fid, (fx, fy) in focus_positions.items():
        vals.append((fid, math.hypot(x - fx, y - fy)))
    vals.sort(key=lambda t: t[1])
    return [v[0] for v in vals[:limit]]

candidates = []

def add_candidate(item_id, item_type, category, length, x, y, reason, action, score):
    candidates.append({
        "id": item_id,
        "item_type": item_type,
        "category": category,
        "length_m": None if length is None else round(length, 3),
        "x": round(x, 3),
        "y": round(y, 3),
        "near_focus_junction_ids": nearest_focus_ids(x, y),
        "reason": reason,
        "suggested_manual_action": action,
        "score": round(score, 3),
    })

for e in short_edges:
    fr = e["from"]
    to = e["to"]
    if fr not in junctions or to not in junctions:
        continue
    x = (junctions[fr]["x"] + junctions[to]["x"]) / 2
    y = (junctions[fr]["y"] + junctions[to]["y"]) / 2
    short_cluster_strength = 0
    for eid in incoming.get(fr, []) + outgoing.get(fr, []) + incoming.get(to, []) + outgoing.get(to, []):
        if eid in edges_touching_box and edge_map[eid]["length"] <= 12.0:
            short_cluster_strength += 1
    if e["length"] <= 7.0 and short_cluster_strength >= 4:
        add_candidate(e["id"], "edge", "likely tiny artifact edge", e["length"], x, y, "very short edge inside short-edge cluster", "consider delete if clearly artificial", 9.0 + short_cluster_strength * 0.3)
    elif e["length"] <= 12.0 and short_cluster_strength >= 5:
        add_candidate(e["id"], "edge", "likely over-split junction chain", e["length"], x, y, "short connector likely splitting local node geometry", "consider merge/simplify", 7.0 + short_cluster_strength * 0.25)

for j in interior_dead_end_junctions:
    short_count = 0
    for eid in incoming.get(j["junction_id"], []) + outgoing.get(j["junction_id"], []):
        if eid in edges_touching_box and edge_map[eid]["length"] <= 12.0:
            short_count += 1
    if short_count >= 2:
        add_candidate(j["junction_id"], "junction", "likely bad dead-end artifact", None, j["x"], j["y"], "dead-end or low-degree node in interior dense zone with short connectors", "inspect only", 8.5 + short_count * 0.4)

for t in traffic_lights:
    if t["short_edge_count"] >= 3 or t["int_lane_count"] <= 2:
        score = 7.8 + t["short_edge_count"] * 0.35
        reason = "traffic-light node connected to multiple short edges or very low internal lanes"
        add_candidate(t["junction_id"], "junction", "likely signalized local geometry issue", None, t["x"], t["y"], reason, "inspect traffic-light structure", score)

for ch in tiny_chains:
    fr = ch["from"]
    to = ch["to"]
    if fr in junctions and to in junctions:
        x = (junctions[fr]["x"] + junctions[to]["x"]) / 2
        y = (junctions[fr]["y"] + junctions[to]["y"]) / 2
        add_candidate(ch["edge_id"], "edge", "likely over-split junction chain", ch["length"], x, y, "short-edge chain between nearby junctions", "consider merge/simplify", 8.0 + (ch["from_short_degree"] + ch["to_short_degree"]) * 0.25)

dedup = {}
for c in candidates:
    key = (c["id"], c["item_type"], c["category"])
    if key not in dedup or c["score"] > dedup[key]["score"]:
        dedup[key] = c

candidates = list(dedup.values())
candidates.sort(key=lambda x: x["score"], reverse=True)

max_items = 16
if len(candidates) > max_items:
    candidates = candidates[:max_items]

category_order = [
    "likely tiny artifact edge",
    "likely bad dead-end artifact",
    "likely over-split junction chain",
    "likely signalized local geometry issue",
]

counts = {k: 0 for k in category_order}
for c in candidates:
    if c["category"] in counts:
        counts[c["category"]] += 1

result = {
    "network_file": str(net_file),
    "hs6_box": {"xmin": xmin, "xmax": xmax, "ymin": ymin, "ymax": ymax},
    "focus_junction_ids": focus_ids,
    "box_stats": {
        "junctions_in_box": len(junctions_in_box),
        "edges_touching_box": len(edges_touching_box),
        "very_short_edges_le_12m": len(short_edges),
        "interior_dead_end_like_junctions": len(interior_dead_end_junctions),
        "traffic_light_junctions_in_box": len(traffic_lights),
        "tiny_chain_count": len(tiny_chains),
    },
    "candidate_category_counts": counts,
    "candidates": candidates,
}

with out_json.open("w", encoding="utf-8") as f:
    json.dump(result, f, indent=2)

with out_csv.open("w", newline="", encoding="utf-8") as f:
    fields = [
        "rank",
        "id",
        "item_type",
        "category",
        "length_m",
        "x",
        "y",
        "near_focus_junction_ids",
        "reason",
        "suggested_manual_action",
        "score",
    ]
    w = csv.DictWriter(f, fieldnames=fields)
    w.writeheader()
    for i, c in enumerate(candidates, start=1):
        row = dict(c)
        row["rank"] = i
        row["near_focus_junction_ids"] = ";".join(c["near_focus_junction_ids"])
        w.writerow(row)

lines = []
lines.append("HS6 manual cleanup plan")
lines.append("")
lines.append(f"network: {net_file}")
lines.append(f"box: xmin={xmin}, xmax={xmax}, ymin={ymin}, ymax={ymax}")
lines.append("")
lines.append("local stats:")
for k, v in result["box_stats"].items():
    lines.append(f"- {k}: {v}")
lines.append("")
lines.append("candidate categories in top list:")
for k in category_order:
    lines.append(f"- {k}: {counts.get(k, 0)}")
ignore_count = 0
lines.append(f"- ignore for now: {ignore_count}")
lines.append("")
lines.append("top manual targets:")
for i, c in enumerate(candidates, start=1):
    lines.append(f"{i}. {c['item_type']} {c['id']} | {c['category']} | len={c['length_m']} | near={','.join(c['near_focus_junction_ids'])} | action={c['suggested_manual_action']} | reason={c['reason']}")
lines.append("")
lines.append("manual netedit checklist:")
lines.append("- inspect first: focus junction ids and top 8 ranked candidates")
lines.append("- inspect short edges under 7m before touching longer edges")
lines.append("- avoid touching major through-corridor edges unless artifact is obvious")
lines.append("- safe to remove only tiny isolated connectors that duplicate a nearby path")
lines.append("- do not change signal timing/program now; only inspect signalized node geometry")
lines.append("- do not collapse multi-leg junctions blindly; keep valid turn structure")
lines.append("- after each tiny edit, re-check local connectivity around focus nodes")

with out_txt.open("w", encoding="utf-8") as f:
    f.write("\n".join(lines))

print("done")
print("candidates", len(candidates))
print("short_edges", len(short_edges))
