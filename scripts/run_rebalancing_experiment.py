import os
import csv
import argparse
import xml.etree.ElementTree as ET
from datetime import datetime
import math


project_dir = r"E:\project_sakif_chicago"
sumo_bin = r"C:\Program Files (x86)\Eclipse\Sumo\bin\sumo.exe"
sumo_tools = r"C:\Program Files (x86)\Eclipse\Sumo\tools"

import sys
if sumo_tools not in sys.path:
    sys.path.append(sumo_tools)

import traci


def fnum(v):
    try:
        return float(v)
    except Exception:
        return 0.0


def parse_summary_file(path):
    inserted = 0
    arrived = 0
    teleports = 0
    collisions = 0
    running = 0
    waiting = 0
    if not os.path.exists(path):
        return {
            "inserted": 0,
            "arrived": 0,
            "unfinished": 0,
            "teleports": 0,
            "collisions": 0,
            "running": 0,
            "waiting": 0,
        }
    root = ET.parse(path).getroot()
    for step in root.findall("step"):
        inserted = max(inserted, int(fnum(step.get("inserted", "0"))))
        arrived = max(arrived, int(fnum(step.get("ended", "0"))))
        teleports = max(teleports, int(fnum(step.get("teleports", "0"))))
        collisions = max(collisions, int(fnum(step.get("collisions", "0"))))
        running = int(fnum(step.get("running", str(running))))
        waiting = int(fnum(step.get("waiting", str(waiting))))
    return {
        "inserted": inserted,
        "arrived": arrived,
        "unfinished": max(0, inserted - arrived),
        "teleports": teleports,
        "collisions": collisions,
        "running": running,
        "waiting": waiting,
    }


def parse_tripinfo_file(path):
    n = 0
    duration = 0.0
    waiting = 0.0
    timeloss = 0.0
    route_len = 0.0
    if not os.path.exists(path):
        return {
            "trip_count": 0,
            "avg_trip_duration": 0.0,
            "avg_waiting_time": 0.0,
            "avg_time_loss": 0.0,
            "avg_route_length": 0.0,
        }
    root = ET.parse(path).getroot()
    for t in root.findall("tripinfo"):
        n += 1
        duration += fnum(t.get("duration", "0"))
        waiting += fnum(t.get("waitingTime", "0"))
        timeloss += fnum(t.get("timeLoss", "0"))
        route_len += fnum(t.get("routeLength", "0"))
    if n == 0:
        return {
            "trip_count": 0,
            "avg_trip_duration": 0.0,
            "avg_waiting_time": 0.0,
            "avg_time_loss": 0.0,
            "avg_route_length": 0.0,
        }
    return {
        "trip_count": n,
        "avg_trip_duration": duration / n,
        "avg_waiting_time": waiting / n,
        "avg_time_loss": timeloss / n,
        "avg_route_length": route_len / n,
    }


def collect_metrics(summary_file, tripinfo_file):
    a = parse_summary_file(summary_file)
    b = parse_tripinfo_file(tripinfo_file)
    return {**a, **b}


