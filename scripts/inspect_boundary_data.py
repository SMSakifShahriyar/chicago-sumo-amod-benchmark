from pathlib import Path
import re
import pandas as pd

root = Path(r"E:\project_sakif_chicago")
file_path = root / "Boundaries_-_Community_Areas_20260310.csv"
out_path = root / "output" / "boundary_data_profile.txt"

if not file_path.exists():
    raise SystemExit("boundary file not found")

df = pd.read_csv(file_path, dtype=str)
columns = list(df.columns)

id_candidates = ["AREA_NUMBE", "AREA_NUM_1", "area_numbe", "area_num_1", "community_area", "community"]
name_candidates = ["COMMUNITY", "community", "AREA_NAME", "area_name", "name"]
geom_candidates = [c for c in columns if "geom" in c.lower() or "wkt" in c.lower() or c.lower() == "geometry"]

id_field = next((c for c in id_candidates if c in columns), None)
name_field = next((c for c in name_candidates if c in columns), None)
geom_field = geom_candidates[0] if geom_candidates else None

feature_count = len(df)

num_re = re.compile(r"-?\d+\.\d+|-?\d+")
all_lons = []
all_lats = []

if geom_field:
    for val in df[geom_field].fillna("").astype(str):
        nums = [float(x) for x in num_re.findall(val)]
        if len(nums) < 4:
            continue
        coords = list(zip(nums[0::2], nums[1::2]))
        for lon, lat in coords[:2000]:
            all_lons.append(lon)
            all_lats.append(lat)

crs_guess = "unknown"
if all_lons and all_lats:
    if min(all_lons) >= -180 and max(all_lons) <= 180 and min(all_lats) >= -90 and max(all_lats) <= 90:
        crs_guess = "likely EPSG:4326 (lon/lat)"

lines = []
lines.append("Boundary data profile")
lines.append("file: " + str(file_path))
lines.append("feature_count: " + str(feature_count))
lines.append("")
lines.append("columns:")
for c in columns:
    lines.append("- " + c)
lines.append("")
lines.append("detected fields:")
lines.append("- area id field: " + str(id_field))
lines.append("- area name field: " + str(name_field))
lines.append("- geometry field: " + str(geom_field))
lines.append("- crs/projection guess: " + crs_guess)

if id_field and name_field:
    lines.append("")
    lines.append("sample areas:")
    sample = df[[id_field, name_field]].head(15)
    for _, row in sample.iterrows():
        lines.append(f"- {row[id_field]} | {row[name_field]}")

out_path.write_text("\n".join(lines), encoding="utf-8")
print("done")
print("features", feature_count)
print("id_field", id_field)
print("name_field", name_field)
print("geom_field", geom_field)
print("crs", crs_guess)
