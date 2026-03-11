from pathlib import Path
import re
import xml.etree.ElementTree as ET
import pandas as pd

root = Path(r"E:\project_sakif_chicago")
net_file = root / "net" / "map_reduced_clean_auto_v2.net.xml"
boundary_file = root / "Boundaries_-_Community_Areas_20260310.csv"
out_path = root / "output" / "network_boundary_overlap.txt"

if not net_file.exists() or not boundary_file.exists():
    raise SystemExit("required file missing")

net = ET.parse(net_file).getroot()
loc = net.find("location")
orig_boundary = None
conv_boundary = None
if loc is not None:
    orig_boundary = loc.get("origBoundary")
    conv_boundary = loc.get("convBoundary")

if not orig_boundary:
    raise SystemExit("origBoundary missing in network")

ominx, ominy, omaxx, omaxy = [float(x) for x in orig_boundary.split(",")]

bdf = pd.read_csv(boundary_file, dtype=str)
cols = list(bdf.columns)

id_field = "AREA_NUMBE" if "AREA_NUMBE" in cols else ("AREA_NUM_1" if "AREA_NUM_1" in cols else cols[0])
name_field = "COMMUNITY" if "COMMUNITY" in cols else ("community" if "community" in cols else cols[1])
geom_field = None
for c in cols:
    if "geom" in c.lower() or "wkt" in c.lower() or c.lower() == "geometry":
        geom_field = c
        break

if geom_field is None:
    raise SystemExit("geometry-like field not found")

num_re = re.compile(r"-?\d+\.\d+|-?\d+")

def geom_bbox(wkt):
    nums = [float(x) for x in num_re.findall(str(wkt))]
    if len(nums) < 4:
        return None
    xs = nums[0::2]
    ys = nums[1::2]
    return (min(xs), min(ys), max(xs), max(ys))

def intersects(a, b):
    return not (a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3])

def expand(box, d):
    return (box[0]-d, box[1]-d, box[2]+d, box[3]+d)

net_box = (ominx, ominy, omaxx, omaxy)
near_box = expand(net_box, 0.01)

overlap_rows = []
near_rows = []

for _, r in bdf.iterrows():
    bbox = geom_bbox(r.get(geom_field, ""))
    if bbox is None:
        continue
    area_id = str(r.get(id_field, "")).strip()
    area_name = str(r.get(name_field, "")).strip()
    entry = {
        "id": area_id,
        "name": area_name,
        "bbox": bbox,
    }
    if intersects(bbox, net_box):
        overlap_rows.append(entry)
    elif intersects(bbox, near_box):
        near_rows.append(entry)

overlap_rows = sorted(overlap_rows, key=lambda x: (x["id"], x["name"]))
near_rows = sorted(near_rows, key=lambda x: (x["id"], x["name"]))

lines = []
lines.append("Network-boundary overlap profile")
lines.append("network: " + str(net_file))
lines.append("boundary: " + str(boundary_file))
lines.append("")
lines.append("network convBoundary (projected): " + str(conv_boundary))
lines.append("network origBoundary (lon/lat): " + str(orig_boundary))
lines.append("")
lines.append("overlapping community areas:")
if overlap_rows:
    for e in overlap_rows:
        lines.append(f"- {e['id']} | {e['name']}")
else:
    lines.append("- none")
lines.append("")
lines.append("nearby community areas (+0.01 degree buffer):")
if near_rows:
    for e in near_rows:
        lines.append(f"- {e['id']} | {e['name']}")
else:
    lines.append("- none")

out_path.write_text("\n".join(lines), encoding="utf-8")
print("done")
print("overlap_count", len(overlap_rows))
print("near_count", len(near_rows))