def write_summary_txt(path, policy, metrics, baseline, reproduced, extra=None):
    if extra is None:
        extra = {}
    lines = []
    lines.append("rebalancing policy run summary")
    lines.append("")
    lines.append(f"policy={policy}")
    lines.append(f"timestamp={datetime.now().isoformat(timespec='seconds')}")
    lines.append("")
    lines.append("policy_metrics")
    lines.append(f"inserted={metrics['inserted']}")
    lines.append(f"arrived={metrics['arrived']}")
    lines.append(f"unfinished={metrics['unfinished']}")
    lines.append(f"teleports={metrics['teleports']}")
    lines.append(f"collisions={metrics['collisions']}")
    lines.append(f"avg_trip_duration={round(metrics['avg_trip_duration'], 6)}")
    lines.append(f"avg_waiting_time={round(metrics['avg_waiting_time'], 6)}")
    lines.append(f"avg_time_loss={round(metrics['avg_time_loss'], 6)}")
    if "rebalance_moves" in extra:
        lines.append(f"rebalance_moves={extra['rebalance_moves']}")
    if "eligible_idle_checks" in extra:
        lines.append(f"eligible_idle_checks={extra['eligible_idle_checks']}")
    if "decision_interval" in extra:
        lines.append(f"decision_interval={extra['decision_interval']}")
    if "max_rebalance_share" in extra:
        lines.append(f"max_rebalance_share={extra['max_rebalance_share']}")
    if "max_rebalance_count" in extra:
        lines.append(f"max_rebalance_count={extra['max_rebalance_count']}")
    lines.append("")
    lines.append("baseline_10pct_metrics")
    lines.append(f"inserted={baseline['inserted']}")
    lines.append(f"arrived={baseline['arrived']}")
    lines.append(f"unfinished={baseline['unfinished']}")
    lines.append(f"teleports={baseline['teleports']}")
    lines.append(f"collisions={baseline['collisions']}")
    lines.append(f"avg_trip_duration={round(baseline['avg_trip_duration'], 6)}")
    lines.append(f"avg_waiting_time={round(baseline['avg_waiting_time'], 6)}")
    lines.append(f"avg_time_loss={round(baseline['avg_time_loss'], 6)}")
    lines.append("")
    lines.append("difference_policy_minus_baseline")
    lines.append(f"inserted={metrics['inserted'] - baseline['inserted']}")
    lines.append(f"arrived={metrics['arrived'] - baseline['arrived']}")
    lines.append(f"unfinished={metrics['unfinished'] - baseline['unfinished']}")
    lines.append(f"teleports={metrics['teleports'] - baseline['teleports']}")
    lines.append(f"collisions={metrics['collisions'] - baseline['collisions']}")
    lines.append(f"avg_trip_duration={round(metrics['avg_trip_duration'] - baseline['avg_trip_duration'], 6)}")
    lines.append(f"avg_waiting_time={round(metrics['avg_waiting_time'] - baseline['avg_waiting_time'], 6)}")
    lines.append(f"avg_time_loss={round(metrics['avg_time_loss'] - baseline['avg_time_loss'], 6)}")
    lines.append("")
    lines.append(f"reproduces_baseline_closely={reproduced}")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def build_paths(policy):
    output_dir = os.path.join(project_dir, "output")
    os.makedirs(output_dir, exist_ok=True)
    tag = policy.upper()
    return {
        "tripinfo": os.path.join(output_dir, f"rebalancing_{tag}_tripinfo.xml"),
        "summary": os.path.join(output_dir, f"rebalancing_{tag}_summary.xml"),
        "statistics": os.path.join(output_dir, f"rebalancing_{tag}_statistics.xml"),
        "run_log": os.path.join(output_dir, f"rebalancing_{tag}_run.log"),
        "policy_log": os.path.join(output_dir, f"rebalancing_{tag}_policy_log.csv"),
        "summary_txt": os.path.join(output_dir, f"rebalancing_{tag}_summary.txt"),
    }


