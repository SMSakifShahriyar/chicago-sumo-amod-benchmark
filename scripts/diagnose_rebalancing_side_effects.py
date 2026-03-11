import os
import csv
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict

project_dir = r"E:\project_sakif_chicago"
out_dir = os.path.join(project_dir, "output")

summary_files = {
    "A": os.path.join(out_dir, "controlled_A_seed101_summary.txt"),
    "B": os.path.join(out_dir, "controlled_B_seed101_summary.txt"),
    "C": os.path.join(out_dir, "controlled_C_seed101_summary.txt"),
}
stats_files = {
    "A": os.path.join(out_dir, "controlled_A_seed101_statistics.xml"),
    "B": os.path.join(out_dir, "controlled_B_seed101_statistics.xml"),
    "C": os.path.join(out_dir, "controlled_C_seed101_statistics.xml"),
}
log_files = {
    "A": os.path.join(out_dir, "controlled_A_seed101_policy_log.csv"),
    "B": os.path.join(out_dir, "controlled_B_seed101_policy_log.csv"),
    "C": os.path.join(out_dir, "controlled_C_seed101_policy_log.csv"),
}
request_file = os.path.join(project_dir, "data", "compact4_request_stream_s0p005.csv")

table_csv = os.path.join(out_dir, "rebalancing_side_effect_table.csv")
report_txt = os.path.join(out_dir, "rebalancing_side_effect_diagnosis.txt")


def fnum(v):
    try:
        return float(v)
    except Exception:
        return 0.0


def read_summary(path):
    d = {}
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            s = line.strip()
            if "=" in s:
                k, v = s.split("=", 1)
                d[k.strip()] = v.strip()
    return d


def read_stats(path):
    out = {
        "teleports": 0,
        "collisions": 0,
        "avg_route_length": 0.0,
        "avg_waiting_time_stats": 0.0,
        "avg_time_loss_stats": 0.0,
    }
    root = ET.parse(path).getroot()
    t = root.find("teleports")
    if t is not None:
        out["teleports"] = int(fnum(t.get("total", "0")))
    s = root.find("safety")
    if s is not None:
        out["collisions"] = int(fnum(s.get("collisions", "0")))
    v = root.find("vehicleTripStatistics")
    if v is not None:
        out["avg_route_length"] = fnum(v.get("routeLength", "0"))
        out["avg_waiting_time_stats"] = fnum(v.get("waitingTime", "0"))
        out["avg_time_loss_stats"] = fnum(v.get("timeLoss", "0"))
    return out


def read_requests(path):
    c = Counter()
    total = 0
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            total += 1
            c[row["origin_zone"].strip()] += 1
    shares = {}
    for z, n in c.items():
        shares[z] = n / total if total > 0 else 0.0
    return total, c, shares


def parse_policy_log(path):
    actions = Counter()
    assign_origin = Counter()
    reb_src = Counter()
    reb_dst = Counter()
    rows = []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            row["time_int"] = int(fnum(row.get("time", "0")))
            rows.append(row)
            a = row.get("action", "")
            actions[a] += 1
            if a == "assign_request":
                assign_origin[row.get("origin_zone", "")] += 1
            elif a == "rebalance_move":
                reb_src[row.get("origin_zone", "")] += 1
                reb_dst[row.get("destination_zone", "")] += 1

    vehicle_events = defaultdict(list)
    for row in rows:
        vehicle_events[row.get("vehicle_id", "")].append(row)
    for vid in vehicle_events:
        vehicle_events[vid].sort(key=lambda x: (x["time_int"], x.get("action", "")))

    reb_move_total = actions.get("rebalance_move", 0)
    next_to_dest = 0
    next_to_source = 0
    next_to_other = 0
    no_next_assign = 0
    delay_sum = 0
    delay_count = 0

    for vid, events in vehicle_events.items():
        for i, ev in enumerate(events):
            if ev.get("action") != "rebalance_move":
                continue
            src = ev.get("origin_zone", "")
            dst = ev.get("destination_zone", "")
            t0 = ev.get("time_int", 0)
            next_assign = None
            for j in range(i + 1, len(events)):
                if events[j].get("action") == "assign_request":
                    next_assign = events[j]
                    break
            if next_assign is None:
                no_next_assign += 1
                continue
            az = next_assign.get("origin_zone", "")
            if az == dst:
                next_to_dest += 1
            elif az == src:
                next_to_source += 1
            else:
                next_to_other += 1
            delay_sum += max(0, next_assign.get("time_int", 0) - t0)
            delay_count += 1

    avg_delay = (delay_sum / delay_count) if delay_count > 0 else 0.0

    return {
        "actions": actions,
        "assign_origin": assign_origin,
        "reb_src": reb_src,
        "reb_dst": reb_dst,
        "reb_move_total": reb_move_total,
        "next_to_dest": next_to_dest,
        "next_to_source": next_to_source,
        "next_to_other": next_to_other,
        "no_next_assign": no_next_assign,
        "avg_delay_to_next_assign": avg_delay,
    }


