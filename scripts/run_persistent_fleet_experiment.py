import os
import csv
import argparse
import xml.etree.ElementTree as ET
from datetime import datetime
import math
import shutil
import subprocess
import re


script_dir = os.path.dirname(os.path.abspath(__file__))
project_dir = os.path.abspath(os.path.join(script_dir, ".."))
sumo_home = os.environ.get("SUMO_HOME", "")
sumo_bin = os.environ.get("SUMO_BIN", "sumo")
if not shutil.which(sumo_bin):
    alt = "sumo.exe" if os.name == "nt" else "sumo"
    if shutil.which(alt):
        sumo_bin = alt
sumo_tools = os.path.join(sumo_home, "tools") if sumo_home else ""

import sys
if sumo_tools and sumo_tools not in sys.path:
    sys.path.append(sumo_tools)

import traci


def fnum(v):
    try:
        return float(v)
    except Exception:
        return 0.0


def load_zone_edges():
    service_files = {
        "cz1": os.path.join(project_dir, "data", "compact4_service_edges_cz1.txt"),
        "cz2": os.path.join(project_dir, "data", "compact4_service_edges_cz2.txt"),
        "cz3": os.path.join(project_dir, "data", "compact4_service_edges_cz3.txt"),
        "cz4": os.path.join(project_dir, "data", "compact4_service_edges_cz4.txt"),
    }
    zone_edges = {}
    edge_zone = {}
    taz_file = os.path.join(project_dir, "data", "compact4_zones.taz.xml")
    root = ET.parse(taz_file).getroot()
    raw_zone = {}
    for t in root.findall("taz"):
        zid = t.get("id", "").strip()
        raw_edges = [e.strip() for e in (t.get("edges", "") or "").split() if e.strip()]
        edges = [e for e in raw_edges if not e.startswith("-")]
        if not edges:
            edges = raw_edges
        raw_zone[zid] = edges

    for z in sorted(raw_zone.keys()):
        edges = []
        p = service_files.get(z)
        if p and os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                for line in f:
                    e = line.strip()
                    if e:
                        edges.append(e)
        if not edges:
            edges = raw_zone[z]
        zone_edges[z] = edges
    for z, edges in zone_edges.items():
        for e in edges:
            if e not in edge_zone:
                edge_zone[e] = z
    zones = sorted(zone_edges.keys())
    return zones, zone_edges, edge_zone


