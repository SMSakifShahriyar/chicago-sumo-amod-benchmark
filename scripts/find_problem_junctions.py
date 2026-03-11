import csv
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET

root = Path(r"E:\project_sakif_chicago")
net_file = root / "net" / "map_reduced.net.xml"
out_csv = root / "output" / "problem_junctions.csv"
out_json = root / "output" / "problem_junctions.json"
out_summary = root / "output" / "problem_junctions_summary.txt"
out_top = root / "output" / "problem_junctions_top_ids.txt"

if not net_file.exists():
    print("network file not found:", net_file)
    raise SystemExit(1)

tree = ET.parse(net_file)
net = tree.getroot()

junctions = {}
normal_junction_ids = []
for j in net.findall("junction"):
    jid = j.get("id", "")
    jtype = j.get("type", "")
    x = float(j.get("x", "0") or 0)
    y = float(j.get("y", "0") or 0)
    inclanes = [v for v in (j.get("incLanes", "") or "").split(" ") if v]
    intlanes = [v for v in (j.get("intLanes", "") or "").split(" ") if v]
    if jtype != "internal" and not jid.startswith(":"):
        normal_junction_ids.append(jid)
    junctions[jid] = {
        "id": jid,
        "x": x,
        "y": y,
        "type": jtype,
        "inc_lane_count": len(inclanes),
        "int_lane_count": len(intlanes),
    }

x_vals = [junctions[j]["x"] for j in normal_junction_ids if j in junctions]
y_vals = [junctions[j]["y"] for j in normal_junction_ids if j in junctions]
if not x_vals or not y_vals:
    print("no usable normal junctions found")
    raise SystemExit(1)

xmin, xmax = min(x_vals), max(x_vals)
ymin, ymax = min(y_vals), max(y_vals)
width = max(1.0, xmax - xmin)
height = max(1.0, ymax - ymin)
margin = max(50.0, min(width, height) * 0.08)

incident_edges = {jid: [] for jid in normal_junction_ids}
in_counts = {jid: 0 for jid in normal_junction_ids}
out_counts = {jid: 0 for jid in normal_junction_ids}

for e in net.findall("edge"):
    if e.get("function"):
        continue
    eid = e.get("id", "")
    fr = e.get("from", "")
    to = e.get("to", "")
    lane = e.find("lane")
    length = None
    if lane is not None:
        try:
            length = float(lane.get("length", "0") or 0)
        except ValueError:
            length = 0.0
    else:
        length = 0.0
    data = {"id": eid, "from": fr, "to": to, "length": length}
    if fr in incident_edges:
        incident_edges[fr].append(data)
        out_counts[fr] += 1
    if to in incident_edges:
        incident_edges[to].append(data)
        in_counts[to] += 1

neighbor_map = {jid: set() for jid in normal_junction_ids}
for jid in normal_junction_ids:
    for e in incident_edges.get(jid, []):
        if e["from"] == jid and e["to"] in neighbor_map:
            neighbor_map[jid].add(e["to"])
        if e["to"] == jid and e["from"] in neighbor_map:
            neighbor_map[jid].add(e["from"])

points = [(jid, junctions[jid]["x"], junctions[jid]["y"]) for jid in normal_junction_ids]

