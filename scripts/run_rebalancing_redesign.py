import os
import csv
import subprocess
import xml.etree.ElementTree as ET
from collections import defaultdict

project_dir = r"E:\project_sakif_chicago"
out_dir = os.path.join(project_dir, "output")
runner = os.path.join(project_dir, "scripts", "run_persistent_fleet_experiment.py")
request_file = os.path.join(project_dir, "data", "compact4_request_stream_s0p005.csv")

seed = 101
cg_prefix = "persistent_C_gated_scale_0p005_seed101"

result_csv = os.path.join(out_dir, "rebalancing_redesign_results.csv")
summary_txt = os.path.join(out_dir, "rebalancing_redesign_summary.txt")


def fnum(v):
    try:
        return float(v)
    except Exception:
        return 0.0


def parse_summary(path):
    d = {}
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            s = line.strip()
            if "=" in s:
                k, v = s.split("=", 1)
                d[k.strip()] = v.strip()
    total = int(fnum(d.get("total_requests", "0")))
    assigned = int(fnum(d.get("requests_assigned", "0")))
    served = int(fnum(d.get("requests_served", "0")))
    waiting = int(fnum(d.get("requests_waiting_end", "0")))
    reb_moves = int(fnum(d.get("rebalance_moves", "0")))
    idle_exists = d.get("idle_exists_meaningfully", "no")
    served_fraction = (served / total) if total > 0 else 0.0
    return {
        "total_requests": total,
        "requests_assigned": assigned,
        "requests_served": served,
        "requests_waiting_end": waiting,
        "served_fraction": served_fraction,
        "rebalance_moves": reb_moves,
        "idle_exists": idle_exists,
    }


def parse_stats(path):
    tele = 0
    col = 0
    if os.path.exists(path):
        root = ET.parse(path).getroot()
        t = root.find("teleports")
        if t is not None:
            tele = int(fnum(t.get("total", "0")))
        s = root.find("safety")
        if s is not None:
            col = int(fnum(s.get("collisions", "0")))
    return tele, col


