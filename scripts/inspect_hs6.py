import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET

root = Path(r"E:\project_sakif_chicago")
net_file = root / "net" / "map_reduced.net.xml"
out_json = root / "output" / "hs6_detail.json"
out_txt = root / "output" / "hs6_detail.txt"

center_x = 639.548
center_y = 942.371
focus_ids = [
    "10922644190",
    "9913028598",
    "2284331776",
    "9913028592",
    "13328987946",
]

if not net_file.exists():
    print("network file missing:", net_file)
    raise SystemExit(1)

tree = ET.parse(net_file)
net = tree.getroot()

junctions = {}
for j in net.findall("junction"):
    jid = j.get("id", "")
    x = float(j.get("x", "0") or 0)
    y = float(j.get("y", "0") or 0)
    inclanes = [v for v in (j.get("incLanes", "") or "").split(" ") if v]
    intlanes = [v for v in (j.get("intLanes", "") or "").split(" ") if v]
    junctions[jid] = {
        "id": jid,
        "x": x,
        "y": y,
        "type": j.get("type", ""),
        "inc_lane_count": len(inclanes),
        "int_lane_count": len(intlanes),
    }

edge_map = {}
incoming = {}
outgoing = {}
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
    outgoing.setdefault(fr, []).append(eid)
    incoming.setdefault(to, []).append(eid)

all_normal_junctions = []
for jid, j in junctions.items():
    if j["type"] != "internal" and not jid.startswith(":"):
        all_normal_junctions.append((jid, j["x"], j["y"], j["type"]))

neighbor_radius = 60.0
short_edge_threshold = 12.0
cluster_radius = 45.0

result = {
    "center": {"x": center_x, "y": center_y},
    "focus_junction_ids": focus_ids,
    "junctions": [],
}

present = []
for fid in focus_ids:
    if fid in junctions:
        present.append(fid)

xs = [center_x]
ys = [center_y]
for fid in present:
    xs.append(junctions[fid]["x"])
    ys.append(junctions[fid]["y"])

pad = 80.0
bbox = {
    "xmin": round(min(xs) - pad, 3),
    "xmax": round(max(xs) + pad, 3),
    "ymin": round(min(ys) - pad, 3),
    "ymax": round(max(ys) + pad, 3),
}
result["inspection_bbox"] = bbox

for fid in focus_ids:
    if fid not in junctions:
        result["junctions"].append({
            "junction_id": fid,
            "found": False,
        })
        continue

    j = junctions[fid]
    in_edges = incoming.get(fid, [])
    out_edges = outgoing.get(fid, [])

    connected_lanes = 0
    for eid in in_edges + out_edges:
        connected_lanes += edge_map.get(eid, {}).get("lane_count", 0)

    short_edges = []
    for eid in in_edges + out_edges:
        e = edge_map.get(eid)
        if not e:
            continue
        if e["length"] <= short_edge_threshold:
            short_edges.append({
                "edge_id": eid,
                "length": round(e["length"], 3),
                "from": e["from"],
                "to": e["to"],
            })

    neighbors = []
    for jid, x, y, jtype in all_normal_junctions:
        if jid == fid:
            continue
        d = math.hypot(x - j["x"], y - j["y"])
        if d <= neighbor_radius:
            neighbors.append({
                "junction_id": jid,
                "distance": round(d, 3),
                "type": jtype,
            })
    neighbors.sort(key=lambda n: n["distance"])

    tiny_cluster = False
    tiny_cluster_reason = []
    if len(short_edges) >= 3:
        tiny_cluster = True
        tiny_cluster_reason.append("many_very_short_edges")
    close_n = 0
    for n in neighbors:
        if n["distance"] <= cluster_radius:
            close_n += 1
    if close_n >= 12:
        tiny_cluster = True
        tiny_cluster_reason.append("dense_nearby_junction_cluster")
    if j["type"] == "dead_end" and len(short_edges) >= 2 and close_n >= 6:
        tiny_cluster = True
        tiny_cluster_reason.append("dead_end_inside_dense_area")

    result["junctions"].append({
        "junction_id": fid,
        "found": True,
        "x": round(j["x"], 3),
        "y": round(j["y"], 3),
        "type": j["type"],
        "incoming_edge_ids": in_edges,
        "outgoing_edge_ids": out_edges,
        "connected_lane_count_est": connected_lanes,
        "nearby_very_short_edges_le_12m": short_edges,
        "nearby_junction_ids_within_60m": neighbors,
        "likely_tiny_broken_cluster": tiny_cluster,
        "tiny_cluster_reasons": tiny_cluster_reason,
    })

