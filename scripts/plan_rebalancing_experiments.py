import os
import csv
import xml.etree.ElementTree as ET


project_dir = r"E:\project_sakif_chicago"

network_file = os.path.join(project_dir, "net", "map_reduced_clean_auto_v2.net.xml")
taz_file = os.path.join(project_dir, "data", "compact4_zones.taz.xml")
route_file = os.path.join(project_dir, "routes", "compact4_benchmark_10.rou.xml")
config_file = os.path.join(project_dir, "cfg", "baseline_benchmark_10.sumocfg")

od_file = os.path.join(project_dir, "output", "compact4_od_matrix.csv")
time_file = os.path.join(project_dir, "output", "compact4_time_profile.csv")
summary_10_file = os.path.join(project_dir, "output", "baseline_summary_10.xml")
tripinfo_10_file = os.path.join(project_dir, "output", "baseline_tripinfo_10.xml")
edge_10_file = os.path.join(project_dir, "output", "baseline_queue_or_edge_stats_10.xml")
sens_file = os.path.join(project_dir, "output", "sensitivity_comparison.txt")

plan_txt = os.path.join(project_dir, "output", "rebalancing_experiment_plan.txt")
policy_csv = os.path.join(project_dir, "output", "rebalancing_policy_definitions.csv")


def fnum(v):
    try:
        return float(v)
    except Exception:
        return 0.0


def read_od_shares(path):
    zones = []
    matrix = {}
    total = 0.0
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        r = csv.DictReader(f)
        zones = [x for x in r.fieldnames if x != "origin_zone"]
        for row in r:
            o = row["origin_zone"].strip()
            for d in zones:
                val = fnum(row.get(d, 0))
                matrix[(o, d)] = val
                total += val
    shares = {}
    for k, v in matrix.items():
        shares[k] = (v / total) if total > 0 else 0.0
    prod = {z: 0.0 for z in zones}
    attr = {z: 0.0 for z in zones}
    for (o, d), v in matrix.items():
        prod[o] += v
        attr[d] += v
    return zones, matrix, shares, prod, attr, total


def read_hour_profile(path):
    hours = []
    totals = {}
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            h = int(float(row["hour"]))
            t = fnum(row.get("total_trips", 0))
            hours.append(h)
            totals[h] = t
    peak = sorted(hours, key=lambda h: totals[h], reverse=True)[:3]
    return hours, totals, peak


def parse_10pct_metrics(summary_file, tripinfo_file):
    inserted = arrived = teleports = collisions = 0
    if os.path.exists(summary_file):
        root = ET.parse(summary_file).getroot()
        for step in root.findall("step"):
            inserted = max(inserted, int(fnum(step.get("inserted", "0"))))
            arrived = max(arrived, int(fnum(step.get("ended", "0"))))
            teleports = max(teleports, int(fnum(step.get("teleports", "0"))))
            collisions = max(collisions, int(fnum(step.get("collisions", "0"))))
    unfinished = max(0, inserted - arrived)
    n = 0
    dur = wt = tl = 0.0
    if os.path.exists(tripinfo_file):
        root = ET.parse(tripinfo_file).getroot()
        for t in root.findall("tripinfo"):
            n += 1
            dur += fnum(t.get("duration", "0"))
            wt += fnum(t.get("waitingTime", "0"))
            tl += fnum(t.get("timeLoss", "0"))
    avg_d = dur / n if n > 0 else 0.0
    avg_w = wt / n if n > 0 else 0.0
    avg_t = tl / n if n > 0 else 0.0
    return {
        "inserted": inserted,
        "arrived": arrived,
        "unfinished": unfinished,
        "teleports": teleports,
        "collisions": collisions,
        "avg_duration": avg_d,
        "avg_waiting": avg_w,
        "avg_time_loss": avg_t,
    }


def top_edges(edge_file):
    vals = []
    if not os.path.exists(edge_file):
        return vals
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
            vals.append((score, eid))
    vals.sort(key=lambda x: x[0], reverse=True)
    return [x[1] for x in vals[:5]]


required = [network_file, taz_file, route_file, config_file, od_file, time_file, summary_10_file, tripinfo_10_file]
missing = [p for p in required if not os.path.exists(p)]

zones, matrix, shares, prod, attr, total_od = read_od_shares(od_file)
hours, hourly_totals, peak_hours = read_hour_profile(time_file)
m = parse_10pct_metrics(summary_10_file, tripinfo_10_file)
bottlenecks = top_edges(edge_10_file)

primary_pull_zone = max(attr.keys(), key=lambda z: attr[z])
primary_share_zone = max(prod.keys(), key=lambda z: prod[z])

os.makedirs(os.path.dirname(plan_txt), exist_ok=True)

rows = [
    {
        "policy_id": "A",
        "policy_name": "no_rebalancing",
        "decision_logic": "Do not send any explicit empty rebalancing trips. Keep only passenger demand service routes.",
        "required_inputs": "network, routes_10pct, taz, compact4_od_matrix, compact4_time_profile",
        "simulation_control_approach": "Open-loop baseline replay using existing routed demand; no TraCI rebalancing actions.",
        "measurement_outcomes": "served trips, unfinished, teleports, collisions, avg waiting, avg time loss, zone-level imbalance",
        "academic_positioning": "baseline",
        "implementation_order": "1",
    },
    {
        "policy_id": "B",
        "policy_name": "idle_to_high_demand_zone",
        "decision_logic": f"At fixed interval, send a capped fraction of currently idle vehicles from surplus zones toward one current target zone (default target by demand attraction share, initially {primary_pull_zone}).",
        "required_inputs": "A + interval_seconds + per_step_rebalance_cap + idle_vehicle_detector + zone_surplus_rule",
        "simulation_control_approach": "TraCI loop every interval; identify idle vehicles and assign target edges in chosen high-demand zone.",
        "measurement_outcomes": "A metrics + empty_vehicle_km + rebalancing_trip_count + pickup delay reduction",
        "academic_positioning": "heuristic",
        "implementation_order": "2",
    },
    {
        "policy_id": "C",
        "policy_name": "demand_share_based_rebalancing",
        "decision_logic": "At fixed interval, compute desired idle vehicles per zone using compact4 demand shares and current total idle pool; move only surplus idle vehicles to deficit zones with capped transfer per step.",
        "required_inputs": "B inputs + zone demand share vector from compact4_od_matrix + current idle count by zone",
        "simulation_control_approach": "TraCI loop every interval; solve simple deficit-surplus matching by greedy nearest-zone transfer.",
        "measurement_outcomes": "B metrics + zone imbalance score over time + stability across peak hours",
        "academic_positioning": "heuristic",
        "implementation_order": "3",
    },
]