def load_demand_shares(zones):
    od_file = os.path.join(project_dir, "output", "compact4_od_matrix.csv")
    prod = {z: 0.0 for z in zones}
    attr = {z: 0.0 for z in zones}
    with open(od_file, "r", encoding="utf-8-sig", newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            o = row["origin_zone"].strip()
            if o not in prod:
                continue
            for z in zones:
                v = fnum(row.get(z, 0))
                prod[o] += v
                attr[z] += v
    s = sum(attr.values())
    if s > 0:
        share = {z: attr[z] / s for z in zones}
    else:
        share = {z: 1.0 / len(zones) for z in zones}
    return share


def infer_request_scale(request_path):
    name = os.path.basename(request_path)
    m = re.search(r"s0p(\d{3})", name)
    if not m:
        return ""
    try:
        return f"{int(m.group(1)) / 1000.0:.3f}"
    except Exception:
        return ""


def read_requests(path, valid_zones, valid_edges):
    rows = []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        r = csv.DictReader(f)
        if r.fieldnames is None:
            raise ValueError(f"request file has no header: {path}")
        required = ["request_id", "request_time", "origin_zone", "destination_zone"]
        for k in required:
            if k not in r.fieldnames:
                raise ValueError(f"request file missing required column '{k}': {path}")
        has_origin_edge = "origin_edge" in r.fieldnames
        has_destination_edge = "destination_edge" in r.fieldnames
        if has_origin_edge != has_destination_edge:
            raise ValueError("request file must include both origin_edge and destination_edge columns together")
        edge_columns_used = has_origin_edge and has_destination_edge
        for row in r:
            rid = (row.get("request_id") or "").strip()
            oz = (row.get("origin_zone") or "").strip()
            dz = (row.get("destination_zone") or "").strip()
            if oz not in valid_zones:
                raise ValueError(f"invalid origin_zone '{oz}' for request_id '{rid}'")
            if dz not in valid_zones:
                raise ValueError(f"invalid destination_zone '{dz}' for request_id '{rid}'")
            oe = ""
            de = ""
            if edge_columns_used:
                oe = (row.get("origin_edge") or "").strip()
                de = (row.get("destination_edge") or "").strip()
                if not oe or not de:
                    raise ValueError(f"request_id '{rid}' has empty origin_edge/destination_edge with edge columns present")
                if oe not in valid_edges:
                    raise ValueError(f"request_id '{rid}' has invalid origin_edge '{oe}'")
                if de not in valid_edges:
                    raise ValueError(f"request_id '{rid}' has invalid destination_edge '{de}'")
            rows.append({
                "request_id": rid,
                "request_time": int(float(row["request_time"])),
                "origin_zone": oz,
                "destination_zone": dz,
                "origin_edge": oe,
                "destination_edge": de,
            })
    rows.sort(key=lambda x: (x["request_time"], x["request_id"]))
    return rows, edge_columns_used


def choose_zone_from_shares(shares, index):
    order = sorted(shares.keys())
    vals = [shares[z] for z in order]
    s = sum(vals)
    if s <= 0:
        return order[index % len(order)]
    threshold = ((index % 10000) + 0.5) / 10000.0
    run = 0.0
    for z in order:
        run += shares[z] / s
        if threshold <= run:
            return z
    return order[-1]


def build_edge_pick(zone_edges):
    zone_idx = {z: 0 for z in zone_edges}
    def pick(zone):
        edges = zone_edges.get(zone, [])
        if not edges:
            return ""
        i = zone_idx[zone]
        edge = edges[i % len(edges)]
        zone_idx[zone] = i + 1
        return edge
    return pick


def initialize_fleet(fleet_size, zones, zone_edges, demand_share, pick_edge):
    vehicles = {}
    type_id = "fleetType"
    for i in range(fleet_size):
        zid = choose_zone_from_shares(demand_share, i)
        start_edge = pick_edge(zid)
        if not start_edge:
            continue
        rid = f"init_route_{i:05d}"
        vid = f"veh_{i:05d}"
        traci.route.add(rid, [start_edge])
        traci.vehicle.add(vid, rid, typeID=type_id, depart="0", departLane="best", departSpeed="max")
        vehicles[vid] = {
            "status": "idle",
            "zone": zid,
            "edge": start_edge,
            "request_id": "",
            "origin_edge": "",
            "dest_edge": "",
            "phase": "",
            "assigned_time": -1,
        }
    return vehicles


def parse_tripinfo(path):
    n = 0
    d = w = tl = 0.0
    if not os.path.exists(path):
        return 0, 0.0, 0.0, 0.0
    root = ET.parse(path).getroot()
    for t in root.findall("tripinfo"):
        n += 1
        d += fnum(t.get("duration", "0"))
        w += fnum(t.get("waitingTime", "0"))
        tl += fnum(t.get("timeLoss", "0"))
    if n == 0:
        return 0, 0.0, 0.0, 0.0
    return n, d / n, w / n, tl / n


def setup_fleet_type():
    try:
        traci.vehicletype.copy("DEFAULT_VEHTYPE", "fleetType")
    except Exception:
        pass
    try:
        traci.vehicletype.setImperfection("fleetType", 0.0)
    except Exception:
        pass
    try:
        traci.vehicletype.setSpeedDeviation("fleetType", 0.0)
    except Exception:
        pass


def supports_option(option_name):
    try:
        res = subprocess.run([sumo_bin, "--help"], capture_output=True, text=True, timeout=10)
        text = (res.stdout or "") + "\n" + (res.stderr or "")
        return option_name in text
    except Exception:
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", default="A")
    parser.add_argument("--fleet-size", type=int, default=300)
    parser.add_argument("--decision-interval", type=int, default=30)
    parser.add_argument("--same-zone-candidate-cap", type=int, default=15)
    parser.add_argument("--global-candidate-cap", type=int, default=15)
    parser.add_argument("--max-rebalance-share", type=float, default=0.15)
    parser.add_argument("--max-rebalance-count", type=int, default=25)
    parser.add_argument("--rebalance-shortage-threshold", type=float, default=0.0)
    parser.add_argument("--rebalance-min-shortage", type=int, default=1)
    parser.add_argument("--rebalance-intensity-scale", type=float, default=1.0)
    parser.add_argument("--request-file", default=os.path.join(project_dir, "data", "compact4_request_stream.csv"))
    parser.add_argument("--end-time", type=int, default=86400)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--cgated-debug-file", default="")
    parser.add_argument("--output-prefix", default="persistent_A")
    parser.add_argument("--stage-summary-file", default=os.path.join(project_dir, "output", "persistent_fleet_stage1_summary.txt"))
    args = parser.parse_args()

    policy = args.policy.strip().upper()
    if policy not in ["A", "B", "C", "CG"]:
        raise ValueError("Only policy A, B, C and CG are implemented.")

    out_dir = os.path.join(project_dir, "output")
    os.makedirs(out_dir, exist_ok=True)

    prefix = args.output_prefix.strip()
    tripinfo_file = os.path.join(out_dir, f"{prefix}_tripinfo.xml")
    stats_file = os.path.join(out_dir, f"{prefix}_statistics.xml")
    summary_xml = os.path.join(out_dir, f"{prefix}_summary.xml")
    run_log = os.path.join(out_dir, f"{prefix}_run.log")
    policy_log = os.path.join(out_dir, f"{prefix}_policy_log.csv")
    summary_txt = os.path.join(out_dir, f"{prefix}_summary.txt")
    stage1_txt = args.stage_summary_file

    zones, zone_edges, edge_zone = load_zone_edges()
    demand_share = load_demand_shares(zones)
    requests, request_edge_columns_used = read_requests(
        args.request_file,
        set(zones),
        set(edge_zone.keys()),
    )
    pick_edge = build_edge_pick(zone_edges)
    network_file = os.path.join(project_dir, "net", "map_reduced_clean_auto_v2.net.xml")
    request_scale = infer_request_scale(args.request_file)

    cmd = [
        sumo_bin,
        "-n", network_file,
        "--tripinfo-output", tripinfo_file,
        "--summary-output", summary_xml,
        "--duration-log.statistics", "true",
        "--no-step-log", "true",
        "--seed", str(args.seed),
        "--begin", "0",
        "--end", str(args.end_time),
    ]
    statistics_output_enabled = supports_option("--statistic-output")
    if statistics_output_enabled:
        cmd.extend(["--statistic-output", stats_file])

    traci.start(cmd)
    setup_fleet_type()
    vehicles = initialize_fleet(args.fleet_size, zones, zone_edges, demand_share, pick_edge)
    fleet_init_count = len(vehicles)
    traci.simulationStep()

    req_idx = 0
    open_queue = []
    served = 0
    assigned = 0
    no_vehicle = 0
    no_path = 0
    dropped = 0
    rebalance_moves = 0
    log_rows = []
    step_rows = []
    cgated_debug_rows = []
    sim_time = int(traci.simulation.getTime())

    while sim_time < args.end_time:
        traci.simulationStep()
        sim_time = int(traci.simulation.getTime())

        while req_idx < len(requests) and requests[req_idx]["request_time"] <= sim_time:
            open_queue.append(requests[req_idx])
            req_idx += 1

        for vid in list(vehicles.keys()):
            if vid not in traci.vehicle.getIDList():
                if vehicles[vid]["status"] == "serving":
                    dropped += 1
                vehicles.pop(vid, None)

        for vid, st in vehicles.items():
            try:
                edge = traci.vehicle.getRoadID(vid)
            except Exception:
                continue
            if edge and not edge.startswith(":"):
                st["edge"] = edge
                st["zone"] = edge_zone.get(edge, st["zone"])
            if st["status"] == "idle":
                try:
                    route = traci.vehicle.getRoute(vid)
                    route_idx = traci.vehicle.getRouteIndex(vid)
                    if route and route_idx >= len(route) - 1:
                        keep_edge = pick_edge(st["zone"])
                        if keep_edge:
                            traci.vehicle.changeTarget(vid, keep_edge)
                            log_rows.append({
                                "time": sim_time,
                                "vehicle_id": vid,
                                "request_id": "",
                                "origin_zone": st["zone"],
                                "destination_zone": st["zone"],
                                "action": "idle_keepalive",
                                "status": "idle",
                                "reason": "extend_idle_route",
                            })
                except Exception:
                    pass
            if st["status"] == "serving":
                if st["phase"] == "pickup":
                    if st["edge"] == st["origin_edge"]:
                        try:
                            traci.vehicle.changeTarget(vid, st["dest_edge"])
                            st["phase"] = "dropoff"
                            log_rows.append({
                                "time": sim_time,
                                "vehicle_id": vid,
                                "request_id": st["request_id"],
                                "origin_zone": st.get("origin_zone", ""),
                                "destination_zone": st.get("destination_zone", ""),
                                "action": "pickup_reached",
                                "status": "serving",
                                "reason": "pickup_completed",
                            })
                        except Exception:
                            no_path += 1
                            st["status"] = "idle"
                            st["phase"] = ""
                            st["request_id"] = ""
                elif st["phase"] == "dropoff":
                    if st["edge"] == st["dest_edge"]:
                        served += 1
                        st["status"] = "idle"
                        st["phase"] = ""
                        st["request_id"] = ""
                        log_rows.append({
                            "time": sim_time,
                            "vehicle_id": vid,
                            "request_id": "",
                            "origin_zone": "",
                            "destination_zone": "",
                            "action": "dropoff_complete_idle",
                            "status": "idle",
                            "reason": "service_completed",
                        })

        if sim_time % args.decision_interval == 0:
            idle_ids = [vid for vid, st in vehicles.items() if st["status"] == "idle"]

            q_next = []
            for req in open_queue:
                idle_ids = [vid for vid in idle_ids if vid in vehicles and vehicles[vid]["status"] == "idle"]
                if not idle_ids:
                    q_next.append(req)
                    no_vehicle += 1
                    continue
                o_zone = req["origin_zone"]
                d_zone = req["destination_zone"]
                o_edge = req.get("origin_edge", "") or pick_edge(o_zone)
                d_edge = req.get("destination_edge", "") or pick_edge(d_zone)
                if not o_edge or not d_edge:
                    no_path += 1
                    continue

                same_zone_idle = sorted([vid for vid in idle_ids if vehicles[vid]["zone"] == o_zone])
                if same_zone_idle:
                    candidate_ids = same_zone_idle[:max(1, args.same_zone_candidate_cap)]
                else:
                    candidate_ids = sorted(idle_ids)[:max(1, args.global_candidate_cap)]
                best_vid = ""
                best_cost = None
                for vid in candidate_ids:
                    try:
                        r = traci.simulation.findRoute(vehicles[vid]["edge"], o_edge)
                        if not r.edges:
                            continue
                        cost = r.travelTime
                        if best_cost is None or cost < best_cost:
                            best_cost = cost
                            best_vid = vid
                    except Exception:
                        continue
                if not best_vid:
                    q_next.append(req)
                    no_path += 1
                    continue

                try:
                    traci.vehicle.changeTarget(best_vid, o_edge)
                    vehicles[best_vid]["status"] = "serving"
                    vehicles[best_vid]["phase"] = "pickup"
                    vehicles[best_vid]["request_id"] = req["request_id"]
                    vehicles[best_vid]["origin_edge"] = o_edge
                    vehicles[best_vid]["dest_edge"] = d_edge
                    vehicles[best_vid]["origin_zone"] = o_zone
                    vehicles[best_vid]["destination_zone"] = d_zone
                    vehicles[best_vid]["assigned_time"] = sim_time
                    assigned += 1
                    idle_ids.remove(best_vid)
                    log_rows.append({
                        "time": sim_time,
                        "vehicle_id": best_vid,
                        "request_id": req["request_id"],
                        "origin_zone": o_zone,
                        "destination_zone": d_zone,
                        "action": "assign_request",
                        "status": "serving",
                        "reason": "zone_first_nearest",
                    })
                except Exception:
                    q_next.append(req)
                    no_path += 1
            open_queue = q_next

            if policy in ["B", "C", "CG"]:
                idle_ids = [vid for vid, st in vehicles.items() if st["status"] == "idle"]
                idle_total = len(idle_ids)
                idle_by_zone = {z: 0 for z in zones}
                for vid in idle_ids:
                    zid = vehicles[vid]["zone"]
                    if zid in idle_by_zone:
                        idle_by_zone[zid] += 1
                if idle_total > 0:
                    desired = {z: idle_total * demand_share.get(z, 0.0) for z in zones}
                    shortage = {z: desired[z] - idle_by_zone[z] for z in zones}
                    cap_share = int(math.ceil(idle_total * args.max_rebalance_share))
                    move_cap = min(args.max_rebalance_count, cap_share)
                    move_cap = int(math.ceil(move_cap * max(0.0, args.rebalance_intensity_scale)))
                    min_shortage = max(
                        args.rebalance_min_shortage,
                        int(math.ceil(idle_total * max(0.0, args.rebalance_shortage_threshold))),
                    )
                    active_deficits = [z for z in zones if shortage[z] >= min_shortage]
                    debug_reason = ""
                    moved_now = 0
                    if policy == "B":
                        target_zone = max(zones, key=lambda z: shortage[z])
                        if active_deficits:
                            target_zone = max(active_deficits, key=lambda z: shortage[z])
                        target_gap = shortage[target_zone]
                        if target_gap > 0 and target_zone in active_deficits:
                            move_cap = min(move_cap, int(math.ceil(target_gap)))
                            if move_cap > 0:
                                surplus_order = sorted(
                                    zones,
                                    key=lambda z: (idle_by_zone[z] - desired[z]),
                                    reverse=True,
                                )
                                target_edge = pick_edge(target_zone)
                                moved_now = 0
                                for sz in surplus_order:
                                    if moved_now >= move_cap:
                                        break
                                    if sz == target_zone:
                                        continue
                                    surplus = idle_by_zone[sz] - desired[sz]
                                    if surplus <= 0:
                                        continue
                                    source_ids = [vid for vid in idle_ids if vehicles[vid]["zone"] == sz]
                                    source_ids = sorted(source_ids)
                                    for vid in source_ids:
                                        if moved_now >= move_cap:
                                            break
                                        if vehicles.get(vid, {}).get("status") != "idle":
                                            continue
                                        try:
                                            traci.vehicle.changeTarget(vid, target_edge)
                                            moved_now += 1
                                            rebalance_moves += 1
                                            idle_by_zone[sz] = max(0, idle_by_zone[sz] - 1)
                                            idle_by_zone[target_zone] += 1
                                            log_rows.append({
                                                "time": sim_time,
                                                "vehicle_id": vid,
                                                "request_id": "",
                                                "origin_zone": sz,
                                                "destination_zone": target_zone,
                                                "action": "rebalance_move",
                                                "status": "idle",
                                                "reason": "policy_B_demand_gap",
                                            })
                                        except Exception:
                                            pass
                        else:
                            debug_reason = "no_active_target_or_gap"
                    else:
                        if move_cap > 0:
                            deficit_order = sorted(
                                active_deficits,
                                key=lambda z: shortage[z],
                                reverse=True,
                            )
                            surplus_order = sorted(
                                [z for z in zones if (idle_by_zone[z] - desired[z]) > 0],
                                key=lambda z: (idle_by_zone[z] - desired[z]),
                                reverse=True,
                            )
                            moved_now = 0
                            for dz in deficit_order:
                                if moved_now >= move_cap:
                                    break
                                target_edge = pick_edge(dz)
                                if not target_edge:
                                    continue
                                need = int(math.ceil(shortage[dz]))
                                if need <= 0:
                                    continue
                                for sz in surplus_order:
                                    if moved_now >= move_cap or need <= 0:
                                        break
                                    if sz == dz:
                                        continue
                                    surplus = int(math.floor(idle_by_zone[sz] - desired[sz]))
                                    if surplus <= 0:
                                        continue
                                    source_ids = [vid for vid in idle_ids if vehicles[vid]["zone"] == sz]
                                    source_ids = sorted(source_ids)
                                    for vid in source_ids:
                                        if moved_now >= move_cap or need <= 0 or surplus <= 0:
                                            break
                                        if vehicles.get(vid, {}).get("status") != "idle":
                                            continue
                                        try:
                                            traci.vehicle.changeTarget(vid, target_edge)
                                            moved_now += 1
                                            rebalance_moves += 1
                                            need -= 1
                                            surplus -= 1
                                            idle_by_zone[sz] = max(0, idle_by_zone[sz] - 1)
                                            idle_by_zone[dz] += 1
                                            log_rows.append({
                                                "time": sim_time,
                                                "vehicle_id": vid,
                                                "request_id": "",
                                                "origin_zone": sz,
                                                "destination_zone": dz,
                                                "action": "rebalance_move",
                                                "status": "idle",
                                                "reason": "policy_C_demand_share_balance" if policy == "C" else "policy_C_gated_demand_share_balance",
                                            })
                                        except Exception:
                                            pass
                            if policy == "CG" and moved_now == 0:
                                if len(active_deficits) == 0:
                                    debug_reason = "no_active_deficit"
                                elif len(surplus_order) == 0:
                                    debug_reason = "no_surplus_zone"
                                else:
                                    debug_reason = "no_eligible_idle_from_surplus"
                        else:
                            if policy == "CG":
                                debug_reason = "move_cap_zero"

                    if policy == "CG" and args.cgated_debug_file:
                        shortage_text = "|".join([f"{z}:{round(shortage[z],3)}" for z in zones])
                        idle_text = "|".join([f"{z}:{idle_by_zone[z]}" for z in zones])
                        deficits_text = "|".join(active_deficits)
                        surplus_text = "|".join([z for z in zones if (idle_by_zone[z] - desired[z]) > 0])
                        cgated_debug_rows.append({
                            "time": sim_time,
                            "idle_total": idle_total,
                            "idle_by_zone": idle_text,
                            "shortage_by_zone": shortage_text,
                            "active_deficits": deficits_text,
                            "surplus_zones": surplus_text,
                            "cap_share": cap_share,
                            "cap_after_intensity": move_cap,
                            "moved_now": moved_now,
                            "reason_no_move": debug_reason if moved_now == 0 else "",
                            "min_shortage": min_shortage,
                        })

            step_rows.append({
                "time": sim_time,
                "open_queue": len(open_queue),
                "served": served,
                "assigned": assigned,
                "idle_total": len([1 for v in vehicles.values() if v["status"] == "idle"]),
                "serving_total": len([1 for v in vehicles.values() if v["status"] == "serving"]),
                "known_vehicle_count": len(vehicles),
            })

    traci.close()

    trip_n, avg_d, avg_w, avg_t = parse_tripinfo(tripinfo_file)
    idle_snapshots = [r["idle_total"] for r in step_rows]
    max_idle = max(idle_snapshots) if idle_snapshots else 0
    min_idle = min(idle_snapshots) if idle_snapshots else 0

    with open(policy_log, "w", encoding="utf-8", newline="") as f:
        fields = ["time", "vehicle_id", "request_id", "origin_zone", "destination_zone", "action", "status", "reason"]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for row in log_rows:
            w.writerow(row)

    if policy == "CG" and args.cgated_debug_file:
        with open(args.cgated_debug_file, "w", encoding="utf-8", newline="") as f:
            fields = [
                "time",
                "idle_total",
                "idle_by_zone",
                "shortage_by_zone",
                "active_deficits",
                "surplus_zones",
                "cap_share",
                "cap_after_intensity",
                "moved_now",
                "reason_no_move",
                "min_shortage",
            ]
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            for row in cgated_debug_rows:
                w.writerow(row)

    summary_ts = datetime.now().isoformat(timespec='seconds')

    lines = []
    lines.append("persistent fleet policy summary")
    lines.append("")
    lines.append("provenance")
    lines.append(f"summary_generation_timestamp={summary_ts}")
    lines.append(f"policy={policy}")
    lines.append(f"request_file={args.request_file}")
    lines.append(f"request_scale={request_scale}")
    lines.append(f"seed={args.seed}")
    lines.append(f"fleet_size={args.fleet_size}")
    lines.append(f"decision_interval={args.decision_interval}")
    lines.append(f"same_zone_candidate_cap={args.same_zone_candidate_cap}")
    lines.append(f"global_candidate_cap={args.global_candidate_cap}")
    lines.append(f"rebalance_min_shortage={args.rebalance_min_shortage}")
    lines.append(f"rebalance_shortage_threshold={args.rebalance_shortage_threshold}")
    lines.append(f"rebalance_intensity_scale={args.rebalance_intensity_scale}")
    lines.append(f"max_rebalance_share={args.max_rebalance_share}")
    lines.append(f"max_rebalance_count={args.max_rebalance_count}")
    lines.append(f"network_file={network_file}")
    lines.append(f"request_edge_columns_used={'yes' if request_edge_columns_used else 'no'}")
    lines.append(f"statistics_output_enabled={'yes' if statistics_output_enabled else 'no'}")
    lines.append(f"statistics_file={stats_file if statistics_output_enabled else ''}")
    lines.append(f"summary_xml_file={summary_xml}")
    lines.append(f"tripinfo_file={tripinfo_file}")
    lines.append(f"policy_log_file={policy_log}")
    lines.append(f"run_log_file={run_log}")
    lines.append(f"stage_summary_file={stage1_txt}")
    lines.append(f"output_prefix={prefix}")
    lines.append("")
    lines.append("metrics")
    lines.append(f"timestamp={summary_ts}")
    lines.append(f"fleet_size_configured={args.fleet_size}")
    lines.append(f"fleet_size_initialized={fleet_init_count}")
    lines.append(f"total_requests={len(requests)}")
    lines.append(f"requests_released={req_idx}")
    lines.append(f"requests_assigned={assigned}")
    lines.append(f"requests_served={served}")
    lines.append(f"requests_waiting_end={len(open_queue)}")
    lines.append(f"requests_unserved_proxy={max(0, len(requests)-served)}")
    lines.append(f"no_vehicle_events={no_vehicle}")
    lines.append(f"no_path_events={no_path}")
    lines.append(f"dropped_serving_vehicles={dropped}")
    lines.append(f"rebalance_moves={rebalance_moves}")
    lines.append("")
    lines.append("trip_metrics")
    lines.append(f"tripinfo_count={trip_n}")
    lines.append(f"avg_trip_duration={round(avg_d,6)}")
    lines.append(f"avg_waiting_time={round(avg_w,6)}")
    lines.append(f"avg_time_loss={round(avg_t,6)}")
    lines.append("")
    lines.append("idle_existence_check")
    lines.append(f"idle_min_snapshot={min_idle}")
    lines.append(f"idle_max_snapshot={max_idle}")
    lines.append(f"idle_exists_meaningfully={'yes' if max_idle>0 else 'no'}")
    lines.append("")
    lines.append("assignment_rule")
    lines.append("zone-first then nearest travel-time among idle vehicles")
    lines.append(f"same_zone_candidate_cap={args.same_zone_candidate_cap}")
    lines.append(f"global_candidate_cap={args.global_candidate_cap}")
    if policy == "A":
        lines.append("no rebalancing actions in policy A")
    elif policy == "B":
        lines.append("policy B enabled: idle-only demand-gap rebalancing")
        lines.append(f"max_rebalance_share={args.max_rebalance_share}")
        lines.append(f"max_rebalance_count={args.max_rebalance_count}")
    elif policy == "C":
        lines.append("policy C enabled: idle demand-share balancing rebalancing")
        lines.append(f"max_rebalance_share={args.max_rebalance_share}")
        lines.append(f"max_rebalance_count={args.max_rebalance_count}")
    else:
        lines.append("policy CG enabled: gated idle demand-share balancing rebalancing")
        lines.append(f"max_rebalance_share={args.max_rebalance_share}")
        lines.append(f"max_rebalance_count={args.max_rebalance_count}")
        lines.append(f"rebalance_shortage_threshold={args.rebalance_shortage_threshold}")
        lines.append(f"rebalance_min_shortage={args.rebalance_min_shortage}")
        lines.append(f"rebalance_intensity_scale={args.rebalance_intensity_scale}")
    with open(summary_txt, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    ready_for_b = "yes"
    if served < 100 or (len(requests) > 0 and served / len(requests) < 0.01):
        ready_for_b = "no"

    stage_lines = []
    stage_lines.append("persistent fleet stage1 summary")
    stage_lines.append("")
    stage_lines.append(f"summary_generation_timestamp={summary_ts}")
    stage_lines.append(f"policy={policy}")
    stage_lines.append(f"request_file={args.request_file}")
    stage_lines.append(f"request_scale={request_scale}")
    stage_lines.append(f"seed={args.seed}")
    stage_lines.append(f"decision_interval={args.decision_interval}")
    stage_lines.append("implemented_components=request_stream_builder,persistent_vehicle_initializer,dispatch,rebalancing_policy")
    stage_lines.append(f"fleet_size={args.fleet_size}")
    stage_lines.append(f"total_requests={len(requests)}")
    stage_lines.append(f"served_requests={served}")
    stage_lines.append(f"waiting_end={len(open_queue)}")
    stage_lines.append(f"idle_exists_meaningfully={'yes' if max_idle>0 else 'no'}")
    stage_lines.append(f"ready_for_policy_B={ready_for_b}")
    with open(stage1_txt, "w", encoding="utf-8") as f:
        f.write("\n".join(stage_lines) + "\n")

    with open(run_log, "w", encoding="utf-8") as f:
        f.write("persistent fleet run log\n")
        f.write("sumo_command=" + " ".join(cmd) + "\n")
        f.write(f"policy={policy}\n")
        f.write(f"fleet_size={args.fleet_size}\n")
        f.write(f"decision_interval={args.decision_interval}\n")
        f.write(f"same_zone_candidate_cap={args.same_zone_candidate_cap}\n")
        f.write(f"global_candidate_cap={args.global_candidate_cap}\n")
        f.write(f"seed={args.seed}\n")
        f.write(f"request_scale={request_scale}\n")
        f.write(f"network_file={network_file}\n")
        f.write(f"request_file={args.request_file}\n")
        f.write(f"request_edge_columns_used={'yes' if request_edge_columns_used else 'no'}\n")
        f.write(f"statistics_output_enabled={'yes' if statistics_output_enabled else 'no'}\n")
        f.write(f"max_rebalance_share={args.max_rebalance_share}\n")
        f.write(f"max_rebalance_count={args.max_rebalance_count}\n")
        f.write(f"rebalance_shortage_threshold={args.rebalance_shortage_threshold}\n")
        f.write(f"rebalance_min_shortage={args.rebalance_min_shortage}\n")
        f.write(f"rebalance_intensity_scale={args.rebalance_intensity_scale}\n")
        f.write(f"requests_total={len(requests)}\n")
        f.write(f"served={served}\n")
        f.write(f"queue_end={len(open_queue)}\n")
        f.write(f"rebalance_moves={rebalance_moves}\n")

    print("policy_run=success")
    print("policy=" + policy)
    print("fleet_size=" + str(args.fleet_size))
    print("request_stream=" + args.request_file)
    print("request_scale=" + request_scale)
    print("total_requests=" + str(len(requests)))
    print("requests_served=" + str(served))
    print("requests_waiting_end=" + str(len(open_queue)))
    print("idle_exists_meaningfully=" + ("yes" if max_idle > 0 else "no"))
    print("rebalance_moves=" + str(rebalance_moves))
    print("summary_txt=" + summary_txt)
    print("stage1_summary=" + stage1_txt)
    print("policy_log=" + policy_log)
    print("tripinfo=" + tripinfo_file)
    print("statistics=" + stats_file)


if __name__ == "__main__":
    main()