rows = []
for jid in normal_junction_ids:
    j = junctions[jid]
    x = j["x"]
    y = j["y"]
    deg = len(neighbor_map[jid])
    total_edges = in_counts[jid] + out_counts[jid]
    short10 = 0
    short20 = 0
    very_short_ids = []
    for e in incident_edges[jid]:
        if e["length"] <= 10:
            short10 += 1
            very_short_ids.append(e["id"])
        if e["length"] <= 20:
            short20 += 1
    dense_neighbors_30 = 0
    for other_id, ox, oy in points:
        if other_id == jid:
            continue
        if math.hypot(ox - x, oy - y) <= 30:
            dense_neighbors_30 += 1
    near_boundary = (
        x <= xmin + margin or
        x >= xmax - margin or
        y <= ymin + margin or
        y >= ymax - margin
    )
    reasons = []
    score = 0.0
    if deg >= 7:
        reasons.append(f"high_degree:{deg}")
        score += 2.0 + (deg - 6) * 0.8
    if total_edges >= 10:
        reasons.append(f"many_incident_edges:{total_edges}")
        score += 1.6 + (total_edges - 9) * 0.5
    if j["int_lane_count"] >= 16:
        reasons.append(f"many_internal_lanes:{j['int_lane_count']}")
        score += 1.8 + (j["int_lane_count"] - 15) * 0.2
    if short10 >= 2:
        reasons.append(f"multiple_very_short_edges:{short10}")
        score += 2.2 + (short10 - 1) * 0.6
    elif short20 >= 3:
        reasons.append(f"many_short_edges:{short20}")
        score += 1.4 + (short20 - 2) * 0.5
    if dense_neighbors_30 >= 8:
        reasons.append(f"dense_local_geometry:{dense_neighbors_30}")
        score += 1.8 + (dense_neighbors_30 - 7) * 0.2
    if j["type"] == "traffic_light":
        if deg <= 1:
            reasons.append("traffic_light_low_degree")
            score += 2.0
        if j["int_lane_count"] < 2 and total_edges >= 4:
            reasons.append("traffic_light_low_internal_lanes")
            score += 1.5
        if short10 >= 2:
            reasons.append("traffic_light_short_edge_cluster")
            score += 1.2
    else:
        if deg >= 6 and j["int_lane_count"] >= 12:
            reasons.append("non_tl_high_complexity")
            score += 2.0
    if j["type"] == "dead_end" and not near_boundary:
        reasons.append("dead_end_not_near_boundary")
        score += 2.4
    if j["type"] != "dead_end" and deg == 0:
        reasons.append("isolated_non_dead_end")
        score += 2.4

    if reasons:
        rows.append({
            "junction_id": jid,
            "x": round(x, 3),
            "y": round(y, 3),
            "junction_type": j["type"],
            "degree": deg,
            "incident_edges": total_edges,
            "inc_lanes": j["inc_lane_count"],
            "internal_lanes": j["int_lane_count"],
            "short_edges_le_10m": short10,
            "short_edges_le_20m": short20,
            "dense_neighbors_30m": dense_neighbors_30,
            "near_boundary": near_boundary,
            "score": round(score, 3),
            "reasons": ";".join(reasons),
            "very_short_edge_ids": ";".join(very_short_ids[:10]),
        })

rows.sort(key=lambda r: r["score"], reverse=True)

with out_csv.open("w", newline="", encoding="utf-8") as f:
    fieldnames = [
        "rank",
        "junction_id",
        "x",
        "y",
        "junction_type",
        "degree",
        "incident_edges",
        "inc_lanes",
        "internal_lanes",
        "short_edges_le_10m",
        "short_edges_le_20m",
        "dense_neighbors_30m",
        "near_boundary",
        "score",
        "reasons",
        "very_short_edge_ids",
    ]
    w = csv.DictWriter(f, fieldnames=fieldnames)
    w.writeheader()
    for i, r in enumerate(rows, start=1):
        data = dict(r)
        data["rank"] = i
        w.writerow(data)

with out_json.open("w", encoding="utf-8") as f:
    json.dump(rows, f, indent=2)

top15 = rows[:15]
with out_top.open("w", encoding="utf-8") as f:
    for r in top15:
        f.write(r["junction_id"] + "\n")

lines = []
lines.append("Problem junction diagnostic summary")
lines.append("")
lines.append("Network file: " + str(net_file))
lines.append("Total normal junctions: " + str(len(normal_junction_ids)))
lines.append("Flagged junctions: " + str(len(rows)))
lines.append("Heuristics used:")
lines.append("- high degree junctions")
lines.append("- high incident edge count")
lines.append("- many internal lanes")
lines.append("- clusters of short edges")
lines.append("- dense local geometry (neighbors within 30m)")
lines.append("- unusual traffic-light structure")
lines.append("- unusual non-traffic-light complexity")
lines.append("- dead-end away from boundary")
lines.append("")
lines.append("Top 15 suspicious junctions:")
for i, r in enumerate(top15, start=1):
    lines.append(
        f"{i}. {r['junction_id']} | score={r['score']} | type={r['junction_type']} | degree={r['degree']} | short<=10m={r['short_edges_le_10m']} | reasons={r['reasons']}"
    )

out_summary.write_text("\n".join(lines), encoding="utf-8")

print("done")
print("flagged_junctions:", len(rows))
if rows:
    print("top_junction:", rows[0]["junction_id"], rows[0]["score"])
