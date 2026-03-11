import os
import csv
import math
import argparse
import xml.etree.ElementTree as ET
import numpy as np


script_dir = os.path.dirname(os.path.abspath(__file__))
project_dir = os.path.abspath(os.path.join(script_dir, ".."))
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


def scale_tag(scale):
    return f"0p{int(round(scale * 1000)):03d}"


def load_service_edges(zones):
    edge_map = {}
    for z in zones:
        p = os.path.join(project_dir, "data", f"compact4_service_edges_{z}.txt")
        edges = []
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                for line in f:
                    e = line.strip()
                    if e:
                        edges.append(e)
        edge_map[z] = edges

    taz_file = os.path.join(project_dir, "data", "compact4_zones.taz.xml")
    if os.path.exists(taz_file):
        root = ET.parse(taz_file).getroot()
        for taz in root.findall("taz"):
            zid = (taz.get("id") or "").strip()
            if zid in edge_map and edge_map[zid]:
                continue
            raw = (taz.get("edges") or "").strip().split()
            edge_map[zid] = [e for e in raw if e]
    return edge_map


def pick_edge(rng, edge_map, zone):
    edges = edge_map.get(zone, [])
    if not edges:
        return ""
    idx = int(rng.integers(0, len(edges)))
    return edges[idx]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scale", type=float, default=0.10)
    parser.add_argument("--seed", type=int, default=101)
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    rng = np.random.default_rng(args.seed)

    if args.output.strip():
        out_path = args.output
    else:
        out_path = os.path.join(
            project_dir,
            "data",
            f"compact4_request_stream_s{scale_tag(args.scale)}_seed{args.seed}.csv",
        )

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
    service_edges = load_service_edges(zones)

    rows = []
    rid = 1
    for h in sorted(hours):
        n = hour_alloc[h]
        if n <= 0:
            continue
        od_alloc = allocate(n, od_weights, od_keys)
        for (o, d), c in od_alloc.items():
            if c <= 0:
                continue
            offsets = rng.integers(0, 3600, size=c)
            for i in range(c):
                t = h * 3600 + int(offsets[i])
                rows.append({
                    "request_id": f"r{rid:07d}",
                    "request_time": t,
                    "origin_zone": o,
                    "destination_zone": d,
                    "origin_edge": pick_edge(rng, service_edges, o),
                    "destination_edge": pick_edge(rng, service_edges, d),
                })
                rid += 1

    rows.sort(key=lambda x: (x["request_time"], x["request_id"]))

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "request_id",
                "request_time",
                "origin_zone",
                "destination_zone",
                "origin_edge",
                "destination_edge",
            ],
        )
        w.writeheader()
        for row in rows:
            w.writerow(row)

    print("request_stream_file=" + out_path)
    print("scale=" + str(args.scale))
    print("seed=" + str(args.seed))
    print("total_requests=" + str(len(rows)))
    print("zones=" + ",".join(zones))


if __name__ == "__main__":
    main()