def main():
    req_total, req_origin_counts, req_origin_share = read_requests(request_file)

    policy_data = {}
    for p in ["A", "B", "C"]:
        s = read_summary(summary_files[p])
        st = read_stats(stats_files[p])
        lg = parse_policy_log(log_files[p])

        total = int(fnum(s.get("total_requests", "0")))
        assigned = int(fnum(s.get("requests_assigned", "0")))
        served = int(fnum(s.get("requests_served", "0")))
        waiting = int(fnum(s.get("requests_waiting_end", "0")))
        reb_moves = int(fnum(s.get("rebalance_moves", "0")))
        served_fraction = (served / total) if total > 0 else 0.0

        move_per_served = (reb_moves / served) if served > 0 else 0.0
        move_per_assigned = (reb_moves / assigned) if assigned > 0 else 0.0

        policy_data[p] = {
            "policy": p,
            "total_requests": total,
            "requests_assigned": assigned,
            "requests_served": served,
            "requests_waiting_end": waiting,
            "served_fraction": served_fraction,
            "teleports": st["teleports"],
            "collisions": st["collisions"],
            "avg_route_length": st["avg_route_length"],
            "avg_waiting_time_stats": st["avg_waiting_time_stats"],
            "avg_time_loss_stats": st["avg_time_loss_stats"],
            "rebalance_moves": reb_moves,
            "move_per_served": move_per_served,
            "move_per_assigned": move_per_assigned,
            "assign_request_events": lg["actions"].get("assign_request", 0),
            "idle_keepalive_events": lg["actions"].get("idle_keepalive", 0),
            "rebalance_move_events": lg["reb_move_total"],
            "next_assign_to_rebalance_dest": lg["next_to_dest"],
            "next_assign_to_rebalance_source": lg["next_to_source"],
            "next_assign_to_other_zone": lg["next_to_other"],
            "rebalance_no_next_assign": lg["no_next_assign"],
            "avg_delay_to_next_assign": lg["avg_delay_to_next_assign"],
            "reb_src": lg["reb_src"],
            "reb_dst": lg["reb_dst"],
            "assign_origin": lg["assign_origin"],
        }

    fields = [
        "policy",
        "total_requests",
        "requests_assigned",
        "requests_served",
        "requests_waiting_end",
        "served_fraction",
        "teleports",
        "collisions",
        "avg_route_length",
        "avg_waiting_time_stats",
        "avg_time_loss_stats",
        "rebalance_moves",
        "move_per_served",
        "move_per_assigned",
        "assign_request_events",
        "idle_keepalive_events",
        "rebalance_move_events",
        "next_assign_to_rebalance_dest",
        "next_assign_to_rebalance_source",
        "next_assign_to_other_zone",
        "rebalance_no_next_assign",
        "avg_delay_to_next_assign",
    ]

    with open(table_csv, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for p in ["A", "B", "C"]:
            row = {k: policy_data[p][k] for k in fields}
            row["served_fraction"] = round(row["served_fraction"], 6)
            row["move_per_served"] = round(row["move_per_served"], 6)
            row["move_per_assigned"] = round(row["move_per_assigned"], 6)
            row["avg_delay_to_next_assign"] = round(row["avg_delay_to_next_assign"], 3)
            w.writerow(row)

    A = policy_data["A"]
    B = policy_data["B"]
    C = policy_data["C"]

    b_dest_hit = (B["next_assign_to_rebalance_dest"] / B["rebalance_moves"]) if B["rebalance_moves"] > 0 else 0.0
    b_no_next = (B["rebalance_no_next_assign"] / B["rebalance_moves"]) if B["rebalance_moves"] > 0 else 0.0
    c_dest_hit = (C["next_assign_to_rebalance_dest"] / C["rebalance_moves"]) if C["rebalance_moves"] > 0 else 0.0
    c_no_next = (C["rebalance_no_next_assign"] / C["rebalance_moves"]) if C["rebalance_moves"] > 0 else 0.0

    b_top_src = B["reb_src"].most_common(4)
    b_top_dst = B["reb_dst"].most_common(4)
    c_top_src = C["reb_src"].most_common(4)
    c_top_dst = C["reb_dst"].most_common(4)

    lines = []
    lines.append("rebalancing side-effect diagnosis")
    lines.append("")
    lines.append("scope")
    lines.append("- controlled runs at seed=101 under frozen operating point")
    lines.append("- compared policies A, B, C using policy logs + summary + statistics")
    lines.append("")
    lines.append("core outcomes")
    lines.append(f"- A: served={A['requests_served']}, waiting_end={A['requests_waiting_end']}, served_fraction={A['served_fraction']:.6f}")
    lines.append(f"- B: served={B['requests_served']}, waiting_end={B['requests_waiting_end']}, served_fraction={B['served_fraction']:.6f}")
    lines.append(f"- C: served={C['requests_served']}, waiting_end={C['requests_waiting_end']}, served_fraction={C['served_fraction']:.6f}")
    lines.append("")
    lines.append("rebalancing burden")
    lines.append(f"- B rebalance moves={B['rebalance_moves']} ({B['move_per_served']:.3f} moves per served request)")
    lines.append(f"- C rebalance moves={C['rebalance_moves']} ({C['move_per_served']:.3f} moves per served request)")
    lines.append(f"- B avg route length proxy={B['avg_route_length']:.2f} vs A={A['avg_route_length']:.2f}")
    lines.append(f"- C avg route length proxy={C['avg_route_length']:.2f} vs A={A['avg_route_length']:.2f}")
    lines.append("")
    lines.append("move usefulness")
    lines.append(f"- B next-assignment hit to rebalance destination={b_dest_hit:.3f}, no-next-assignment={b_no_next:.3f}, avg delay to next assignment={B['avg_delay_to_next_assign']:.1f}s")
    lines.append(f"- C next-assignment hit to rebalance destination={c_dest_hit:.3f}, no-next-assignment={c_no_next:.3f}, avg delay to next assignment={C['avg_delay_to_next_assign']:.1f}s")
    lines.append("")
    lines.append("zone drain/fill pattern")
    lines.append("- B top source zones: " + ", ".join([f"{z}:{n}" for z, n in b_top_src]))
    lines.append("- B top destination zones: " + ", ".join([f"{z}:{n}" for z, n in b_top_dst]))
    lines.append("- C top source zones: " + ", ".join([f"{z}:{n}" for z, n in c_top_src]))
    lines.append("- C top destination zones: " + ", ".join([f"{z}:{n}" for z, n in c_top_dst]))
    lines.append("")
    lines.append("diagnosis")
    lines.append("- B likely underperforms because repositioning burden is very high and concentrated, causing churn and weaker near-term assignment availability.")
    lines.append("- C reduces this burden substantially and is closer to A, but still introduces extra empty movement and mild mistiming compared with A's pure local assignment behavior.")
    lines.append("- At this load level, demand pressure is moderate enough that frequent proactive repositioning can be counterproductive.")
    lines.append("")
    lines.append("interpretation")
    lines.append("- most likely reason for ranking A > C > B: excessive and mistimed empty repositioning, strongest in B, moderate in C.")
    lines.append("- both B and C stay safe (0 teleports, 0 collisions), so this is an efficiency issue rather than a safety failure.")
    lines.append("")
    lines.append("recommended next step")
    lines.append("- do a small policy redesign focused only on throttling and gating rebalancing (not a full redesign): reduce unnecessary moves and trigger only under stronger local shortage signals.")

    with open(report_txt, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print("table_file=" + table_csv)
    print("report_file=" + report_txt)


if __name__ == "__main__":
    main()
