import os
import csv
import subprocess
import xml.etree.ElementTree as ET

project_dir = r"E:\project_sakif_chicago"
runner = os.path.join(project_dir, "scripts", "run_persistent_fleet_experiment.py")
out_dir = os.path.join(project_dir, "output")
request_file = os.path.join(project_dir, "data", "compact4_request_stream_s0p005.csv")

shares = [0.10, 0.15, 0.20]
counts = [10, 25, 40]

result_csv = os.path.join(out_dir, "policyB_parameter_results.csv")
summary_txt = os.path.join(out_dir, "policyB_parameter_summary.txt")


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


def run_one(share, count):
    tag = f"persistent_B_scale_0p005_s{str(share).replace('.', 'p')}_c{count}"
    cmd = [
        "python", runner,
        "--policy", "B",
        "--fleet-size", "300",
        "--decision-interval", "15",
        "--same-zone-candidate-cap", "15",
        "--global-candidate-cap", "15",
        "--max-rebalance-share", str(share),
        "--max-rebalance-count", str(count),
        "--request-file", request_file,
        "--end-time", "86400",
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
    rebalance_moves = int(fnum(d.get("rebalance_moves", "0")))
    served_frac = (served / total) if total > 0 else 0.0

    return {
        "max_rebalance_share": share,
        "max_rebalance_count": count,
        "total_requests": total,
        "requests_assigned": assigned,
        "requests_served": served,
        "requests_waiting_end": waiting,
        "served_fraction": round(served_frac, 6),
        "teleports": tele,
        "collisions": col,
        "rebalance_moves": rebalance_moves,
        "run_return_code": p.returncode,
        "output_prefix": tag,
    }


def load_baseline(path_summary, path_stats):
    d = parse_summary(path_summary)
    tele, col = parse_stats(path_stats)
    total = int(fnum(d.get("total_requests", "0")))
    served = int(fnum(d.get("requests_served", "0")))
    waiting = int(fnum(d.get("requests_waiting_end", "0")))
    served_frac = (served / total) if total > 0 else 0.0
    return {
        "total_requests": total,
        "requests_served": served,
        "requests_waiting_end": waiting,
        "served_fraction": served_frac,
        "teleports": tele,
        "collisions": col,
    }


def main():
    rows = []
    for share in shares:
        for count in counts:
            row = run_one(share, count)
            rows.append(row)
            print(
                f"done share={share} count={count} served={row['requests_served']} "
                f"waiting={row['requests_waiting_end']} served_fraction={row['served_fraction']} "
                f"teleports={row['teleports']} collisions={row['collisions']} moves={row['rebalance_moves']}"
            )

    os.makedirs(out_dir, exist_ok=True)
    with open(result_csv, "w", encoding="utf-8", newline="") as f:
        fields = [
            "max_rebalance_share",
            "max_rebalance_count",
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

    A = load_baseline(
        os.path.join(out_dir, "persistent_A_scale_0p005_summary.txt"),
        os.path.join(out_dir, "persistent_A_scale_0p005_statistics.xml"),
    )
    B0 = load_baseline(
        os.path.join(out_dir, "persistent_B_scale_0p005_summary.txt"),
        os.path.join(out_dir, "persistent_B_scale_0p005_statistics.xml"),
    )

    valid = [r for r in rows if r["run_return_code"] == 0]
    safe = [r for r in valid if r["teleports"] == 0 and r["collisions"] == 0]
    ranked_pool = safe if safe else valid
    best = None
    if ranked_pool:
        best = sorted(
            ranked_pool,
            key=lambda r: (r["requests_served"], -r["requests_waiting_end"], r["served_fraction"]),
            reverse=True,
        )[0]

    lines = []
    lines.append("policy B parameter sweep summary")
    lines.append("")
    lines.append("frozen_operating_point")
    lines.append("fleet_size=300")
    lines.append("dispatch_interval=15")
    lines.append("request_scale=0.005")
    lines.append("same_zone_candidate_cap=15")
    lines.append("global_candidate_cap=15")
    lines.append("")
    lines.append(f"tested_shares={shares}")
    lines.append(f"tested_counts={counts}")
    lines.append("")
    lines.append("baseline_A")
    for k, v in A.items():
        if k == "served_fraction":
            lines.append(f"{k}={round(v,6)}")
        else:
            lines.append(f"{k}={v}")
    lines.append("")
    lines.append("current_default_B")
    for k, v in B0.items():
        if k == "served_fraction":
            lines.append(f"{k}={round(v,6)}")
        else:
            lines.append(f"{k}={v}")
    lines.append("")
    for r in valid:
        lines.append(
            f"share={r['max_rebalance_share']},count={r['max_rebalance_count']},"
            f"assigned={r['requests_assigned']},served={r['requests_served']},"
            f"waiting={r['requests_waiting_end']},served_fraction={r['served_fraction']},"
            f"teleports={r['teleports']},collisions={r['collisions']},moves={r['rebalance_moves']}"
        )

    lines.append("")
    if best is not None:
        lines.append("recommended_setting")
        lines.append(f"max_rebalance_share={best['max_rebalance_share']}")
        lines.append(f"max_rebalance_count={best['max_rebalance_count']}")
        lines.append(f"served={best['requests_served']}")
        lines.append(f"waiting_end={best['requests_waiting_end']}")
        lines.append(f"served_fraction={best['served_fraction']}")
        lines.append(f"teleports={best['teleports']}")
        lines.append(f"collisions={best['collisions']}")

        default_improved = "no"
        if (
            best["requests_served"] > B0["requests_served"]
            and best["requests_waiting_end"] <= B0["requests_waiting_end"]
            and best["teleports"] <= B0["teleports"]
            and best["collisions"] <= B0["collisions"]
        ):
            default_improved = "yes"
        lines.append(f"better_than_current_default_B={default_improved}")
    else:
        lines.append("recommended_setting=none")

    with open(summary_txt, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print("results_csv=" + result_csv)
    print("summary_txt=" + summary_txt)


if __name__ == "__main__":
    main()
