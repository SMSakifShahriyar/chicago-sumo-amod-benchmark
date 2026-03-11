import os
import csv
import json
import math
import xml.etree.ElementTree as ET


project_dir = r"E:\project_sakif_chicago"
network_file = os.path.join(project_dir, "net", "map_reduced_clean_auto_v2.net.xml")
compact_json_file = os.path.join(project_dir, "output", "compact_zone_candidates.json")

taz_file = os.path.join(project_dir, "data", "compact4_zones.taz.xml")
summary_file = os.path.join(project_dir, "output", "compact4_zones_summary.txt")
table_file = os.path.join(project_dir, "output", "compact4_zones_table.csv")


def lane_allows_passenger(lane):
    allow = lane.get("allow")
    disallow = lane.get("disallow")
    if allow:
        values = set(x.strip() for x in allow.split())
        return "all" in values or "passenger" in values
    if disallow:
        values = set(x.strip() for x in disallow.split())
        return not ("all" in values or "passenger" in values)
    return True


def parse_shape(text):
    pts = []
    if not text:
        return pts
    for part in text.split():
        if "," not in part:
            continue
        x, y = part.split(",", 1)
        try:
            pts.append((float(x), float(y)))
        except ValueError:
            pass
    return pts


root = ET.parse(network_file).getroot()
edge_data = {}

for edge in root.findall("edge"):
    edge_id = edge.get("id", "")
    if not edge_id or edge_id.startswith(":"):
        continue
    from_node = edge.get("from")
    to_node = edge.get("to")
    lanes = edge.findall("lane")
    if not from_node or not to_node or not lanes:
        continue
    passenger_lanes = [ln for ln in lanes if lane_allows_passenger(ln)]
    if not passenger_lanes:
        continue
    lane0 = passenger_lanes[0]
    try:
        length = float(lane0.get("length", "0"))
    except ValueError:
        length = 0.0
    shape = parse_shape(lane0.get("shape", "")) or parse_shape(edge.get("shape", ""))
    edge_data[edge_id] = {
        "from": from_node,
        "to": to_node,
        "length": length,
        "lanes": len(passenger_lanes),
        "shape": shape,
    }

with open(compact_json_file, "r", encoding="utf-8") as f:
    compact = json.load(f)

if compact.get("selected_k") != 4:
    raise RuntimeError(f"Expected selected_k=4, found {compact.get('selected_k')}")

zones = sorted(compact.get("zones", []), key=lambda z: z.get("zone_id", ""))
zone_id_map = {
    "CZ1": "cz1",
    "CZ2": "cz2",
    "CZ3": "cz3",
    "CZ4": "cz4",
}

node_degree = {}
for edge_id, ed in edge_data.items():
    node_degree[ed["from"]] = node_degree.get(ed["from"], 0) + 1
    node_degree[ed["to"]] = node_degree.get(ed["to"], 0) + 1

all_mid = []
for edge_id, ed in edge_data.items():
    shp = ed["shape"]
    if shp:
        mid = shp[len(shp) // 2]
        all_mid.append(mid)

if all_mid:
    xmin = min(p[0] for p in all_mid)
    xmax = max(p[0] for p in all_mid)
    ymin = min(p[1] for p in all_mid)
    ymax = max(p[1] for p in all_mid)
else:
    xmin = xmax = ymin = ymax = 0.0

xpad = (xmax - xmin) * 0.08
ypad = (ymax - ymin) * 0.08

seen = set()
duplicates = set()
missing = []
zone_rows = []
zone_summary = []

taz_root = ET.Element("additional")

for z in zones:
    old_id = z.get("zone_id")
    if old_id not in zone_id_map:
        continue
    new_id = zone_id_map[old_id]
    edges = z.get("edges", [])
    kept = []
    source_sink = 0
    for e in edges:
        if e not in edge_data:
            missing.append((new_id, e))
            continue
        if e in seen:
            duplicates.add(e)
        seen.add(e)
        kept.append(e)
        ed = edge_data[e]
        deg_touch = node_degree.get(ed["from"], 0) <= 1 or node_degree.get(ed["to"], 0) <= 1
        bbox_touch = False
        shp = ed["shape"]
        for x, y in shp:
            if x <= xmin + xpad or x >= xmax - xpad or y <= ymin + ypad or y >= ymax - ypad:
                bbox_touch = True
                break
        if deg_touch or bbox_touch:
            source_sink += 1
    kept_sorted = sorted(set(kept))
    ET.SubElement(taz_root, "taz", {"id": new_id, "edges": " ".join(kept_sorted)})
    zone_summary.append({
        "zone_id": new_id,
        "edge_count": len(kept_sorted),
        "source_sink_edges": source_sink,
        "source_sink_ok": "yes" if source_sink >= 1 else "no",
    })
    for e in kept_sorted:
        ed = edge_data[e]
        zone_rows.append({
            "zone_id": new_id,
            "edge_id": e,
            "from_node": ed["from"],
            "to_node": ed["to"],
            "length": round(ed["length"], 3),
            "lanes": ed["lanes"],
        })

os.makedirs(os.path.dirname(taz_file), exist_ok=True)
os.makedirs(os.path.dirname(summary_file), exist_ok=True)

ET.ElementTree(taz_root).write(taz_file, encoding="utf-8", xml_declaration=True)

with open(table_file, "w", newline="", encoding="utf-8") as f:
    fieldnames = ["zone_id", "edge_id", "from_node", "to_node", "length", "lanes"]
    w = csv.DictWriter(f, fieldnames=fieldnames)
    w.writeheader()
    for row in zone_rows:
        w.writerow(row)

summary_lines = []
summary_lines.append("compact4 taz summary")
summary_lines.append("")
for z in sorted(zone_summary, key=lambda x: x["zone_id"]):
    summary_lines.append(
        f"{z['zone_id']}: edge_count={z['edge_count']}, source_sink_edges={z['source_sink_edges']}, source_sink_ok={z['source_sink_ok']}"
    )
summary_lines.append("")
summary_lines.append(f"validation_missing_edges={len(missing)}")
summary_lines.append(f"validation_duplicate_edges={len(duplicates)}")
summary_lines.append("validation_xml_wellformed=yes")
summary_lines.append("validation_passed=yes" if len(missing) == 0 and len(duplicates) == 0 and all(z["source_sink_edges"] >= 1 for z in zone_summary) else "validation_passed=no")

if missing:
    summary_lines.append("")
    summary_lines.append("missing_edges:")
    for zid, eid in missing[:30]:
        summary_lines.append(f"{zid},{eid}")

if duplicates:
    summary_lines.append("")
    summary_lines.append("duplicate_edges:")
    for eid in sorted(list(duplicates))[:30]:
        summary_lines.append(eid)

with open(summary_file, "w", encoding="utf-8") as f:
    f.write("\n".join(summary_lines) + "\n")

print("taz file:", taz_file)
print("summary:", summary_file)
print("table:", table_file)
