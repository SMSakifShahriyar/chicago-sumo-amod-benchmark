import os
import csv
import json


project_dir = r"E:\project_sakif_chicago"
od_in = os.path.join(project_dir, "output", "benchmark5_od_matrix.csv")
crosswalk_in = os.path.join(project_dir, "output", "official5_to_compact4_crosswalk.csv")
time_in = os.path.join(project_dir, "output", "benchmark5_time_profile.csv")

od_csv_out = os.path.join(project_dir, "output", "compact4_od_matrix.csv")
od_json_out = os.path.join(project_dir, "output", "compact4_od_matrix.json")
od_txt_out = os.path.join(project_dir, "output", "compact4_od_summary.txt")
alloc_out = os.path.join(project_dir, "output", "official5_to_compact4_allocation.csv")
time_out = os.path.join(project_dir, "output", "compact4_time_profile.csv")

zones = ["cz1", "cz2", "cz3", "cz4"]
areas = [8, 24, 28, 32, 33]


def fnum(x):
    try:
        return float(x)
    except Exception:
        return 0.0


crosswalk = {}
with open(crosswalk_in, "r", encoding="utf-8-sig", newline="") as f:
    r = csv.DictReader(f)
    for row in r:
        aid = int(row["official_area_id"])
        crosswalk[aid] = {
            "cz1": fnum(row["share_cz1"]),
            "cz2": fnum(row["share_cz2"]),
            "cz3": fnum(row["share_cz3"]),
            "cz4": fnum(row["share_cz4"]),
        }

od5 = {}
with open(od_in, "r", encoding="utf-8-sig", newline="") as f:
    r = csv.DictReader(f)
    for row in r:
        o = int(row["origin_area"])
        for d in areas:
            od5[(o, d)] = fnum(row[str(d)])

od4 = {(zo, zd): 0.0 for zo in zones for zd in zones}
alloc_rows = []

for o in areas:
    for d in areas:
        flow = od5.get((o, d), 0.0)
        if flow == 0:
            continue
        for zo in zones:
            so = crosswalk[o][zo]
            if so == 0:
                continue
            for zd in zones:
                sd = crosswalk[d][zd]
                if sd == 0:
                    continue
                a = flow * so * sd
                if a == 0:
                    continue
                od4[(zo, zd)] += a
                alloc_rows.append({
                    "official_origin": o,
                    "official_destination": d,
                    "flow_official": round(flow, 6),
                    "compact_origin": zo,
                    "compact_destination": zd,
                    "origin_share": round(so, 6),
                    "destination_share": round(sd, 6),
                    "allocated_flow": round(a, 6),
                })

with open(alloc_out, "w", encoding="utf-8", newline="") as f:
    fields = [
        "official_origin", "official_destination", "flow_official",
        "compact_origin", "compact_destination", "origin_share",
        "destination_share", "allocated_flow"
    ]
    w = csv.DictWriter(f, fieldnames=fields)
    w.writeheader()
    for row in alloc_rows:
        w.writerow(row)

with open(od_csv_out, "w", encoding="utf-8", newline="") as f:
    fields = ["origin_zone"] + zones
    w = csv.DictWriter(f, fieldnames=fields)
    w.writeheader()
    for zo in zones:
        row = {"origin_zone": zo}
        for zd in zones:
            row[zd] = round(od4[(zo, zd)], 6)
        w.writerow(row)

total_before = sum(od5.values())
total_after = sum(od4.values())

productions = {z: 0.0 for z in zones}
attractions = {z: 0.0 for z in zones}
internal = {z: od4[(z, z)] for z in zones}
for zo in zones:
    for zd in zones:
        productions[zo] += od4[(zo, zd)]
        attractions[zd] += od4[(zo, zd)]

pairs = []
for zo in zones:
    for zd in zones:
        pairs.append((zo, zd, od4[(zo, zd)]))
pairs.sort(key=lambda x: x[2], reverse=True)

od_json = {
    "zones": zones,
    "matrix": {zo: {zd: round(od4[(zo, zd)], 6) for zd in zones} for zo in zones},
    "total_before": round(total_before, 6),
    "total_after": round(total_after, 6),
    "difference": round(total_after - total_before, 12),
    "productions": {z: round(productions[z], 6) for z in zones},
    "attractions": {z: round(attractions[z], 6) for z in zones},
    "internal": {z: round(internal[z], 6) for z in zones},
    "dominant_pairs_top10": [
        {"origin": zo, "destination": zd, "flow": round(v, 6)} for zo, zd, v in pairs[:10]
    ]
}

with open(od_json_out, "w", encoding="utf-8") as f:
    json.dump(od_json, f, indent=2)

summary_lines = []
summary_lines.append("compact4 od summary")
summary_lines.append("")
summary_lines.append(f"total_before={round(total_before, 6)}")
summary_lines.append(f"total_after={round(total_after, 6)}")
summary_lines.append(f"difference={round(total_after-total_before, 12)}")
summary_lines.append("")
summary_lines.append("productions")
for z in zones:
    summary_lines.append(f"{z}={round(productions[z], 6)}")
summary_lines.append("")
summary_lines.append("attractions")
for z in zones:
    summary_lines.append(f"{z}={round(attractions[z], 6)}")
summary_lines.append("")
summary_lines.append("internal")
for z in zones:
    summary_lines.append(f"{z}={round(internal[z], 6)}")
summary_lines.append("")
summary_lines.append("top10_compact_pairs")
for zo, zd, v in pairs[:10]:
    summary_lines.append(f"{zo}->{zd}={round(v, 6)}")

with open(od_txt_out, "w", encoding="utf-8") as f:
    f.write("\n".join(summary_lines) + "\n")

time_rows = []
if os.path.exists(time_in):
    with open(time_in, "r", encoding="utf-8-sig", newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            out = {"hour": row["hour"], "total_trips": fnum(row.get("total_trips", 0))}
            for z in zones:
                out["prod_" + z] = 0.0
                out["attr_" + z] = 0.0
            for a in areas:
                pval = fnum(row.get(f"prod_{a}", 0))
                aval = fnum(row.get(f"attr_{a}", 0))
                shares = crosswalk[a]
                for z in zones:
                    out["prod_" + z] += pval * shares[z]
                    out["attr_" + z] += aval * shares[z]
            for z in zones:
                out["prod_" + z] = round(out["prod_" + z], 6)
                out["attr_" + z] = round(out["attr_" + z], 6)
            time_rows.append(out)

if time_rows:
    with open(time_out, "w", encoding="utf-8", newline="") as f:
        fields = ["hour", "total_trips"] + [f"prod_{z}" for z in zones] + [f"attr_{z}" for z in zones]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for row in time_rows:
            w.writerow(row)

print("od csv:", od_csv_out)
print("od json:", od_json_out)
print("od summary:", od_txt_out)
print("allocation csv:", alloc_out)
if time_rows:
    print("time profile:", time_out)
