import os
import csv
import subprocess
import xml.etree.ElementTree as ET
from collections import defaultdict

project_dir = r"E:\project_sakif_chicago"
out_dir = os.path.join(project_dir, "output")
runner = os.path.join(project_dir, "scripts", "run_persistent_fleet_experiment.py")
request_file = os.path.join(project_dir, "data", "compact4_request_stream_s0p005.csv")

policies = ["A", "B", "C"]
seeds = [11, 22]

result_csv = os.path.join(out_dir, "policy_repeatability_results.csv")
summary_txt = os.path.join(out_dir, "policy_repeatability_summary.txt")


def fnum(v):
    try:
        return float(v)
    except Exception:
        return 0.0


def parse_summary(path):
    d = {}
    if not os.path.exists(path):
        return d
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            s = line.strip()
            if "=" in s:
                k, v = s.split("=", 1)
                d[k.strip()] = v.strip()
    return d


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


def run_one(policy, seed):
    tag = f"repeat_{policy}_seed{seed}"
    cmd = [
        "python", runner,
        "--policy", policy,
        "--fleet-size", "300",
        "--decision-interval", "15",
        "--same-zone-candidate-cap", "15",
        "--global-candidate-cap", "15",
        "--max-rebalance-share", "0.15",
        "--max-rebalance-count", "25",
        "--request-file", request_file,
        "--end-time", "86400",
        "--seed", str(seed),
        "--output-prefix", tag,
        "--stage-summary-file", os.path.join(out_dir, f"{tag}_framework_summary.txt"),
    ]
    p = subprocess.run(cmd, capture_output=True, text=True)

    summary_path = os.path.join(out_dir, f"{tag}_summary.txt")
    stats_path = os.path.join(out_dir, f"{tag}_statistics.xml")

    d = parse_summary(summary_path)
    tele, col = parse_stats(stats_path)

    total = int(fnum(d.get("total_requests", "0")))
    assigned = int(fnum(d.get("requests_assigned", "0")))
    served = int(fnum(d.get("requests_served", "0")))
    waiting = int(fnum(d.get("requests_waiting_end", "0")))
    served_frac = (served / total) if total > 0 else 0.0

    return {
        "policy": policy,
        "seed": seed,
        "total_requests": total,
        "requests_assigned": assigned,
        "requests_served": served,
        "requests_waiting_end": waiting,
        "served_fraction": round(served_frac, 6),
        "teleports": tele,
        "collisions": col,
        "run_return_code": p.returncode,
        "output_prefix": tag,
    }


def main():
    rows = []
    for seed in seeds:
        for policy in policies:
            row = run_one(policy, seed)
            rows.append(row)
            print(
                f"done policy={policy} seed={seed} served={row['requests_served']} "
                f"waiting={row['requests_waiting_end']} served_fraction={row['served_fraction']} "
                f"teleports={row['teleports']} collisions={row['collisions']}"
            )

    os.makedirs(out_dir, exist_ok=True)
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
            "run_return_code",
            "output_prefix",
        ]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)

    valid = [r for r in rows if r["run_return_code"] == 0]
    by_seed = defaultdict(dict)
    for r in valid:
        by_seed[r["seed"]][r["policy"]] = r

    stable = "yes"
    for seed in seeds:
        s = by_seed.get(seed, {})
        if not ("A" in s and "B" in s and "C" in s):
            stable = "no"
            continue
        if not (s["A"]["requests_served"] < s["B"]["requests_served"] < s["C"]["requests_served"]):
            stable = "no"

    avg = {}
    for p in policies:
        prs = [r for r in valid if r["policy"] == p]
        if prs:
            avg[p] = {
                "served": sum(r["requests_served"] for r in prs) / len(prs),
                "waiting": sum(r["requests_waiting_end"] for r in prs) / len(prs),
                "served_fraction": sum(r["served_fraction"] for r in prs) / len(prs),
                "teleports": sum(r["teleports"] for r in prs) / len(prs),
                "collisions": sum(r["collisions"] for r in prs) / len(prs),
            }

    lines = []
    lines.append("policy repeatability summary")
    lines.append("")
    lines.append("frozen_operating_point")
    lines.append("fleet_size=300")
    lines.append("dispatch_interval=15")
    lines.append("request_scale=0.005")
    lines.append("same_zone_candidate_cap=15")
    lines.append("global_candidate_cap=15")
    lines.append("max_rebalance_share=0.15")
    lines.append("max_rebalance_count=25")
    lines.append(f"seeds={seeds}")
    lines.append("")
    for r in valid:
        lines.append(
            f"policy={r['policy']},seed={r['seed']},total={r['total_requests']},"
            f"assigned={r['requests_assigned']},served={r['requests_served']},"
            f"waiting={r['requests_waiting_end']},served_fraction={r['served_fraction']},"
            f"teleports={r['teleports']},collisions={r['collisions']}"
        )
    lines.append("")
    for p in policies:
        if p in avg:
            lines.append(
                f"avg_{p}:served={round(avg[p]['served'],3)},"
                f"waiting={round(avg[p]['waiting'],3)},"
                f"served_fraction={round(avg[p]['served_fraction'],6)},"
                f"teleports={round(avg[p]['teleports'],3)},"
                f"collisions={round(avg[p]['collisions'],3)}"
            )
    lines.append("")
    lines.append(f"ranking_A_lt_B_lt_C_stable={stable}")
    lines.append(f"freeze_policy_C={'yes' if stable == 'yes' else 'no'}")
    lines.append(f"ready_for_writeup={'yes' if stable == 'yes' else 'no'}")

    with open(summary_txt, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print("results_csv=" + result_csv)
    print("summary_txt=" + summary_txt)


if __name__ == "__main__":
    main()