all_jids_in_box = []
for jid, x, y, jtype in all_normal_junctions:
    if bbox["xmin"] <= x <= bbox["xmax"] and bbox["ymin"] <= y <= bbox["ymax"]:
        all_jids_in_box.append((jid, jtype, x, y))

box_short_edges = []
for eid, e in edge_map.items():
    fr = e["from"]
    to = e["to"]
    if fr in junctions and to in junctions:
        fx = junctions[fr]["x"]
        fy = junctions[fr]["y"]
        tx = junctions[to]["x"]
        ty = junctions[to]["y"]
        in_box = (
            bbox["xmin"] <= fx <= bbox["xmax"] and
            bbox["ymin"] <= fy <= bbox["ymax"] and
            bbox["xmin"] <= tx <= bbox["xmax"] and
            bbox["ymin"] <= ty <= bbox["ymax"]
        )
        if in_box and e["length"] <= short_edge_threshold:
            box_short_edges.append({
                "edge_id": eid,
                "length": round(e["length"], 3),
                "from": fr,
                "to": to,
            })

result["box_stats"] = {
    "junctions_in_box": len(all_jids_in_box),
    "short_edges_in_box_le_12m": len(box_short_edges),
    "short_edges_examples": box_short_edges[:30],
}

manual_plan = []
manual_plan.append("inspect top 5 focus junctions first")
if result["box_stats"]["short_edges_in_box_le_12m"] >= 15:
    manual_plan.append("check tiny edges and merge/remove artifact segments")
if any(j.get("type") == "dead_end" and j.get("likely_tiny_broken_cluster") for j in result["junctions"] if j.get("found")):
    manual_plan.append("inspect dead_end nodes in dense center for artifact dead-ends")
if sum(1 for j in result["junctions"] if j.get("found") and j.get("type") == "traffic_light") >= 3:
    manual_plan.append("inspect traffic-light nodes for over-split approaches and short connectors")
if not manual_plan:
    manual_plan.append("low urgency")

result["recommendation"] = {
    "should_ignore": False,
    "should_manual_cleanup": True,
    "suggested_edit_types": [
        "merge_or_remove_tiny_artifact_edges",
        "fix_dead_end_artifact",
        "simplify_local_junction_cluster",
        "inspect_signalized_node_structure",
    ],
    "manual_plan": manual_plan,
}

out_json.write_text(json.dumps(result, indent=2), encoding="utf-8")

lines = []
lines.append("HS6 detail inspection")
lines.append("network: " + str(net_file))
lines.append(f"center: ({center_x}, {center_y})")
lines.append("")
lines.append("inspection bbox:")
lines.append(f"xmin={bbox['xmin']} xmax={bbox['xmax']} ymin={bbox['ymin']} ymax={bbox['ymax']}")
lines.append("")
lines.append("focus junction findings:")
for item in result["junctions"]:
    if not item.get("found"):
        lines.append(f"- {item['junction_id']}: not found")
        continue
    lines.append(
        f"- {item['junction_id']} type={item['type']} x={item['x']} y={item['y']} in={len(item['incoming_edge_ids'])} out={len(item['outgoing_edge_ids'])} lanes={item['connected_lane_count_est']} short<=12m={len(item['nearby_very_short_edges_le_12m'])} neighbors<=60m={len(item['nearby_junction_ids_within_60m'])} tiny_cluster={item['likely_tiny_broken_cluster']}"
    )
lines.append("")
lines.append("box stats:")
lines.append(f"junctions_in_box={result['box_stats']['junctions_in_box']}")
lines.append(f"short_edges_in_box_le_12m={result['box_stats']['short_edges_in_box_le_12m']}")
lines.append("")
lines.append("recommendation:")
lines.append("ignore: no")
lines.append("manual_cleanup: yes")
for step in manual_plan:
    lines.append("- " + step)

out_txt.write_text("\n".join(lines), encoding="utf-8")

print("done")
print("bbox", bbox)
print("short_edges_in_box", result["box_stats"]["short_edges_in_box_le_12m"])