with open(policy_csv, "w", encoding="utf-8", newline="") as f:
    fields = [
        "policy_id",
        "policy_name",
        "decision_logic",
        "required_inputs",
        "simulation_control_approach",
        "measurement_outcomes",
        "academic_positioning",
        "implementation_order",
    ]
    w = csv.DictWriter(f, fieldnames=fields)
    w.writeheader()
    for r in rows:
        w.writerow(r)

lines = []
lines.append("rebalancing experiment plan")
lines.append("")
lines.append("scope")
lines.append("first rebalancing experiment framework on accepted 10% benchmark")
lines.append("no RL; baseline + simple heuristics only")
lines.append("")
lines.append("artifact check")
if missing:
    lines.append("status=insufficient")
    lines.append("missing_files:")
    for p in missing:
        lines.append(p)
else:
    lines.append("status=sufficient")
    lines.append("all required 10% artifacts are present")
lines.append("")
lines.append("10pct baseline reference")
lines.append(f"inserted={m['inserted']}")
lines.append(f"arrived={m['arrived']}")
lines.append(f"unfinished={m['unfinished']}")
lines.append(f"teleports={m['teleports']}")
lines.append(f"collisions={m['collisions']}")
lines.append(f"avg_duration={round(m['avg_duration'],6)}")
lines.append(f"avg_waiting={round(m['avg_waiting'],6)}")
lines.append(f"avg_time_loss={round(m['avg_time_loss'],6)}")
lines.append("")
lines.append("compact4 demand structure")
lines.append(f"zones={', '.join(zones)}")
lines.append(f"total_od={round(total_od,6)}")
lines.append("zone_production_share")
for z in zones:
    lines.append(f"{z}={round(prod[z]/total_od,6) if total_od>0 else 0.0}")
lines.append("zone_attraction_share")
for z in zones:
    lines.append(f"{z}={round(attr[z]/total_od,6) if total_od>0 else 0.0}")
lines.append(f"highest_attraction_zone={primary_pull_zone}")
lines.append(f"highest_production_zone={primary_share_zone}")
lines.append("")
lines.append("hourly shape guidance")
lines.append(f"top_hours_by_total_demand={', '.join([str(h) for h in peak_hours])}")
lines.append("")
lines.append("policy sequence")
lines.append("1) policy A no_rebalancing")
lines.append("2) policy B idle_to_high_demand_zone")
lines.append("3) policy C demand_share_based_rebalancing")
lines.append("")
lines.append("simulation control approach")
lines.append("use one experiment runner with TraCI support")
lines.append("run policy A as no-action reference")
lines.append("run policies B and C with same interval and same rebalancing cap for fair comparison")
lines.append("")
lines.append("primary metrics")
lines.append("1) unfinished vehicles")
lines.append("2) teleports and reasons")
lines.append("3) avg waiting time")
lines.append("4) avg time loss")
lines.append("5) served/arrived count")
lines.append("secondary metrics")
lines.append("1) empty_vehicle_km")
lines.append("2) rebalancing trip count")
lines.append("3) bottleneck edge persistence")
lines.append(f"baseline bottleneck edges={', '.join(bottlenecks) if bottlenecks else 'n/a'}")
lines.append("")
lines.append("file plan")
lines.append("reuse")
lines.append(f"- {network_file}")
lines.append(f"- {taz_file}")
lines.append(f"- {route_file}")
lines.append(f"- {config_file}")
lines.append("new scripts to implement next")
lines.append("- scripts/run_rebalancing_experiment.py")
lines.append("- scripts/rebalancing_policy_a.py")
lines.append("- scripts/rebalancing_policy_b.py")
lines.append("- scripts/rebalancing_policy_c.py")
lines.append("- scripts/analyze_rebalancing_results.py")
lines.append("new output pattern per policy")
lines.append("- output/rebalancing_<policy>_tripinfo.xml")
lines.append("- output/rebalancing_<policy>_summary.xml")
lines.append("- output/rebalancing_<policy>_statistics.xml")
lines.append("- output/rebalancing_<policy>_run.log")
lines.append("- output/rebalancing_<policy>_policy_log.csv")
lines.append("")
lines.append("academic framing safety")
lines.append("these are baseline and heuristic controls")
lines.append("no novelty claim")
lines.append("goal is reproducible benchmark comparison before advanced methods")
lines.append("")
lines.append("recommended first implementation")
lines.append("policy A first, then policy B")
lines.append("after B is stable and metrics are clean, implement policy C")
lines.append("")
lines.append("exact next step")
lines.append("implement scripts/run_rebalancing_experiment.py with policy A only (no-action), produce output/rebalancing_A_* files using the 10% scenario.")

with open(plan_txt, "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")

print("plan file:", plan_txt)
print("policy csv:", policy_csv)
