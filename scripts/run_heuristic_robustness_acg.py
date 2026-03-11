import os
import csv
import math
import statistics
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

project_dir = Path(r"E:\project_sakif_chicago")
out_dir = project_dir / "output"
scripts_dir = project_dir / "scripts"
runner = scripts_dir / "run_persistent_fleet_experiment.py"
request_file = project_dir / "data" / "compact4_request_stream_s0p005.csv"

seeds = [101, 202, 303, 404, 505]
policies = ["A", "CG"]

result_csv = out_dir / "heuristic_robustness_acg_results.csv"
summary_txt = out_dir / "heuristic_robustness_acg_summary.txt"


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
    moves = int(fnum(d.get("rebalance_moves", "0")))
    served_fraction = (served / total) if total > 0 else 0.0
    return total, assigned, served, waiting, served_fraction, moves


def parse_stats(path):
    tele = 0
    col = 0
    root = ET.parse(path).getroot()
    t = root.find("teleports")
    if t is not None:
        tele = int(fnum(t.get("total", "0")))
    s = root.find("safety")
    if s is not None:
        col = int(fnum(s.get("collisions", "0")))
    return tele, col


def run_one(policy, seed):
    tag = f"robust_{policy}_s{seed}"
    cmd = [
        "python", str(runner),
        "--policy", policy,
        "--fleet-size", "300",
        "--decision-interval", "15",
        "--same-zone-candidate-cap", "15",
        "--global-candidate-cap", "15",
        "--max-rebalance-share", "0.15",
        "--max-rebalance-count", "25",
        "--rebalance-shortage-threshold", "0.08",
        "--rebalance-min-shortage", "1",
        "--rebalance-intensity-scale", "0.35",
        "--request-file", str(request_file),
        "--end-time", "86400",
        "--seed", str(seed),
        "--output-prefix", tag,
        "--stage-summary-file", str(out_dir / f"{tag}_framework_summary.txt"),
    ]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        return {
            "policy": policy,
            "seed": seed,
            "run_return_code": p.returncode,
        }

    summary_path = out_dir / f"{tag}_summary.txt"
    stats_path = out_dir / f"{tag}_statistics.xml"

    total, assigned, served, waiting, served_fraction, moves = parse_summary(summary_path)
    tele, col = parse_stats(stats_path)
    return {
        "policy": policy,
        "seed": seed,
        "total_requests": total,
        "requests_assigned": assigned,
        "requests_served": served,
        "requests_waiting_end": waiting,
        "served_fraction": round(served_fraction, 6),
        "teleports": tele,
        "collisions": col,
        "rebalance_moves": moves,
        "run_return_code": 0,
        "output_prefix": tag,
    }


def mean_std(vals):
    if not vals:
        return 0.0, 0.0
    if len(vals) == 1:
        return float(vals[0]), 0.0
    return float(statistics.mean(vals)), float(statistics.stdev(vals))


def main():
    rows = []
    for seed in seeds:
        for policy in policies:
            row = run_one(policy, seed)
            rows.append(row)
            if row.get("run_return_code", 1) == 0:
                print(
                    f"done policy={policy} seed={seed} served={row['requests_served']} "
                    f"waiting={row['requests_waiting_end']} served_fraction={row['served_fraction']}"
                )
            else:
                print(f"failed policy={policy} seed={seed} rc={row.get('run_return_code')}")

    with open(result_csv, "w", encoding="utf-8", newline="") as f:
        fields = [
            "policy",
            "seed",
            "total_requests",
            "requests_assigned",
            "requests_served",
            "requests_waiting_end",
            "served_fraction",
            "teleports",
            "collisions",
            "rebalance_moves",
            "run_return_code",
            "output_prefix",
        ]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)

    valid = [r for r in rows if r.get("run_return_code") == 0]
    by_policy = {p: [r for r in valid if r["policy"] == p] for p in policies}

    lines = []
    lines.append("Heuristic Robustness Summary (A vs C_gated fix1)")
    lines.append("")
    lines.append("frozen_operating_point")
    lines.append("fleet_size=300")
    lines.append("dispatch_interval=15")
    lines.append("request_scale=0.005")
    lines.append("candidate_caps=15/15")
    lines.append("seed_list=" + ",".join(str(s) for s in seeds))
    lines.append("")

    for r in valid:
        lines.append(
            f"policy={r['policy']},seed={r['seed']},served={r['requests_served']},"
            f"waiting={r['requests_waiting_end']},served_fraction={r['served_fraction']},"
            f"teleports={r['teleports']},collisions={r['collisions']},moves={r['rebalance_moves']}"
        )

    lines.append("")
    summary = {}
    for p in policies:
        prs = by_policy[p]
        served = [x["requests_served"] for x in prs]
        waiting = [x["requests_waiting_end"] for x in prs]
        frac = [x["served_fraction"] for x in prs]
        tele = [x["teleports"] for x in prs]
        col = [x["collisions"] for x in prs]
        moves = [x["rebalance_moves"] for x in prs]

        s_m, s_sd = mean_std(served)
        w_m, w_sd = mean_std(waiting)
        f_m, f_sd = mean_std(frac)
        t_m, _ = mean_std(tele)
        c_m, _ = mean_std(col)
        m_m, m_sd = mean_std(moves)

        summary[p] = {
            "served_mean": s_m,
            "served_sd": s_sd,
            "waiting_mean": w_m,
            "waiting_sd": w_sd,
            "frac_mean": f_m,
            "frac_sd": f_sd,
            "tele_mean": t_m,
            "col_mean": c_m,
            "moves_mean": m_m,
            "moves_sd": m_sd,
        }

        lines.append(
            f"{p}: served_mean={s_m:.3f} served_sd={s_sd:.3f}, "
            f"waiting_mean={w_m:.3f} waiting_sd={w_sd:.3f}, "
            f"served_fraction_mean={f_m:.6f} served_fraction_sd={f_sd:.6f}, "
            f"teleports_mean={t_m:.3f}, collisions_mean={c_m:.3f}, "
            f"moves_mean={m_m:.3f} moves_sd={m_sd:.3f}"
        )

    lines.append("")
    if "A" in summary and "CG" in summary:
        d_served = summary["CG"]["served_mean"] - summary["A"]["served_mean"]
        d_wait = summary["CG"]["waiting_mean"] - summary["A"]["waiting_mean"]
        d_frac = summary["CG"]["frac_mean"] - summary["A"]["frac_mean"]
        lines.append(f"delta_CG_minus_A_served_mean={d_served:.3f}")
        lines.append(f"delta_CG_minus_A_waiting_mean={d_wait:.3f}")
        lines.append(f"delta_CG_minus_A_served_fraction_mean={d_frac:.6f}")
        cg_better = "yes" if (d_served > 0 and d_wait < 0) else "no"
        lines.append(f"CG_better_than_A_on_mean={cg_better}")

    with open(summary_txt, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(result_csv)
    print(summary_txt)


if __name__ == "__main__":
    main()
