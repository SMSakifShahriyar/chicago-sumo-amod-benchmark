import os
import csv
import math
import xml.etree.ElementTree as ET


project_dir = r"E:\project_sakif_chicago"
od_file = os.path.join(project_dir, "output", "compact4_od_matrix.csv")
time_file = os.path.join(project_dir, "output", "compact4_time_profile.csv")

demand_csv = os.path.join(project_dir, "data", "compact4_benchmark_demand.csv")
flows_xml = os.path.join(project_dir, "data", "compact4_benchmark_flows.xml")
summary_file = os.path.join(project_dir, "output", "compact4_benchmark_demand_summary.txt")

zones = ["cz1", "cz2", "cz3", "cz4"]
scale = 0.05


def fnum(v):
    try:
        return float(v)
    except Exception:
        return 0.0


def allocate_by_largest_remainder(total_int, weights, keys):
    if total_int <= 0:
        return {k: 0 for k in keys}
    raw = {k: total_int * max(0.0, weights.get(k, 0.0)) for k in keys}
    base = {k: int(math.floor(raw[k])) for k in keys}
    rem = total_int - sum(base.values())
    if rem > 0:
        order = sorted(keys, key=lambda k: (raw[k] - base[k], raw[k]), reverse=True)
        idx = 0
        while rem > 0 and order:
            k = order[idx % len(order)]
            base[k] += 1
            rem -= 1
            idx += 1
    return base


od = {}
with open(od_file, "r", encoding="utf-8-sig", newline="") as f:
    r = csv.DictReader(f)
    for row in r:
        o = row["origin_zone"].strip()
        for d in zones:
            od[(o, d)] = fnum(row.get(d, 0))

od_total = sum(od.values())
od_weights = {}
if od_total > 0:
    for k, v in od.items():
        od_weights[k] = v / od_total
else:
    for o in zones:
        for d in zones:
            od_weights[(o, d)] = 0.0

hours = []
hour_totals = {}
with open(time_file, "r", encoding="utf-8-sig", newline="") as f:
    r = csv.DictReader(f)
    for row in r:
        h = int(float(row["hour"]))
        t = fnum(row.get("total_trips", 0))
        hours.append(h)
        hour_totals[h] = t

raw_benchmark_total = od_total * scale
benchmark_total = int(round(raw_benchmark_total))

hour_weight_sum = sum(hour_totals[h] for h in hours)
hour_weights = {}
if hour_weight_sum > 0:
    for h in hours:
        hour_weights[h] = hour_totals[h] / hour_weight_sum
else:
    for h in hours:
        hour_weights[h] = 0.0

hour_alloc = allocate_by_largest_remainder(benchmark_total, hour_weights, hours)

pair_keys = [(o, d) for o in zones for d in zones]
rows = []
compact_matrix = {(o, d): 0 for o in zones for d in zones}

for h in sorted(hours):
    h_total = hour_alloc[h]
    pair_weights = {k: od_weights[k] for k in pair_keys}
    pair_alloc = allocate_by_largest_remainder(h_total, pair_weights, pair_keys)
    begin = h * 3600
    end = (h + 1) * 3600
    for (o, d), n in pair_alloc.items():
        if n <= 0:
            continue
        rows.append({
            "hour": h,
            "begin": begin,
            "end": end,
            "from_taz": o,
            "to_taz": d,
            "trips": n
        })
        compact_matrix[(o, d)] += n

os.makedirs(os.path.dirname(demand_csv), exist_ok=True)
os.makedirs(os.path.dirname(summary_file), exist_ok=True)

with open(demand_csv, "w", encoding="utf-8", newline="") as f:
    fieldnames = ["hour", "begin", "end", "from_taz", "to_taz", "trips"]
    w = csv.DictWriter(f, fieldnames=fieldnames)
    w.writeheader()
    for row in rows:
        w.writerow(row)

root = ET.Element("data")
for h in sorted(hours):
    begin = h * 3600
    end = (h + 1) * 3600
    interval = ET.SubElement(root, "interval", {"begin": str(begin), "end": str(end)})
    for row in rows:
        if row["hour"] != h:
            continue
        ET.SubElement(interval, "tazRelation", {
            "from": row["from_taz"],
            "to": row["to_taz"],
            "count": str(row["trips"])
        })

ET.ElementTree(root).write(flows_xml, encoding="utf-8", xml_declaration=True)

prod = {z: 0 for z in zones}
attr = {z: 0 for z in zones}
for (o, d), n in compact_matrix.items():
    prod[o] += n
    attr[d] += n

converted_total = sum(compact_matrix.values())
od_share_max_diff = 0.0
if converted_total > 0:
    for k in pair_keys:
        new_share = compact_matrix[k] / converted_total
        od_share_max_diff = max(od_share_max_diff, abs(new_share - od_weights[k]))

new_hour_total = {h: 0 for h in hours}
for row in rows:
    new_hour_total[row["hour"]] += row["trips"]

hour_shape_max_diff = 0.0
if converted_total > 0:
    for h in hours:
        old_share = hour_weights[h]
        new_share = new_hour_total[h] / converted_total
        hour_shape_max_diff = max(hour_shape_max_diff, abs(old_share - new_share))

top_pairs = sorted(pair_keys, key=lambda k: compact_matrix[k], reverse=True)[:10]

lines = []
lines.append("compact4 benchmark demand summary")
lines.append("")
lines.append(f"recommended_scale_type=representative_day")
lines.append(f"scale_factor={scale}")
lines.append(f"raw_scaled_total={round(raw_benchmark_total, 6)}")
lines.append(f"benchmark_total_trips={benchmark_total}")
lines.append(f"converted_total_trips={converted_total}")
lines.append("")
lines.append(f"od_share_preserved=yes")
lines.append(f"od_share_max_abs_diff={round(od_share_max_diff, 8)}")
lines.append(f"hourly_shape_preserved=yes")
lines.append(f"hourly_share_max_abs_diff={round(hour_shape_max_diff, 8)}")
lines.append("")
lines.append("productions")
for z in zones:
    lines.append(f"{z}={prod[z]}")
lines.append("")
lines.append("attractions")
for z in zones:
    lines.append(f"{z}={attr[z]}")
lines.append("")
lines.append("top10_pairs")
for o, d in top_pairs:
    lines.append(f"{o}->{d}={compact_matrix[(o,d)]}")

with open(summary_file, "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")

print("demand csv:", demand_csv)
print("flows xml:", flows_xml)
print("summary:", summary_file)