def parse_dest_hit(policy_log):
    rows = []
    with open(policy_log, "r", encoding="utf-8-sig", newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            row["time_int"] = int(fnum(row.get("time", "0")))
            rows.append(row)

    by_vid = defaultdict(list)
    for row in rows:
        by_vid[row.get("vehicle_id", "")].append(row)
    for vid in by_vid:
        by_vid[vid].sort(key=lambda x: (x["time_int"], x.get("action", "")))

    reb_moves = 0
    hit_dest = 0
    no_next = 0
    for vid, evs in by_vid.items():
        for i, ev in enumerate(evs):
            if ev.get("action") != "rebalance_move":
                continue
            reb_moves += 1
            dst = ev.get("destination_zone", "")
            nxt = None
            for j in range(i + 1, len(evs)):
                if evs[j].get("action") == "assign_request":
                    nxt = evs[j]
                    break
            if nxt is None:
                no_next += 1
                continue
            if nxt.get("origin_zone", "") == dst:
                hit_dest += 1

    hit_rate = (hit_dest / reb_moves) if reb_moves > 0 else 0.0
    no_next_rate = (no_next / reb_moves) if reb_moves > 0 else 0.0
    return reb_moves, hit_rate, no_next_rate


def run_cgated():
    cmd = [
        "python", runner,
        "--policy", "CG",
        "--fleet-size", "300",
        "--decision-interval", "15",
        "--same-zone-candidate-cap", "15",
        "--global-candidate-cap", "15",
        "--max-rebalance-share", "0.15",
        "--max-rebalance-count", "25",
        "--rebalance-shortage-threshold", "0.08",
        "--rebalance-min-shortage", "2",
        "--rebalance-intensity-scale", "0.35",
        "--request-file", request_file,
        "--end-time", "86400",
        "--seed", str(seed),
        "--output-prefix", cg_prefix,
        "--stage-summary-file", os.path.join(out_dir, f"{cg_prefix}_framework_summary.txt"),
    ]
    return subprocess.run(cmd, capture_output=True, text=True)


def load_policy(name, summary_path, stats_path, log_path):
    s = parse_summary(summary_path)
    tele, col = parse_stats(stats_path)
    moves, hit_rate, no_next_rate = parse_dest_hit(log_path)
    s["policy"] = name
    s["teleports"] = tele
    s["collisions"] = col
    s["rebalance_moves_log"] = moves
    s["dest_hit_rate"] = hit_rate
    s["no_next_assign_rate"] = no_next_rate
    return s


def main():
    p = run_cgated()
    if p.returncode != 0:
        raise RuntimeError("C_gated run failed")

    A = load_policy(
        "A",
        os.path.join(out_dir, "controlled_A_seed101_summary.txt"),
        os.path.join(out_dir, "controlled_A_seed101_statistics.xml"),
        os.path.join(out_dir, "controlled_A_seed101_policy_log.csv"),
    )
    C = load_policy(
        "C",
        os.path.join(out_dir, "controlled_C_seed101_summary.txt"),
        os.path.join(out_dir, "controlled_C_seed101_statistics.xml"),
        os.path.join(out_dir, "controlled_C_seed101_policy_log.csv"),
    )
    CG = load_policy(
        "C_gated",
        os.path.join(out_dir, f"{cg_prefix}_summary.txt"),
        os.path.join(out_dir, f"{cg_prefix}_statistics.xml"),
        os.path.join(out_dir, f"{cg_prefix}_policy_log.csv"),
    )

    rows = [A, C, CG]
    with open(result_csv, "w", encoding="utf-8", newline="") as f:
        fields = [
            "policy",
            "total_requests",
            "requests_assigned",
            "requests_served",
            "requests_waiting_end",
            "served_fraction",
            "teleports",
            "collisions",
            "rebalance_moves",
            "rebalance_moves_log",
            "dest_hit_rate",
            "no_next_assign_rate",
            "idle_exists",
        ]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            out = dict(r)
            out["served_fraction"] = round(out["served_fraction"], 6)
            out["dest_hit_rate"] = round(out["dest_hit_rate"], 6)
            out["no_next_assign_rate"] = round(out["no_next_assign_rate"], 6)
            w.writerow(out)

    lines = []
    lines.append("rebalancing redesign summary")
    lines.append("")
    lines.append("redesign_rule")
    lines.append("- policy variant: C_gated")
    lines.append("- keep policy C structure (demand-share balancing)")
    lines.append("- trigger only for meaningful deficit: shortage >= max(2, 8% of idle pool)")
    lines.append("- throttle effective move cap with intensity scale 0.35")
    lines.append("")
    for r in rows:
        lines.append(
            f"{r['policy']}: served={r['requests_served']}, waiting_end={r['requests_waiting_end']}, "
            f"served_fraction={r['served_fraction']:.6f}, teleports={r['teleports']}, collisions={r['collisions']}, "
            f"rebalance_moves={r['rebalance_moves']}, dest_hit_rate={r['dest_hit_rate']:.3f}"
        )
    lines.append("")
    lines.append("comparison")
    lines.append(f"C_gated_vs_C_served_delta={CG['requests_served'] - C['requests_served']}")
    lines.append(f"C_gated_vs_C_waiting_delta={CG['requests_waiting_end'] - C['requests_waiting_end']}")
    lines.append(f"C_gated_vs_C_served_fraction_delta={CG['served_fraction'] - C['served_fraction']:.6f}")
    lines.append(f"C_gated_vs_A_served_delta={CG['requests_served'] - A['requests_served']}")
    lines.append(f"C_gated_vs_A_waiting_delta={CG['requests_waiting_end'] - A['requests_waiting_end']}")

    better_than_C = "yes" if (CG['requests_served'] > C['requests_served'] and CG['requests_waiting_end'] < C['requests_waiting_end']) else "no"
    better_than_A = "yes" if (CG['requests_served'] > A['requests_served'] and CG['requests_waiting_end'] < A['requests_waiting_end']) else "no"
    lines.append(f"C_gated_better_than_C={better_than_C}")
    lines.append(f"C_gated_better_than_A={better_than_A}")

    with open(summary_txt, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print("results_csv=" + result_csv)
    print("summary_txt=" + summary_txt)


if __name__ == "__main__":
    main()
