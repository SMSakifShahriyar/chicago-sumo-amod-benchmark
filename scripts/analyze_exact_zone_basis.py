from pathlib import Path
import csv
import re
import xml.etree.ElementTree as ET
import pandas as pd

root = Path(r"E:\project_sakif_chicago")
net_file = root / "net" / "map_reduced_clean_auto_v2.net.xml"
boundary_file = root / "Boundaries_-_Community_Areas_20260310.csv"
taxi_file = root / "Taxi_Trips_(2024-)_20260310.csv"

out_overlap = root / "output" / "community_area_overlap_exact.txt"
out_scenarios = root / "output" / "community_area_retention_scenarios.csv"
out_summary = root / "output" / "community_area_retention_summary.txt"
out_od = root / "output" / "community_area_od_exact.csv"

if not net_file.exists() or not boundary_file.exists() or not taxi_file.exists():
    raise SystemExit("required file missing")

net = ET.parse(net_file).getroot()
loc = net.find("location")
if loc is None:
    raise SystemExit("network location block missing")
orig_boundary = loc.get("origBoundary")
if not orig_boundary:
    raise SystemExit("origBoundary missing")
ominx, ominy, omaxx, omaxy = [float(x) for x in orig_boundary.split(",")]

num_re = re.compile(r"-?\d+(?:\.\d+)?")

def extract_coords_from_wkt(wkt):
    nums = [float(x) for x in num_re.findall(str(wkt))]
    if len(nums) < 4:
        return []
    return list(zip(nums[0::2], nums[1::2]))

def bbox_from_coords(coords):
    xs = [p[0] for p in coords]
    ys = [p[1] for p in coords]
    return (min(xs), min(ys), max(xs), max(ys))

def intersects(a, b):
    return not (a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3])

def expand(box, d):
    return (box[0] - d, box[1] - d, box[2] + d, box[3] + d)

def bbox_distance(a, b):
    if intersects(a, b):
        return 0.0
    dx = 0.0
    if a[2] < b[0]:
        dx = b[0] - a[2]
    elif b[2] < a[0]:
        dx = a[0] - b[2]
    dy = 0.0
    if a[3] < b[1]:
        dy = b[1] - a[3]
    elif b[3] < a[1]:
        dy = a[1] - b[3]
    return (dx * dx + dy * dy) ** 0.5

net_box = (ominx, ominy, omaxx, omaxy)
near_buffer_deg = 0.01
near_box = expand(net_box, near_buffer_deg)

bdf = pd.read_csv(boundary_file, dtype=str)
if "AREA_NUMBE" not in bdf.columns or "COMMUNITY" not in bdf.columns or "the_geom" not in bdf.columns:
    raise SystemExit("boundary expected columns missing")

areas = []
for _, row in bdf.iterrows():
    area_id = str(row["AREA_NUMBE"]).strip()
    area_name = str(row["COMMUNITY"]).strip()
    coords = extract_coords_from_wkt(row["the_geom"])
    if not coords:
        continue
    box = bbox_from_coords(coords)
    overlap = intersects(box, net_box)
    near = (not overlap) and intersects(box, near_box)
    dist = bbox_distance(box, net_box)
    areas.append({
        "id": area_id,
        "name": area_name,
        "bbox": box,
        "overlap": overlap,
        "near": near,
        "distance_deg": dist,
    })

overlap_areas = sorted([a for a in areas if a["overlap"]], key=lambda x: int(x["id"]))
nearby_areas = sorted([a for a in areas if a["near"]], key=lambda x: int(x["id"]))

overlap_ids = {a["id"] for a in overlap_areas}
nearby_ids = {a["id"] for a in nearby_areas}
overlap_plus_near = overlap_ids | nearby_ids

usecols = ["Pickup Community Area", "Dropoff Community Area", "Trip Start Timestamp"]
tdf = pd.read_csv(taxi_file, dtype=str, usecols=usecols)
tdf["Pickup Community Area"] = tdf["Pickup Community Area"].fillna("").str.strip()
tdf["Dropoff Community Area"] = tdf["Dropoff Community Area"].fillna("").str.strip()
mask_both = (tdf["Pickup Community Area"] != "") & (tdf["Dropoff Community Area"] != "")
both_df = tdf.loc[mask_both, ["Pickup Community Area", "Dropoff Community Area", "Trip Start Timestamp"]].copy()
both_count = len(both_df)

