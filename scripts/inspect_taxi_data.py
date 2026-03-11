from pathlib import Path
import pandas as pd

root = Path(r"E:\project_sakif_chicago")
file_path = root / "Taxi_Trips_(2024-)_20260310.csv"
out_path = root / "output" / "taxi_data_profile.txt"

if not file_path.exists():
    raise SystemExit("taxi file not found")

important = [
    "Trip Start Timestamp",
    "Trip End Timestamp",
    "Pickup Census Tract",
    "Dropoff Census Tract",
    "Pickup Community Area",
    "Dropoff Community Area",
    "Trip Seconds",
    "Trip Miles",
    "Fare",
    "Trip Total",
]

header = pd.read_csv(file_path, nrows=0)
columns = list(header.columns)

sample_df = pd.read_csv(file_path, nrows=5000)
dtypes = {c: str(sample_df[c].dtype) for c in columns}

row_count = 0
nn_pickup_ca = 0
nn_dropoff_ca = 0
nn_both_ca = 0
nn_pickup_ct = 0
nn_dropoff_ct = 0
nn_both_ct = 0

min_dt = None
max_dt = None
by_month = {}
by_day = {}
by_hour = {}

samples = {c: [] for c in important if c in columns}

usecols = columns
for chunk in pd.read_csv(file_path, chunksize=200000, dtype=str, usecols=usecols):
    row_count += len(chunk)

    for c in important:
        if c in chunk.columns and len(samples[c]) < 5:
            vals = chunk[c].dropna().astype(str)
            vals = [v.strip() for v in vals if v.strip()]
            for v in vals:
                if v not in samples[c]:
                    samples[c].append(v)
                if len(samples[c]) >= 5:
                    break

    if "Pickup Community Area" in chunk.columns:
        p = chunk["Pickup Community Area"].fillna("").astype(str).str.strip() != ""
    else:
        p = pd.Series([False] * len(chunk))

    if "Dropoff Community Area" in chunk.columns:
        d = chunk["Dropoff Community Area"].fillna("").astype(str).str.strip() != ""
    else:
        d = pd.Series([False] * len(chunk))

    nn_pickup_ca += int(p.sum())
    nn_dropoff_ca += int(d.sum())
    nn_both_ca += int((p & d).sum())

    if "Pickup Census Tract" in chunk.columns:
        pct = chunk["Pickup Census Tract"].fillna("").astype(str).str.strip() != ""
    else:
        pct = pd.Series([False] * len(chunk))

    if "Dropoff Census Tract" in chunk.columns:
        dct = chunk["Dropoff Census Tract"].fillna("").astype(str).str.strip() != ""
    else:
        dct = pd.Series([False] * len(chunk))

    nn_pickup_ct += int(pct.sum())
    nn_dropoff_ct += int(dct.sum())
    nn_both_ct += int((pct & dct).sum())

    if "Trip Start Timestamp" in chunk.columns:
        dt = pd.to_datetime(chunk["Trip Start Timestamp"], errors="coerce")
        valid = dt.dropna()
        if not valid.empty:
            cur_min = valid.min()
            cur_max = valid.max()
            min_dt = cur_min if min_dt is None else min(min_dt, cur_min)
            max_dt = cur_max if max_dt is None else max(max_dt, cur_max)

            months = valid.dt.to_period("M").astype(str).value_counts()
            for k, v in months.items():
                by_month[k] = by_month.get(k, 0) + int(v)

            days = valid.dt.date.astype(str).value_counts()
            for k, v in days.items():
                by_day[k] = by_day.get(k, 0) + int(v)

            hours = valid.dt.hour.value_counts()
            for k, v in hours.items():
                kk = int(k)
                by_hour[kk] = by_hour.get(kk, 0) + int(v)

lines = []
lines.append("Taxi data profile")
lines.append("file: " + str(file_path))
lines.append("row_count: " + str(row_count))
lines.append("")
lines.append("columns:")
for c in columns:
    lines.append(f"- {c} | dtype(sample)={dtypes.get(c,'unknown')}")
lines.append("")
lines.append("important columns present:")
for c in important:
    lines.append(f"- {c}: {'yes' if c in columns else 'no'}")
lines.append("")
lines.append("important column sample values:")
for c in important:
    if c in samples:
        lines.append(f"- {c}: {samples[c]}")
lines.append("")
lines.append("missingness summary:")
lines.append(f"- non_null pickup_community_area: {nn_pickup_ca}")
lines.append(f"- non_null dropoff_community_area: {nn_dropoff_ca}")
lines.append(f"- non_null both community_area: {nn_both_ca}")
lines.append(f"- non_null pickup_census_tract: {nn_pickup_ct}")
lines.append(f"- non_null dropoff_census_tract: {nn_dropoff_ct}")
lines.append(f"- non_null both census_tract: {nn_both_ct}")
lines.append("")
lines.append("date range:")
lines.append(f"- min trip_start_timestamp: {min_dt}")
lines.append(f"- max trip_start_timestamp: {max_dt}")
lines.append("")
lines.append("counts by month:")
for k in sorted(by_month):
    lines.append(f"- {k}: {by_month[k]}")
lines.append("")
lines.append("counts by day (top 20):")
for k, v in sorted(by_day.items(), key=lambda x: x[1], reverse=True)[:20]:
    lines.append(f"- {k}: {v}")
lines.append("")
lines.append("counts by hour:")
for h in range(24):
    lines.append(f"- {h:02d}:00: {by_hour.get(h,0)}")

out_path.write_text("\n".join(lines), encoding="utf-8")
print("done")
print("rows", row_count)
print("date_min", min_dt)
print("date_max", max_dt)
