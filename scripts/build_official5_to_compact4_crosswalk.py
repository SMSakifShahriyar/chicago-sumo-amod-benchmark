import os
import csv
import json
import math
import xml.etree.ElementTree as ET


project_dir = r"E:\project_sakif_chicago"
network_file = os.path.join(project_dir, "net", "map_reduced_clean_auto_v2.net.xml")
compact_json_file = os.path.join(project_dir, "output", "compact_zone_candidates.json")

official_files = {
    8: os.path.join(project_dir, "data", "benchmark5_zone_edges_area8_unique.txt"),
    24: os.path.join(project_dir, "data", "benchmark5_zone_edges_area24_unique.txt"),
    28: os.path.join(project_dir, "data", "benchmark5_zone_edges_area28_unique.txt"),
    32: os.path.join(project_dir, "data", "benchmark5_zone_edges_area32_unique.txt"),
    33: os.path.join(project_dir, "data", "benchmark5_zone_edges_area33_unique.txt"),
}

official_names = {
    8: "NEAR NORTH SIDE",
    24: "WEST TOWN",
    28: "NEAR WEST SIDE",
    32: "LOOP",
    33: "NEAR SOUTH SIDE",
}

csv_out = os.path.join(project_dir, "output", "official5_to_compact4_crosswalk.csv")
json_out = os.path.join(project_dir, "output", "official5_to_compact4_crosswalk.json")
txt_out = os.path.join(project_dir, "output", "official5_to_compact4_crosswalk_summary.txt")


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


def read_edge_list(path):
    values = []
    if not os.path.exists(path):
        return values
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if s:
                values.append(s)
    return values


def distance(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


root = ET.parse(network_file).getroot()
edge_mid = {}
for edge in root.findall("edge"):
    eid = edge.get("id", "")
    if not eid or eid.startswith(":"):
        continue
    lane = edge.find("lane")
    shape = []
    if lane is not None:
        shape = parse_shape(lane.get("shape", ""))
    if not shape:
        shape = parse_shape(edge.get("shape", ""))
    if shape:
        edge_mid[eid] = shape[len(shape) // 2]

with open(compact_json_file, "r", encoding="utf-8") as f:
    compact = json.load(f)

zone_id_map = {"CZ1": "cz1", "CZ2": "cz2", "CZ3": "cz3", "CZ4": "cz4"}
compact_edges = {}
compact_centers = {}
for z in compact.get("zones", []):
    old_id = z.get("zone_id")
    if old_id not in zone_id_map:
        continue
    zid = zone_id_map[old_id]
    edges = set(z.get("edges", []))
    compact_edges[zid] = edges
    pts = [edge_mid[e] for e in edges if e in edge_mid]
    if pts:
        compact_centers[zid] = (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))

rows = []
summary_lines = []

for aid in [8, 24, 28, 32, 33]:
    oe = read_edge_list(official_files[aid])
    oe_set = set(oe)
    overlap_counts = {}
    for zid in ["cz1", "cz2", "cz3", "cz4"]:
        overlap_counts[zid] = len(oe_set.intersection(compact_edges.get(zid, set())))
    total_overlap = sum(overlap_counts.values())
    shares = {}
    if total_overlap > 0:
        for zid in overlap_counts:
            shares[zid] = overlap_counts[zid] / total_overlap
    else:
        shares = {zid: 0.0 for zid in ["cz1", "cz2", "cz3", "cz4"]}

    mapped_primary = max(shares.keys(), key=lambda z: (shares[z], overlap_counts[z]))
    fallback_used = "no"
    if total_overlap == 0:
        pts = [edge_mid[e] for e in oe if e in edge_mid]
        if pts:
            oc = (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
            mapped_primary = min(compact_centers.keys(), key=lambda z: distance(oc, compact_centers[z]))
            fallback_used = "yes"
            overlap_counts[mapped_primary] = 1
            shares[mapped_primary] = 1.0
        else:
            mapped_primary = "cz1"
            fallback_used = "yes"
            shares = {"cz1": 1.0, "cz2": 0.0, "cz3": 0.0, "cz4": 0.0}

    secondary = [z for z in ["cz1", "cz2", "cz3", "cz4"] if z != mapped_primary and shares[z] >= 0.2]
    split = "yes" if secondary else "no"

    dominant = sorted([f"{z}:{overlap_counts[z]} ({shares[z]:.3f})" for z in ["cz1", "cz2", "cz3", "cz4"]], key=lambda s: float(s.split("(")[1].split(")")[0]), reverse=True)
    row = {
        "official_area_id": aid,
        "official_area_name": official_names[aid],
        "official_unique_edge_count": len(oe),
        "overlap_total_edges": total_overlap,
        "primary_compact_zone": mapped_primary,
        "primary_share": round(shares.get(mapped_primary, 0.0), 6),
        "secondary_compact_zones": "|".join(secondary) if secondary else "",
        "is_split": split,
        "fallback_used": fallback_used,
        "share_cz1": round(shares.get("cz1", 0.0), 6),
        "share_cz2": round(shares.get("cz2", 0.0), 6),
        "share_cz3": round(shares.get("cz3", 0.0), 6),
        "share_cz4": round(shares.get("cz4", 0.0), 6),
        "overlap_cz1": overlap_counts.get("cz1", 0),
        "overlap_cz2": overlap_counts.get("cz2", 0),
        "overlap_cz3": overlap_counts.get("cz3", 0),
        "overlap_cz4": overlap_counts.get("cz4", 0),
    }
    rows.append(row)
    summary_lines.append(
        f"{aid} {official_names[aid]} -> primary={mapped_primary} share={row['primary_share']:.3f}, split={split}, secondary={row['secondary_compact_zones'] or 'none'}, overlap={'; '.join(dominant)}"
    )

os.makedirs(os.path.dirname(csv_out), exist_ok=True)

with open(csv_out, "w", newline="", encoding="utf-8") as f:
    fieldnames = list(rows[0].keys())
    w = csv.DictWriter(f, fieldnames=fieldnames)
    w.writeheader()
    for r in rows:
        w.writerow(r)

with open(json_out, "w", encoding="utf-8") as f:
    json.dump({
        "method": "edge-overlap with proximity fallback",
        "rows": rows
    }, f, indent=2)

split_count = sum(1 for r in rows if r["is_split"] == "yes")
many_to_one = len(set(r["primary_compact_zone"] for r in rows))

rule_lines = []
rule_lines.append("recommended_od_conversion_rule")
rule_lines.append("1. For each official OD flow O->D, split origin O across compact zones using O shares.")
rule_lines.append("2. Split destination D across compact zones using D shares.")
rule_lines.append("3. Allocate flow to compact pair (czo,czd) by O_share[czo] * D_share[czd].")
rule_lines.append("4. If official area has no overlap, use proximity fallback primary zone with share 1.0.")

with open(txt_out, "w", encoding="utf-8") as f:
    f.write("official5 to compact4 crosswalk summary\n\n")
    for line in summary_lines:
        f.write(line + "\n")
    f.write("\n")
    f.write(f"mapping_style={'mostly one-to-one' if split_count <= 1 else 'mixed split mapping'}\n")
    f.write(f"official_areas_split_count={split_count}\n")
    f.write(f"distinct_primary_compact_zones_used={many_to_one}\n")
    f.write("\n")
    for line in rule_lines:
        f.write(line + "\n")

print("crosswalk csv:", csv_out)
print("crosswalk json:", json_out)
print("crosswalk summary:", txt_out)
