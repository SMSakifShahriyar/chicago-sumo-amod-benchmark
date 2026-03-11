from pathlib import Path
import re
import xml.etree.ElementTree as ET
import pandas as pd

root = Path(r"E:\project_sakif_chicago")
boundary_file = root / "Boundaries_-_Community_Areas_20260310.csv"
net_file = root / "net" / "map_reduced_clean_auto_v2.net.xml"
out_file = root / "data" / "benchmark5_community_areas.csv"
summary_file = root / "output" / "benchmark5_demand_summary.txt"

area_ids = ["8", "24", "28", "32", "33"]

if not boundary_file.exists() or not net_file.exists():
    raise SystemExit("required file missing")

bdf = pd.read_csv(boundary_file, dtype=str)
bdf["AREA_NUMBE"] = bdf["AREA_NUMBE"].astype(str).str.strip()
keep = bdf[bdf["AREA_NUMBE"].isin(area_ids)].copy()
keep.to_csv(out_file, index=False)

num_re = re.compile(r"-?\d+(?:\.\d+)?")

def coords_from_wkt(wkt):
    nums = [float(x) for x in num_re.findall(str(wkt))]
    if len(nums) < 4:
        return []
    return list(zip(nums[0::2], nums[1::2]))

def bbox(coords):
    xs = [p[0] for p in coords]
    ys = [p[1] for p in coords]
    return (min(xs), min(ys), max(xs), max(ys))

def intersect(a, b):
    return not (a[2] <= b[0] or a[0] >= b[2] or a[3] <= b[1] or a[1] >= b[3])

def intersection_area(a, b):
    ix1 = max(a[0], b[0])
    iy1 = max(a[1], b[1])
    ix2 = min(a[2], b[2])
    iy2 = min(a[3], b[3])
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    return (ix2 - ix1) * (iy2 - iy1)

def box_area(a):
    return max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])

net = ET.parse(net_file).getroot()
loc = net.find("location")
orig = loc.get("origBoundary") if loc is not None else None
if not orig:
    raise SystemExit("origBoundary missing")
net_box = tuple(float(x) for x in orig.split(","))

rows = []
for _, r in keep.iterrows():
    coords = coords_from_wkt(r.get("the_geom", ""))
    if not coords:
        continue
    b = bbox(coords)
    ia = intersection_area(b, net_box)
    ba = box_area(b)
    ratio = (ia / ba) if ba > 0 else 0.0
    intersects = intersect(b, net_box)

    if intersects and ratio >= 0.15:
        cls = "overlap_strong"
    elif intersects:
        cls = "overlap_partial"
    else:
        cls = "near_or_outside"

    rows.append({
        "area_id": str(r.get("AREA_NUMBE", "")).strip(),
        "area_name": str(r.get("COMMUNITY", "")).strip(),
        "bbox_min_lon": b[0],
        "bbox_min_lat": b[1],
        "bbox_max_lon": b[2],
        "bbox_max_lat": b[3],
        "bbox_intersection_area_with_network": ia,
        "bbox_area": ba,
        "bbox_intersection_ratio": ratio,
        "overlap_class": cls,
    })

lines = []
if summary_file.exists():
    lines = summary_file.read_text(encoding="utf-8").splitlines()

lines.append("")
lines.append("boundary/network overlap caveats for selected 5 official areas:")
for r in sorted(rows, key=lambda x: int(x["area_id"])):
    lines.append(
        f"- {r['area_id']} {r['area_name']} | class={r['overlap_class']} | bbox_intersection_ratio={round(r['bbox_intersection_ratio'],6)}"
    )

for r in rows:
    if r["overlap_class"] != "overlap_strong":
        lines.append(f"- special_care_needed_for_mapping: {r['area_id']} {r['area_name']}")

summary_file.write_text("\n".join(lines), encoding="utf-8")

print("done")
print("clipped_features", len(keep))
for r in sorted(rows, key=lambda x: int(x["area_id"])):
    print(r["area_id"], r["area_name"], r["overlap_class"], round(r["bbox_intersection_ratio"], 6))