def load_zone_data():
    taz_file = os.path.join(project_dir, "data", "compact4_zones.taz.xml")
    od_file = os.path.join(project_dir, "output", "compact4_od_matrix.csv")
    zone_edges = {}
    edge_to_zone = {}
    target_edge = {}
    root = ET.parse(taz_file).getroot()
    for t in root.findall("taz"):
        zid = t.get("id", "").strip()
        edges = [e.strip() for e in (t.get("edges", "") or "").split() if e.strip()]
        zone_edges[zid] = edges
        if edges:
            target_edge[zid] = edges[0]
        for e in edges:
            if e not in edge_to_zone:
                edge_to_zone[e] = zid
    zones = sorted(zone_edges.keys())
    prod = {z: 0.0 for z in zones}
    attr = {z: 0.0 for z in zones}
    with open(od_file, "r", encoding="utf-8-sig", newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            o = row["origin_zone"].strip()
            if o not in prod:
                continue
            for z in zones:
                val = fnum(row.get(z, 0))
                prod[o] += val
                attr[z] += val
    total = sum(attr.values())
    if total > 0:
        share = {z: attr[z] / total for z in zones}
    else:
        share = {z: 0.0 for z in zones}
    return zones, zone_edges, edge_to_zone, target_edge, share


def run_policy_a(paths, decision_interval=300, prefix="A"):
    net_file = os.path.join(project_dir, "net", "map_reduced_clean_auto_v2.net.xml")
    route_file = os.path.join(project_dir, "routes", "compact4_benchmark_10.rou.xml")
    end_time = 86400

    cmd = [
        sumo_bin,
        "-n", net_file,
        "-r", route_file,
        "--tripinfo-output", paths["tripinfo"],
        "--summary-output", paths["summary"],
        "--statistic-output", paths["statistics"],
        "--duration-log.statistics", "true",
        "--no-step-log", "true",
        "--time-to-teleport", "-1",
        "--begin", "0",
        "--end", str(end_time),
    ]

    log_rows = []
    run_lines = []
    run_lines.append("rebalancing experiment run log")
    run_lines.append(f"policy={prefix}")
    run_lines.append("sumo_command=" + " ".join(cmd))

    traci.start(cmd)
    sim_time = 0
    step_count = 0
    departed_total = 0
    arrived_total = 0
    teleports_total = 0
    collisions_total = 0
    actions_total = 0

    has_start_tele = hasattr(traci.simulation, "getStartingTeleportNumber")
    has_end_tele = hasattr(traci.simulation, "getEndingTeleportNumber")
    has_coll = hasattr(traci.simulation, "getCollidingVehiclesNumber")

    while sim_time < end_time:
        traci.simulationStep()
        sim_time = int(traci.simulation.getTime())
        step_count += 1
        departed_total += int(traci.simulation.getDepartedNumber())
        arrived_total += int(traci.simulation.getArrivedNumber())
        if has_start_tele:
            teleports_total += int(traci.simulation.getStartingTeleportNumber())
        if has_end_tele:
            teleports_total += int(traci.simulation.getEndingTeleportNumber())
        if has_coll:
            collisions_total += int(traci.simulation.getCollidingVehiclesNumber())

        if sim_time % decision_interval == 0:
            running = int(traci.vehicle.getIDCount())
            waiting = int(traci.simulation.getMinExpectedNumber())
            log_rows.append({
                "time": sim_time,
                "policy": prefix,
                "source_zone": "",
                "target_zone": "",
                "vehicle_id": "",
                "action_taken": "none",
                "reason": "policy_no_rebalance",
                "rebalancing_actions": 0,
                "running_vehicles": running,
                "min_expected": waiting,
                "departed_cum": departed_total,
                "arrived_cum": arrived_total,
                "teleports_cum": teleports_total,
                "collisions_cum": collisions_total,
            })

    traci.close()

    run_lines.append(f"steps={step_count}")
    run_lines.append(f"departed_cum={departed_total}")
    run_lines.append(f"arrived_cum={arrived_total}")
    run_lines.append(f"teleports_cum={teleports_total}")
    run_lines.append(f"collisions_cum={collisions_total}")
    run_lines.append(f"policy_actions_cum={actions_total}")

    with open(paths["run_log"], "w", encoding="utf-8") as f:
        f.write("\n".join(run_lines) + "\n")

    with open(paths["policy_log"], "w", encoding="utf-8", newline="") as f:
        fieldnames = [
            "time",
            "policy",
            "source_zone",
            "target_zone",
            "vehicle_id",
            "action_taken",
            "reason",
            "rebalancing_actions",
            "running_vehicles",
            "min_expected",
            "departed_cum",
            "arrived_cum",
            "teleports_cum",
            "collisions_cum",
        ]
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in log_rows:
            w.writerow(row)
    return {"rebalance_moves": 0, "eligible_idle_checks": 0, "decision_interval": decision_interval}


def run_policy_b(paths, decision_interval=300, max_rebalance_share=0.15, max_rebalance_count=25):
    net_file = os.path.join(project_dir, "net", "map_reduced_clean_auto_v2.net.xml")
    route_file = os.path.join(project_dir, "routes", "compact4_benchmark_10.rou.xml")
    end_time = 86400
    zones, zone_edges, edge_to_zone, target_edge, demand_share = load_zone_data()

    cmd = [
        sumo_bin,
        "-n", net_file,
        "-r", route_file,
        "--tripinfo-output", paths["tripinfo"],
        "--summary-output", paths["summary"],
        "--statistic-output", paths["statistics"],
        "--duration-log.statistics", "true",
        "--no-step-log", "true",
        "--time-to-teleport", "-1",
        "--begin", "0",
        "--end", str(end_time),
    ]

    log_rows = []
    run_lines = []
    run_lines.append("rebalancing experiment run log")
    run_lines.append("policy=B")
    run_lines.append("sumo_command=" + " ".join(cmd))
    run_lines.append(f"decision_interval={decision_interval}")
    run_lines.append(f"max_rebalance_share={max_rebalance_share}")
    run_lines.append(f"max_rebalance_count={max_rebalance_count}")

    traci.start(cmd)
    sim_time = 0
    step_count = 0
    departed_total = 0
    arrived_total = 0
    teleports_total = 0
    collisions_total = 0
    moves_total = 0
    eligible_idle_checks = 0

    has_start_tele = hasattr(traci.simulation, "getStartingTeleportNumber")
    has_end_tele = hasattr(traci.simulation, "getEndingTeleportNumber")
    has_coll = hasattr(traci.simulation, "getCollidingVehiclesNumber")

    while sim_time < end_time:
        traci.simulationStep()
        sim_time = int(traci.simulation.getTime())
        step_count += 1
        departed_total += int(traci.simulation.getDepartedNumber())
        arrived_total += int(traci.simulation.getArrivedNumber())
        if has_start_tele:
            teleports_total += int(traci.simulation.getStartingTeleportNumber())
        if has_end_tele:
            teleports_total += int(traci.simulation.getEndingTeleportNumber())
        if has_coll:
            collisions_total += int(traci.simulation.getCollidingVehiclesNumber())

        if sim_time % decision_interval != 0:
            continue

        veh_ids = traci.vehicle.getIDList()
        idle_zone_veh = {z: [] for z in zones}
        for vid in veh_ids:
            try:
                route = traci.vehicle.getRoute(vid)
                route_idx = traci.vehicle.getRouteIndex(vid)
                speed = traci.vehicle.getSpeed(vid)
                road = traci.vehicle.getRoadID(vid)
            except Exception:
                continue
            if not route or route_idx < 0:
                continue
            if route_idx >= len(route) - 1 and speed <= 0.1:
                zid = edge_to_zone.get(road)
                if zid:
                    idle_zone_veh[zid].append(vid)

        idle_total = sum(len(v) for v in idle_zone_veh.values())
        eligible_idle_checks += idle_total
        running = int(traci.vehicle.getIDCount())
        min_expected = int(traci.simulation.getMinExpectedNumber())

        if idle_total <= 0:
            log_rows.append({
                "time": sim_time,
                "policy": "B",
                "source_zone": "",
                "target_zone": "",
                "vehicle_id": "",
                "action_taken": "none",
                "reason": "no_idle_vehicle",
                "rebalancing_actions": 0,
                "running_vehicles": running,
                "min_expected": min_expected,
                "departed_cum": departed_total,
                "arrived_cum": arrived_total,
                "teleports_cum": teleports_total,
                "collisions_cum": collisions_total,
            })
            continue

        shortage = {}
        current = {}
        desired = {}
        for z in zones:
            current[z] = len(idle_zone_veh[z])
            desired[z] = idle_total * demand_share.get(z, 0.0)
            shortage[z] = desired[z] - current[z]
        target_zone = max(zones, key=lambda z: shortage[z])
        if shortage[target_zone] <= 0:
            log_rows.append({
                "time": sim_time,
                "policy": "B",
                "source_zone": "",
                "target_zone": target_zone,
                "vehicle_id": "",
                "action_taken": "none",
                "reason": "no_shortage_signal",
                "rebalancing_actions": 0,
                "running_vehicles": running,
                "min_expected": min_expected,
                "departed_cum": departed_total,
                "arrived_cum": arrived_total,
                "teleports_cum": teleports_total,
                "collisions_cum": collisions_total,
            })
            continue

        cap_share = int(math.ceil(idle_total * max_rebalance_share))
        cap_short = int(math.ceil(shortage[target_zone]))
        move_cap = min(max_rebalance_count, cap_share, cap_short)
        if move_cap <= 0:
            log_rows.append({
                "time": sim_time,
                "policy": "B",
                "source_zone": "",
                "target_zone": target_zone,
                "vehicle_id": "",
                "action_taken": "none",
                "reason": "cap_zero",
                "rebalancing_actions": 0,
                "running_vehicles": running,
                "min_expected": min_expected,
                "departed_cum": departed_total,
                "arrived_cum": arrived_total,
                "teleports_cum": teleports_total,
                "collisions_cum": collisions_total,
            })
            continue

        source_order = sorted(zones, key=lambda z: (current[z] - desired[z]), reverse=True)
        moved_now = 0
        t_edge = target_edge.get(target_zone, "")
        if not t_edge:
            log_rows.append({
                "time": sim_time,
                "policy": "B",
                "source_zone": "",
                "target_zone": target_zone,
                "vehicle_id": "",
                "action_taken": "none",
                "reason": "missing_target_edge",
                "rebalancing_actions": 0,
                "running_vehicles": running,
                "min_expected": min_expected,
                "departed_cum": departed_total,
                "arrived_cum": arrived_total,
                "teleports_cum": teleports_total,
                "collisions_cum": collisions_total,
            })
            continue

        for sz in source_order:
            if moved_now >= move_cap:
                break
            if sz == target_zone:
                continue
            surplus = current[sz] - desired[sz]
            if surplus <= 0:
                continue
            for vid in list(idle_zone_veh[sz]):
                if moved_now >= move_cap:
                    break
                try:
                    traci.vehicle.changeTarget(vid, t_edge)
                    moved_now += 1
                    moves_total += 1
                    reason = f"gap_target={round(shortage[target_zone],3)};surplus_source={round(surplus,3)}"
                    log_rows.append({
                        "time": sim_time,
                        "policy": "B",
                        "source_zone": sz,
                        "target_zone": target_zone,
                        "vehicle_id": vid,
                        "action_taken": "move",
                        "reason": reason,
                        "rebalancing_actions": 1,
                        "running_vehicles": running,
                        "min_expected": min_expected,
                        "departed_cum": departed_total,
                        "arrived_cum": arrived_total,
                        "teleports_cum": teleports_total,
                        "collisions_cum": collisions_total,
                    })
                except Exception as ex:
                    log_rows.append({
                        "time": sim_time,
                        "policy": "B",
                        "source_zone": sz,
                        "target_zone": target_zone,
                        "vehicle_id": vid,
                        "action_taken": "move_failed",
                        "reason": str(ex).replace(",", ";"),
                        "rebalancing_actions": 0,
                        "running_vehicles": running,
                        "min_expected": min_expected,
                        "departed_cum": departed_total,
                        "arrived_cum": arrived_total,
                        "teleports_cum": teleports_total,
                        "collisions_cum": collisions_total,
                    })

        if moved_now == 0:
            log_rows.append({
                "time": sim_time,
                "policy": "B",
                "source_zone": "",
                "target_zone": target_zone,
                "vehicle_id": "",
                "action_taken": "none",
                "reason": "no_eligible_surplus_idle",
                "rebalancing_actions": 0,
                "running_vehicles": running,
                "min_expected": min_expected,
                "departed_cum": departed_total,
                "arrived_cum": arrived_total,
                "teleports_cum": teleports_total,
                "collisions_cum": collisions_total,
            })

    traci.close()

    run_lines.append(f"steps={step_count}")
    run_lines.append(f"departed_cum={departed_total}")
    run_lines.append(f"arrived_cum={arrived_total}")
    run_lines.append(f"teleports_cum={teleports_total}")
    run_lines.append(f"collisions_cum={collisions_total}")
    run_lines.append(f"policy_actions_cum={moves_total}")
    run_lines.append(f"eligible_idle_checks={eligible_idle_checks}")

    with open(paths["run_log"], "w", encoding="utf-8") as f:
        f.write("\n".join(run_lines) + "\n")

    with open(paths["policy_log"], "w", encoding="utf-8", newline="") as f:
        fieldnames = [
            "time",
            "policy",
            "source_zone",
            "target_zone",
            "vehicle_id",
            "action_taken",
            "reason",
            "rebalancing_actions",
            "running_vehicles",
            "min_expected",
            "departed_cum",
            "arrived_cum",
            "teleports_cum",
            "collisions_cum",
        ]
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in log_rows:
            w.writerow(row)

    return {
        "rebalance_moves": moves_total,
        "eligible_idle_checks": eligible_idle_checks,
        "decision_interval": decision_interval,
        "max_rebalance_share": max_rebalance_share,
        "max_rebalance_count": max_rebalance_count,
    }


def write_a_vs_b(path, a, b, b_extra):
    lines = []
    lines.append("rebalancing A vs B")
    lines.append("")
    lines.append("policy_A")
    lines.append(f"inserted={a['inserted']}")
    lines.append(f"arrived={a['arrived']}")
    lines.append(f"unfinished={a['unfinished']}")
    lines.append(f"teleports={a['teleports']}")
    lines.append(f"collisions={a['collisions']}")
    lines.append(f"avg_trip_duration={round(a['avg_trip_duration'],6)}")
    lines.append(f"avg_waiting_time={round(a['avg_waiting_time'],6)}")
    lines.append(f"avg_time_loss={round(a['avg_time_loss'],6)}")
    lines.append("")
    lines.append("policy_B")
    lines.append(f"inserted={b['inserted']}")
    lines.append(f"arrived={b['arrived']}")
    lines.append(f"unfinished={b['unfinished']}")
    lines.append(f"teleports={b['teleports']}")
    lines.append(f"collisions={b['collisions']}")
    lines.append(f"avg_trip_duration={round(b['avg_trip_duration'],6)}")
    lines.append(f"avg_waiting_time={round(b['avg_waiting_time'],6)}")
    lines.append(f"avg_time_loss={round(b['avg_time_loss'],6)}")
    lines.append(f"rebalance_moves={b_extra.get('rebalance_moves',0)}")
    lines.append(f"eligible_idle_checks={b_extra.get('eligible_idle_checks',0)}")
    lines.append("")
    lines.append("difference_B_minus_A")
    lines.append(f"inserted={b['inserted']-a['inserted']}")
    lines.append(f"arrived={b['arrived']-a['arrived']}")
    lines.append(f"unfinished={b['unfinished']-a['unfinished']}")
    lines.append(f"teleports={b['teleports']-a['teleports']}")
    lines.append(f"collisions={b['collisions']-a['collisions']}")
    lines.append(f"avg_trip_duration={round(b['avg_trip_duration']-a['avg_trip_duration'],6)}")
    lines.append(f"avg_waiting_time={round(b['avg_waiting_time']-a['avg_waiting_time'],6)}")
    lines.append(f"avg_time_loss={round(b['avg_time_loss']-a['avg_time_loss'],6)}")
    improved = "no"
    if b["teleports"] <= a["teleports"] and b["collisions"] <= a["collisions"] and b["avg_waiting_time"] < a["avg_waiting_time"]:
        improved = "yes"
    lines.append("")
    lines.append(f"meaningful_improvement={improved}")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", default="A")
    parser.add_argument("--decision-interval", type=int, default=300)
    parser.add_argument("--max-rebalance-share", type=float, default=0.15)
    parser.add_argument("--max-rebalance-count", type=int, default=25)
    args = parser.parse_args()

    policy = args.policy.strip().upper()
    if policy not in ["A", "B"]:
        raise ValueError("Only policy A and B are implemented now.")

    paths = build_paths(policy)

    if policy == "A":
        extra = run_policy_a(paths, decision_interval=args.decision_interval, prefix="A")
    else:
        extra = run_policy_b(
            paths,
            decision_interval=args.decision_interval,
            max_rebalance_share=args.max_rebalance_share,
            max_rebalance_count=args.max_rebalance_count,
        )

    metrics = collect_metrics(paths["summary"], paths["tripinfo"])
    output_dir = os.path.join(project_dir, "output")
    baseline_summary = os.path.join(output_dir, "baseline_summary_10.xml")
    baseline_tripinfo = os.path.join(output_dir, "baseline_tripinfo_10.xml")
    baseline = collect_metrics(baseline_summary, baseline_tripinfo)

    reproduced = "yes"
    if metrics["inserted"] != baseline["inserted"]:
        reproduced = "no"
    if metrics["arrived"] != baseline["arrived"]:
        reproduced = "no"
    if metrics["unfinished"] != baseline["unfinished"]:
        reproduced = "no"
    if metrics["teleports"] != baseline["teleports"]:
        reproduced = "no"
    if metrics["collisions"] != baseline["collisions"]:
        reproduced = "no"
    if abs(metrics["avg_trip_duration"] - baseline["avg_trip_duration"]) > 0.05:
        reproduced = "no"
    if abs(metrics["avg_waiting_time"] - baseline["avg_waiting_time"]) > 0.05:
        reproduced = "no"
    if abs(metrics["avg_time_loss"] - baseline["avg_time_loss"]) > 0.05:
        reproduced = "no"

    write_summary_txt(paths["summary_txt"], policy, metrics, baseline, reproduced, extra=extra)

    if policy == "B":
        a_metrics = collect_metrics(
            os.path.join(output_dir, "rebalancing_A_summary.xml"),
            os.path.join(output_dir, "rebalancing_A_tripinfo.xml"),
        )
        a_vs_b_file = os.path.join(output_dir, "rebalancing_A_vs_B.txt")
        write_a_vs_b(a_vs_b_file, a_metrics, metrics, extra)

    print("policy_run=success")
    print(f"policy={policy}")
    print(f"tripinfo={paths['tripinfo']}")
    print(f"summary={paths['summary']}")
    print(f"statistics={paths['statistics']}")
    print(f"run_log={paths['run_log']}")
    print(f"policy_log={paths['policy_log']}")
    print(f"summary_txt={paths['summary_txt']}")
    print(f"inserted={metrics['inserted']}")
    print(f"arrived={metrics['arrived']}")
    print(f"unfinished={metrics['unfinished']}")
    print(f"teleports={metrics['teleports']}")
    print(f"collisions={metrics['collisions']}")
    print(f"avg_trip_duration={round(metrics['avg_trip_duration'],6)}")
    print(f"avg_waiting_time={round(metrics['avg_waiting_time'],6)}")
    print(f"avg_time_loss={round(metrics['avg_time_loss'],6)}")
    if "rebalance_moves" in extra:
        print(f"rebalance_moves={extra['rebalance_moves']}")
    if "eligible_idle_checks" in extra:
        print(f"eligible_idle_checks={extra['eligible_idle_checks']}")
    if policy == "B":
        print(f"a_vs_b_file={os.path.join(output_dir, 'rebalancing_A_vs_B.txt')}")
    print(f"reproduces_baseline_closely={reproduced}")


if __name__ == "__main__":
    main()
