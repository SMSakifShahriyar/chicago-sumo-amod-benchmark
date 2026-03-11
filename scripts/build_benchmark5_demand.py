from pathlib import Path
import csv
import xml.etree.ElementTree as ET
import pandas as pd

root = Path(r"E:\project_sakif_chicago")
taxi_file = root / "Taxi_Trips_(2024-)_20260310.csv"
boundary_file = root / "Boundaries_-_Community_Areas_20260310.csv"
net_file = root / "net" / "map_reduced_clean_auto_v2.net.xml"

out_od = root / "output" / "benchmark5_od_matrix.csv"
out_area = root / "output" / "benchmark5_area_summary.csv"
out_time = root / "output" / "benchmark5_time_profile.csv"
out_summary = root / "output" / "benchmark5_demand_summary.txt"

area_ids = ["8", "24", "28", "32", "33"]

if not taxi_file.exists() or not boundary_file.exists() or not net_file.exists():
    raise SystemExit("required file missing")

bdf = pd.read_csv(boundary_file, dtype=str, usecols=["AREA_NUMBE", "COMMUNITY"])
bdf["AREA_NUMBE"] = bdf["AREA_NUMBE"].astype(str).str.strip()
name_map = {r["AREA_NUMBE"]: str(r["COMMUNITY"]).strip() for _, r in bdf.iterrows() if str(r["AREA_NUMBE"]).strip() in area_ids}

usecols = ["Pickup Community Area", "Dropoff Community Area", "Trip Start Timestamp"]
df = pd.read_csv(taxi_file, dtype=str, usecols=usecols)
df["Pickup Community Area"] = df["Pickup Community Area"].fillna("").str.strip()
df["Dropoff Community Area"] = df["Dropoff Community Area"].fillna("").str.strip()

filtered = df[
    df["Pickup Community Area"].isin(area_ids) &
    df["Dropoff Community Area"].isin(area_ids)
].copy()

retained_count = len(filtered)

od = filtered.groupby(["Pickup Community Area", "Dropoff Community Area"]).size().reset_index(name="count")

matrix = pd.DataFrame(0, index=area_ids, columns=area_ids)
for _, r in od.iterrows():
    matrix.loc[r["Pickup Community Area"], r["Dropoff Community Area"]] = int(r["count"])

with out_od.open("w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["origin_area"] + area_ids)
    for o in area_ids:
        w.writerow([o] + [int(matrix.loc[o, d]) for d in area_ids])

area_rows = []
for a in area_ids:
    productions = int(matrix.loc[a].sum())
    attractions = int(matrix[a].sum())
    internal = int(matrix.loc[a, a])
    touching = productions + attractions - internal
    area_rows.append({
        "area_id": a,
        "area_name": name_map.get(a, ""),
        "productions": productions,
        "attractions": attractions,
        "internal_trips": internal,
        "total_trips_touching": touching,
    })

pd.DataFrame(area_rows).to_csv(out_area, index=False)

filtered["dt"] = pd.to_datetime(
    filtered["Trip Start Timestamp"],
    format="%m/%d/%Y %I:%M:%S %p",
    errors="coerce",
)
filtered = filtered.dropna(subset=["dt"]).copy()
filtered["hour"] = filtered["dt"].dt.hour

hour_total = filtered.groupby("hour").size().reindex(range(24), fill_value=0)

prod_hour = filtered.groupby(["hour", "Pickup Community Area"]).size().unstack(fill_value=0).reindex(index=range(24), columns=area_ids, fill_value=0)
attr_hour = filtered.groupby(["hour", "Dropoff Community Area"]).size().unstack(fill_value=0).reindex(index=range(24), columns=area_ids, fill_value=0)

time_rows = []
for h in range(24):
    row = {"hour": h, "total_trips": int(hour_total.loc[h])}
    for a in area_ids:
        row[f"prod_{a}"] = int(prod_hour.loc[h, a])
    for a in area_ids:
        row[f"attr_{a}"] = int(attr_hour.loc[h, a])
    time_rows.append(row)

pd.DataFrame(time_rows).to_csv(out_time, index=False)

top_pairs = od.sort_values("count", ascending=False).head(15)

morning_peak_hour = int(hour_total.loc[6:10].idxmax())
midday_peak_hour = int(hour_total.loc[11:15].idxmax())
evening_peak_hour = int(hour_total.loc[16:20].idxmax())

net = ET.parse(net_file).getroot()
loc = net.find("location")
orig_boundary = loc.get("origBoundary") if loc is not None else ""

lines = []
lines.append("Benchmark5 demand summary")
lines.append("taxi_file: " + str(taxi_file))
lines.append("boundary_file: " + str(boundary_file))
lines.append("network_file: " + str(net_file))
lines.append("network_orig_boundary: " + str(orig_boundary))
lines.append("")
lines.append("selected_official_area_ids: " + ", ".join(area_ids))
lines.append("selected_official_area_names:")
for a in area_ids:
    lines.append(f"- {a} | {name_map.get(a,'')}")
lines.append("")
lines.append("retained_trip_count: " + str(retained_count))
lines.append("od_cell_count_nonzero: " + str(int((matrix.values > 0).sum())))
lines.append("")
lines.append("dominant_od_pairs_top15:")
for _, r in top_pairs.iterrows():
    lines.append(f"- {r['Pickup Community Area']}->{r['Dropoff Community Area']}: {int(r['count'])}")
lines.append("")
lines.append("area_production_attraction_summary:")
for r in area_rows:
    lines.append(
        f"- {r['area_id']} {r['area_name']} | productions={r['productions']} attractions={r['attractions']} internal={r['internal_trips']} touching={r['total_trips_touching']}"
    )
lines.append("")
lines.append("hourly_peak_markers_from_trip_start_timestamp:")
lines.append(f"- morning_peak_hour_06_to_10: {morning_peak_hour} (trips={int(hour_total.loc[morning_peak_hour])})")
lines.append(f"- midday_peak_hour_11_to_15: {midday_peak_hour} (trips={int(hour_total.loc[midday_peak_hour])})")
lines.append(f"- evening_peak_hour_16_to_20: {evening_peak_hour} (trips={int(hour_total.loc[evening_peak_hour])})")
lines.append("")
lines.append("hourly_totals:")
for h in range(24):
    lines.append(f"- {h:02d}:00 => {int(hour_total.loc[h])}")

out_summary.write_text("\n".join(lines), encoding="utf-8")

print("done")
print("retained", retained_count)
print("morning", morning_peak_hour, int(hour_total.loc[morning_peak_hour]))
print("midday", midday_peak_hour, int(hour_total.loc[midday_peak_hour]))
print("evening", evening_peak_hour, int(hour_total.loc[evening_peak_hour]))