scenario_masks = {}
scenario_masks["A"] = both_df["Pickup Community Area"].isin(overlap_ids) & both_df["Dropoff Community Area"].isin(overlap_ids)
scenario_masks["B"] = both_df["Pickup Community Area"].isin(overlap_plus_near) & both_df["Dropoff Community Area"].isin(overlap_plus_near)
scenario_masks["C"] = both_df["Pickup Community Area"].isin(overlap_ids) | both_df["Dropoff Community Area"].isin(overlap_ids)
scenario_masks["D"] = both_df["Pickup Community Area"].isin(overlap_plus_near) | both_df["Dropoff Community Area"].isin(overlap_plus_near)

scenario_rows = []
od_rows = []

def top_flows(df, topn=10):
    g = df.groupby(["Pickup Community Area", "Dropoff Community Area"]).size().reset_index(name="count")
    g = g.sort_values("count", ascending=False)
    return g, g.head(topn)

for sid in ["A", "B", "C", "D"]:
    sdf = both_df.loc[scenario_masks[sid]].copy()
    retained = len(sdf)
    pct = (retained / both_count * 100.0) if both_count else 0.0
    od_all, od_top = top_flows(sdf)
    scenario_rows.append({
        "scenario": sid,
        "retained_rows": retained,
        "percent_of_rows_with_both_ca": round(pct, 4),
        "od_matrix_size": int(len(od_all)),
        "dominant_flows_top10": " | ".join([f"{r['Pickup Community Area']}->{r['Dropoff Community Area']}:{int(r['count'])}" for _, r in od_top.iterrows()]),
    })

    for _, r in od_all.iterrows():
        od_rows.append({
            "scenario": sid,
            "pickup_community_area": r["Pickup Community Area"],
            "dropoff_community_area": r["Dropoff Community Area"],
            "count": int(r["count"]),
        })

with out_scenarios.open("w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=["scenario", "retained_rows", "percent_of_rows_with_both_ca", "od_matrix_size", "dominant_flows_top10"])
    w.writeheader()
    for r in scenario_rows:
        w.writerow(r)

with out_od.open("w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=["scenario", "pickup_community_area", "dropoff_community_area", "count"])
    w.writeheader()
    for r in sorted(od_rows, key=lambda x: (x["scenario"], -x["count"], x["pickup_community_area"], x["dropoff_community_area"])):
        w.writerow(r)

lines = []
lines.append("Community area overlap exact")
lines.append("network_orig_boundary: " + orig_boundary)
lines.append(f"near_buffer_deg_for_nearby_nonoverlap: {near_buffer_deg}")
lines.append("")
lines.append("overlapping community areas:")
for a in overlap_areas:
    lines.append(f"- {a['id']} | {a['name']} | distance_deg={a['distance_deg']}")
lines.append("")
lines.append("nearby but non-overlapping community areas:")
for a in nearby_areas:
    lines.append(f"- {a['id']} | {a['name']} | distance_deg={a['distance_deg']}")
out_overlap.write_text("\n".join(lines), encoding="utf-8")

scenario_map = {r["scenario"]: r for r in scenario_rows}

lines2 = []
lines2.append("Community area retention summary")
lines2.append("taxi_rows_with_both_community_area: " + str(both_count))
lines2.append("")
for sid in ["A", "B", "C", "D"]:
    r = scenario_map[sid]
    lines2.append(f"scenario_{sid}: retained_rows={r['retained_rows']} percent_of_both_ca={r['percent_of_rows_with_both_ca']} od_matrix_size={r['od_matrix_size']}")
    lines2.append("dominant_flows: " + r["dominant_flows_top10"])
    lines2.append("")

lines2.append("evidence-based recommendation:")
lines2.append("- overlap set ids: " + ", ".join(sorted(overlap_ids, key=int)))
lines2.append("- overlap+near set ids: " + ", ".join(sorted(overlap_plus_near, key=int)))

countA = scenario_map["A"]["retained_rows"]
countB = scenario_map["B"]["retained_rows"]
if countB > countA:
    lines2.append("- adding nearby areas increases retained demand relative to overlap-only")
else:
    lines2.append("- adding nearby areas does not increase retained demand")

out_summary.write_text("\n".join(lines2), encoding="utf-8")

print("done")
print("both_ca_rows", both_count)
print("overlap_ids", sorted(overlap_ids, key=int))
print("nearby_ids", sorted(nearby_ids, key=int))
for sid in ["A", "B", "C", "D"]:
    r = scenario_map[sid]
    print(sid, r["retained_rows"], r["percent_of_rows_with_both_ca"], r["od_matrix_size"])
