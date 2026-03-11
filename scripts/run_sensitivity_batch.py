import os
import csv
import math
import subprocess
import xml.etree.ElementTree as ET


project_dir = r"E:\project_sakif_chicago"
sumo_bin = r"C:\Program Files (x86)\Eclipse\Sumo\bin"
od2trips_exe = os.path.join(sumo_bin, "od2trips.exe")
duarouter_exe = os.path.join(sumo_bin, "duarouter.exe")
sumo_exe = os.path.join(sumo_bin, "sumo.exe")

network_file = os.path.join(project_dir, "net", "map_reduced_clean_auto_v2.net.xml")
taz_file = os.path.join(project_dir, "data", "compact4_zones.taz.xml")
od_file = os.path.join(project_dir, "output", "compact4_od_matrix.csv")
time_file = os.path.join(project_dir, "output", "compact4_time_profile.csv")
baseline_summary_file = os.path.join(project_dir, "output", "baseline_benchmark_summary.txt")

comparison_file = os.path.join(project_dir, "output", "sensitivity_comparison.txt")

zones = ["cz1", "cz2", "cz3", "cz4"]
scales = [("7p5", 0.075), ("10", 0.10)]


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


def read_od():
    od = {}
    with open(od_file, "r", encoding="utf-8-sig", newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            o = row["origin_zone"].strip()
            for d in zones:
                od[(o, d)] = fnum(row.get(d, 0))
    total = sum(od.values())
    weights = {}
    if total > 0:
        for k, v in od.items():
            weights[k] = v / total
    else:
        for o in zones:
            for d in zones:
                weights[(o, d)] = 0.0
    return od, total, weights


def read_hour_weights():
    hours = []
    totals = {}
    with open(time_file, "r", encoding="utf-8-sig", newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            h = int(float(row["hour"]))
            t = fnum(row.get("total_trips", 0))
            hours.append(h)
            totals[h] = t
    s = sum(totals[h] for h in hours)
    w = {}
    if s > 0:
        for h in hours:
            w[h] = totals[h] / s
    else:
        for h in hours:
            w[h] = 0.0
    return hours, w


def write_demand(scale_tag, scale_value, od_weights, od_total, hours, hour_weights):
    demand_csv = os.path.join(project_dir, "data", f"compact4_benchmark_demand_{scale_tag}.csv")
    flows_xml = os.path.join(project_dir, "data", f"compact4_benchmark_flows_{scale_tag}.xml")
    raw_total = od_total * scale_value
    total_int = int(round(raw_total))
    hour_alloc = allocate(total_int, hour_weights, hours)
    pair_keys = [(o, d) for o in zones for d in zones]
    rows = []
    for h in sorted(hours):
        n = hour_alloc[h]
        pair_alloc = allocate(n, od_weights, pair_keys)
        begin = h * 3600
        end = (h + 1) * 3600
        for (o, d), c in pair_alloc.items():
            if c <= 0:
                continue
            rows.append({
                "hour": h,
                "begin": begin,
                "end": end,
                "from_taz": o,
                "to_taz": d,
                "trips": c
            })
    with open(demand_csv, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["hour", "begin", "end", "from_taz", "to_taz", "trips"])
        w.writeheader()
        for row in rows:
            w.writerow(row)
    root = ET.Element("data")
    for h in sorted(hours):
        interval = ET.SubElement(root, "interval", {"begin": str(h * 3600), "end": str((h + 1) * 3600)})
        for row in rows:
            if row["hour"] != h:
                continue
            ET.SubElement(interval, "tazRelation", {
                "from": row["from_taz"],
                "to": row["to_taz"],
                "count": str(row["trips"])
            })
    ET.ElementTree(root).write(flows_xml, encoding="utf-8", xml_declaration=True)
    return demand_csv, flows_xml, total_int


def run_cmd(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


def build_routes(scale_tag, flows_xml):
    trips_file = os.path.join(project_dir, "data", f"compact4_benchmark_{scale_tag}.trips.xml")
    routes_file = os.path.join(project_dir, "routes", f"compact4_benchmark_{scale_tag}.rou.xml")
    route_log = os.path.join(project_dir, "output", f"compact4_benchmark_route_build_{scale_tag}.log")
    cmd1 = [od2trips_exe, "-n", taz_file, "-z", flows_xml, "-o", trips_file, "--spread.uniform", "--seed", "42"]
    rc1, out1, err1 = run_cmd(cmd1)
    rc2, out2, err2 = 999, "", ""
    if rc1 == 0:
        cmd2 = [duarouter_exe, "-n", network_file, "-r", trips_file, "-a", taz_file, "--with-taz", "--ignore-errors", "-o", routes_file, "--seed", "42"]
        rc2, out2, err2 = run_cmd(cmd2)
    else:
        cmd2 = [duarouter_exe, "-n", network_file, "-r", trips_file, "-a", taz_file, "--with-taz", "--ignore-errors", "-o", routes_file, "--seed", "42"]
    lines = []
    lines.append("route build log")
    lines.append("")
    lines.append("od2trips_command")
    lines.append(" ".join(cmd1))
    lines.append(f"od2trips_rc={rc1}")
    lines.append("od2trips_stdout")
    lines.append(out1.strip())
    lines.append("od2trips_stderr")
    lines.append(err1.strip())
    lines.append("")
    lines.append("duarouter_command")
    lines.append(" ".join(cmd2))
    lines.append(f"duarouter_rc={rc2}")
    lines.append("duarouter_stdout")
    lines.append(out2.strip())
    lines.append("duarouter_stderr")
    lines.append(err2.strip())
    with open(route_log, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return trips_file, routes_file, route_log, rc1, rc2


def write_cfg(scale_tag, routes_file):
    cfg_file = os.path.join(project_dir, "cfg", f"baseline_benchmark_{scale_tag}.sumocfg")
    tripinfo = os.path.join(project_dir, "output", f"baseline_tripinfo_{scale_tag}.xml")
    summary = os.path.join(project_dir, "output", f"baseline_summary_{scale_tag}.xml")
    stats = os.path.join(project_dir, "output", f"baseline_statistics_{scale_tag}.xml")
    edge = os.path.join(project_dir, "output", f"baseline_queue_or_edge_stats_{scale_tag}.xml")
    run_log = os.path.join(project_dir, "output", f"baseline_run_{scale_tag}.log")
    root = ET.Element("configuration")
    inp = ET.SubElement(root, "input")
    ET.SubElement(inp, "net-file", {"value": network_file})
    ET.SubElement(inp, "route-files", {"value": routes_file})
    t = ET.SubElement(root, "time")
    ET.SubElement(t, "begin", {"value": "0"})
    ET.SubElement(t, "end", {"value": "86400"})
    out = ET.SubElement(root, "output")
    ET.SubElement(out, "tripinfo-output", {"value": tripinfo})
    ET.SubElement(out, "summary-output", {"value": summary})
    ET.SubElement(out, "statistic-output", {"value": stats})
    ET.SubElement(out, "edgedata-output", {"value": edge})
    rep = ET.SubElement(root, "report")
    ET.SubElement(rep, "verbose", {"value": "true"})
    ET.SubElement(rep, "duration-log.statistics", {"value": "true"})
    ET.SubElement(rep, "no-step-log", {"value": "true"})
    ET.ElementTree(root).write(cfg_file, encoding="utf-8", xml_declaration=True)
    return cfg_file, tripinfo, summary, stats, edge, run_log


def run_sim(cfg_file, run_log):
    cmd = [sumo_exe, "-c", cfg_file]
    p = subprocess.run(cmd, capture_output=True, text=True)
    with open(run_log, "w", encoding="utf-8") as f:
        f.write((p.stdout or "") + "\n" + (p.stderr or ""))
    return p.returncode, cmd


def parse_metrics(scale_tag, tripinfo_file, summary_file, edge_file, run_log, route_log, rc_sumo):
    inserted = 0
    arrived = 0
    teleports = 0
    collisions = 0
    if os.path.exists(summary_file):
        root = ET.parse(summary_file).getroot()
        for step in root.findall("step"):
            inserted = max(inserted, int(fnum(step.get("inserted", "0"))))
            arrived = max(arrived, int(fnum(step.get("ended", "0"))))
            teleports = max(teleports, int(fnum(step.get("teleports", "0"))))
            collisions = max(collisions, int(fnum(step.get("collisions", "0"))))
    unfinished = max(0, inserted - arrived)
    count = 0
    dur = 0.0
    wait = 0.0
    loss = 0.0
    if os.path.exists(tripinfo_file):
        root = ET.parse(tripinfo_file).getroot()
        for t in root.findall("tripinfo"):
            count += 1
            dur += fnum(t.get("duration", "0"))
            wait += fnum(t.get("waitingTime", "0"))
            loss += fnum(t.get("timeLoss", "0"))
    avg_dur = dur / count if count > 0 else 0.0
    avg_wait = wait / count if count > 0 else 0.0
    avg_loss = loss / count if count > 0 else 0.0
    reasons = {}
    if os.path.exists(run_log):
        with open(run_log, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                s = line.lower()
                if "teleporting vehicle" in s:
                    r = "unknown"
                    if "wrong lane" in s:
                        r = "wrong lane"
                    elif "jam" in s:
                        r = "jam"
                    reasons[r] = reasons.get(r, 0) + 1
    bottlenecks = []
    if os.path.exists(edge_file):
        root = ET.parse(edge_file).getroot()
        for interval in root.findall("interval"):
            for edge in interval.findall("edge"):
                eid = edge.get("id", "")
                if not eid:
                    continue
                wt = fnum(edge.get("waitingTime", "0"))
                sp = fnum(edge.get("speed", "0"))
                smp = fnum(edge.get("sampledSeconds", "0"))
                if smp <= 0:
                    continue
                score = wt + max(0.0, 15.0 - sp) * 4.0
                bottlenecks.append((score, eid, wt, sp))
    bottlenecks.sort(key=lambda x: x[0], reverse=True)
    top_edges = [x[1] for x in bottlenecks[:5]]
    route_warnings = 0
    if os.path.exists(route_log):
        with open(route_log, "r", encoding="utf-8", errors="ignore") as f:
            txt = f.read().lower()
            route_warnings = txt.count("warning:") + txt.count("error:")
    return {
        "scale_tag": scale_tag,
        "sumo_rc": rc_sumo,
        "inserted": inserted,
        "arrived": arrived,
        "unfinished": unfinished,
        "teleports": teleports,
        "teleport_reasons": reasons,
        "collisions": collisions,
        "avg_duration": avg_dur,
        "avg_waiting": avg_wait,
        "avg_time_loss": avg_loss,
        "top_bottlenecks": top_edges,
        "route_warning_or_error_mentions": route_warnings
    }


def parse_baseline():
    data = {}
    if not os.path.exists(baseline_summary_file):
        return data
    with open(baseline_summary_file, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            s = line.strip()
            if "=" not in s:
                continue
            k, v = s.split("=", 1)
            data[k.strip()] = v.strip()
    return data


od, od_total, od_weights = read_od()
hours, hour_weights = read_hour_weights()
baseline = parse_baseline()
results = []

for scale_tag, scale_value in scales:
    demand_csv, flows_xml, total_target = write_demand(scale_tag, scale_value, od_weights, od_total, hours, hour_weights)
    trips_file, routes_file, route_log, rc1, rc2 = build_routes(scale_tag, flows_xml)
    cfg_file, tripinfo_file, summary_file, stats_file, edge_file, run_log = write_cfg(scale_tag, routes_file)
    rc_sumo, run_cmd_list = run_sim(cfg_file, run_log)
    metrics = parse_metrics(scale_tag, tripinfo_file, summary_file, edge_file, run_log, route_log, rc_sumo)
    metrics["scale_value"] = scale_value
    metrics["target_total"] = total_target
    metrics["demand_csv"] = demand_csv
    metrics["flows_xml"] = flows_xml
    metrics["trips_file"] = trips_file
    metrics["routes_file"] = routes_file
    metrics["cfg_file"] = cfg_file
    metrics["tripinfo_file"] = tripinfo_file
    metrics["summary_file"] = summary_file
    metrics["stats_file"] = stats_file
    metrics["edge_file"] = edge_file
    metrics["run_log"] = run_log
    metrics["route_log"] = route_log
    metrics["route_build_rc_od2trips"] = rc1
    metrics["route_build_rc_duarouter"] = rc2
    metrics["run_command"] = " ".join(run_cmd_list)
    results.append(metrics)

lines = []
lines.append("sensitivity comparison")
lines.append("")
lines.append("baseline_5pct")
for k in [
    "inserted_vehicles", "arrived_vehicles", "unfinished_vehicles", "teleports",
    "collisions", "avg_trip_duration", "avg_waiting_time", "avg_time_loss", "baseline_accepted"
]:
    if k in baseline:
        lines.append(f"{k}={baseline[k]}")
lines.append("")

for r in results:
    lines.append(f"scale={r['scale_value']} ({r['scale_tag']})")
    lines.append(f"target_total={r['target_total']}")
    lines.append(f"inserted={r['inserted']}")
    lines.append(f"arrived={r['arrived']}")
    lines.append(f"unfinished={r['unfinished']}")
    lines.append(f"teleports={r['teleports']}")
    if r["teleport_reasons"]:
        reason_text = ", ".join([f"{k}:{v}" for k, v in sorted(r["teleport_reasons"].items(), key=lambda x: x[1], reverse=True)])
    else:
        reason_text = "none"
    lines.append(f"teleport_reasons={reason_text}")
    lines.append(f"collisions={r['collisions']}")
    lines.append(f"avg_trip_duration={round(r['avg_duration'], 6)}")
    lines.append(f"avg_waiting_time={round(r['avg_waiting'], 6)}")
    lines.append(f"avg_time_loss={round(r['avg_time_loss'], 6)}")
    lines.append(f"route_build_od2trips_rc={r['route_build_rc_od2trips']}")
    lines.append(f"route_build_duarouter_rc={r['route_build_rc_duarouter']}")
    lines.append(f"sumo_rc={r['sumo_rc']}")
    lines.append(f"top_bottlenecks={', '.join(r['top_bottlenecks']) if r['top_bottlenecks'] else 'none'}")
    lines.append(f"route_warning_or_error_mentions={r['route_warning_or_error_mentions']}")
    lines.append("")

clean_scales = []
for r in results:
    if r["teleports"] == 0 and r["collisions"] == 0 and r["unfinished"] == 0 and r["sumo_rc"] == 0:
        clean_scales.append(r["scale_tag"])
lines.append(f"clean_scales_for_future_rebalancing={', '.join(clean_scales) if clean_scales else 'none'}")

with open(comparison_file, "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")

print("comparison file:", comparison_file)
for r in results:
    print(f"{r['scale_tag']}: inserted={r['inserted']}, arrived={r['arrived']}, teleports={r['teleports']}, collisions={r['collisions']}, unfinished={r['unfinished']}")
