import os
import csv
import math
import argparse


project_dir = r"E:\project_sakif_chicago"
od_file = os.path.join(project_dir, "output", "compact4_od_matrix.csv")
time_file = os.path.join(project_dir, "output", "compact4_time_profile.csv")
out_file = os.path.join(project_dir, "data", "compact4_request_stream.csv")


def fnum(v):
    try:
        return float(v)
    except Exception:
        return 0.0


def allocate(total_int, weights, keys):
    if total_int <= 0:
        return {k: 0 for k in keys}
    raw = {k: total_int * max(0.0, weights.get(k, 0.0)) for k in keys}
    base = {k: int(math.floor(raw[k])) for k in keys}
    remain = total_int - sum(base.values())
    if remain > 0:
        order = sorted(keys, key=lambda k: (raw[k] - base[k], raw[k]), reverse=True)
        i = 0
        while remain > 0 and order:
            k = order[i % len(order)]
            base[k] += 1
            remain -= 1
            i += 1
    return base


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scale", type=float, default=0.10)
    parser.add_argument("--output", default=out_file)
    args = parser.parse_args()

    zones = []
    od = {}
    od_total = 0.0
    with open(od_file, "r", encoding="utf-8-sig", newline="") as f:
        r = csv.DictReader(f)
        zones = [x for x in r.fieldnames if x != "origin_zone"]
        for row in r:
            o = row["origin_zone"].strip()
            for d in zones:
                v = fnum(row.get(d, 0))
                od[(o, d)] = v
                od_total += v
    od_weights = {}
    if od_total > 0:
        for k, v in od.items():
            od_weights[k] = v / od_total
    else:
        for o in zones:
            for d in zones:
                od_weights[(o, d)] = 0.0

    hours = []
    hour_total = {}
    with open(time_file, "r", encoding="utf-8-sig", newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            h = int(float(row["hour"]))
            t = fnum(row.get("total_trips", 0))
            hours.append(h)
            hour_total[h] = t
    hsum = sum(hour_total[h] for h in hours)
    hour_weights = {}
    if hsum > 0:
        for h in hours:
            hour_weights[h] = hour_total[h] / hsum
    else:
        for h in hours:
            hour_weights[h] = 0.0

    target_total = int(round(od_total * args.scale))
    hour_alloc = allocate(target_total, hour_weights, hours)
    od_keys = [(o, d) for o in zones for d in zones]

    rows = []
    rid = 1
    for h in sorted(hours):
        n = hour_alloc[h]
        if n <= 0:
            continue
        od_alloc = allocate(n, od_weights, od_keys)
        counter = 0
        for (o, d), c in od_alloc.items():
            for _ in range(c):
                t = h * 3600 + int(((counter + 0.5) / n) * 3600)
                rows.append({
                    "request_id": f"r{rid:07d}",
                    "request_time": t,
                    "origin_zone": o,
                    "destination_zone": d,
                })
                rid += 1
                counter += 1

    rows.sort(key=lambda x: (x["request_time"], x["request_id"]))

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["request_id", "request_time", "origin_zone", "destination_zone"])
        w.writeheader()
        for row in rows:
            w.writerow(row)

    print("request_stream_file=" + args.output)
    print("scale=" + str(args.scale))
    print("total_requests=" + str(len(rows)))
    print("zones=" + ",".join(zones))


if __name__ == "__main__":
    main()
