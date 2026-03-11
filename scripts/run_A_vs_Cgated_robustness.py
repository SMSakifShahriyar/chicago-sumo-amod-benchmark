import csv
import statistics
import subprocess
import time
from pathlib import Path
import xml.etree.ElementTree as ET

import matplotlib.pyplot as plt

project_dir = Path(r"E:\project_sakif_chicago")
out_dir = project_dir / "output"
vis_dir = project_dir / "visuals"
scripts_dir = project_dir / "scripts"
runner = scripts_dir / "run_persistent_fleet_experiment.py"

loads = [0.004, 0.005, 0.006]
seeds = [101, 202, 303, 404, 505]
policies = ["A", "CG"]

run_csv = out_dir / "A_vs_Cgated_robustness_runs.csv"
summary_csv = out_dir / "A_vs_Cgated_robustness_summary.csv"
summary_txt = out_dir / "A_vs_Cgated_robustness_summary.txt"
figure_png = vis_dir / "A_vs_Cgated_robustness.png"


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
    served = int(fnum(d.get("requests_served", "0")))
    waiting = int(fnum(d.get("requests_waiting_end", "0")))
    moves = int(fnum(d.get("rebalance_moves", "0")))
    frac = (served / total) if total > 0 else 0.0
    return total, served, waiting, frac, moves


def parse_stats(path):
    tele = 0
    col = 0
    if not path.exists():
        return tele, col
    root = ET.parse(path).getroot()
    t = root.find("teleports")
    if t is not None:
        tele = int(fnum(t.get("total", "0")))
    s = root.find("safety")
    if s is not None:
        col = int(fnum(s.get("collisions", "0")))
    return tele, col


def mean_std(vals):
    if not vals:
        return 0.0, 0.0
    if len(vals) == 1:
        return float(vals[0]), 0.0
    return float(statistics.mean(vals)), float(statistics.stdev(vals))


def load_existing_005(policy, seed):
    tag = f"robust_{policy}_s{seed}"
    sfile = out_dir / f"{tag}_summary.txt"
    xfile = out_dir / f"{tag}_statistics.xml"
    if not sfile.exists():
        return None
    total, served, waiting, frac, moves = parse_summary(sfile)
    tele, col = parse_stats(xfile)
    return {
        "policy": policy,
        "request_scale": 0.005,
        "seed": seed,
        "total_requests": total,
        "requests_served": served,
        "requests_waiting_end": waiting,
        "served_fraction": round(frac, 6),
        "teleports": tele,
        "collisions": col,
        "rebalance_moves": moves,
        "run_return_code": 0,
        "runtime_sec": "",
        "output_prefix": tag,
        "source": "existing_robust_005",
    }


def run_one(policy, request_scale, seed):
    tag_scale = str(request_scale).replace(".", "p")
    tag = f"robmap_{policy}_s{seed}_r{tag_scale}"
    req_file = project_dir / "data" / f"compact4_request_stream_s0p{int(request_scale*1000):03d}.csv"
    if request_scale == 0.004:
        req_file = project_dir / "data" / "compact4_request_stream_s0p04.csv"
    if request_scale == 0.005:
        req_file = project_dir / "data" / "compact4_request_stream_s0p005.csv"
    if request_scale == 0.006:
        req_file = project_dir / "data" / "compact4_request_stream_s0p006.csv"

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
        "--request-file", str(req_file),
        "--end-time", "86400",
        "--seed", str(seed),
        "--output-prefix", tag,
        "--stage-summary-file", str(out_dir / f"{tag}_framework_summary.txt"),
    ]

    t0 = time.time()
    p = subprocess.run(cmd, capture_output=True, text=True)
    runtime = round(time.time() - t0, 3)

    if p.returncode != 0:
        return {
            "policy": policy,
            "request_scale": request_scale,
            "seed": seed,
            "total_requests": "",
            "requests_served": "",
            "requests_waiting_end": "",
            "served_fraction": "",
            "teleports": "",
            "collisions": "",
            "rebalance_moves": "",
            "run_return_code": p.returncode,
            "runtime_sec": runtime,
            "output_prefix": tag,
            "source": "new_run_failed",
        }

    sfile = out_dir / f"{tag}_summary.txt"
    xfile = out_dir / f"{tag}_statistics.xml"
    total, served, waiting, frac, moves = parse_summary(sfile)
    tele, col = parse_stats(xfile)

    return {
        "policy": policy,
        "request_scale": request_scale,
        "seed": seed,
        "total_requests": total,
        "requests_served": served,
        "requests_waiting_end": waiting,
        "served_fraction": round(frac, 6),
        "teleports": tele,
        "collisions": col,
        "rebalance_moves": moves,
        "run_return_code": 0,
        "runtime_sec": runtime,
        "output_prefix": tag,
        "source": "new_run",
    }


def main():
    out_dir.mkdir(parents=True, exist_ok=True)
    vis_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for scale in loads:
        for seed in seeds:
            for policy in policies:
                if scale == 0.005:
                    existing = load_existing_005(policy, seed)
                    if existing is not None:
                        rows.append(existing)
                        print(f"reuse scale={scale} seed={seed} policy={policy} served={existing['requests_served']}")
                        continue
                row = run_one(policy, scale, seed)
                rows.append(row)
                if row.get("run_return_code") == 0:
                    print(
                        f"done scale={scale} seed={seed} policy={policy} "
                        f"served={row['requests_served']} waiting={row['requests_waiting_end']} "
                        f"frac={row['served_fraction']} runtime={row['runtime_sec']}"
                    )
                else:
                    print(f"failed scale={scale} seed={seed} policy={policy} rc={row['run_return_code']}")

    run_fields = [
        "policy", "request_scale", "seed", "total_requests", "requests_served",
        "requests_waiting_end", "served_fraction", "teleports", "collisions",
        "rebalance_moves", "run_return_code", "runtime_sec", "output_prefix", "source"
    ]
    with open(run_csv, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=run_fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)

    valid = [r for r in rows if r.get("run_return_code") == 0]

    sum_rows = []
    for scale in loads:
        for policy in policies:
            grp = [r for r in valid if float(r["request_scale"]) == scale and r["policy"] == policy]
            served = [float(r["requests_served"]) for r in grp]
            waiting = [float(r["requests_waiting_end"]) for r in grp]
            frac = [float(r["served_fraction"]) for r in grp]
            moves = [float(r["rebalance_moves"]) for r in grp]
            sm, ss = mean_std(served)
            wm, ws = mean_std(waiting)
            fm, fs = mean_std(frac)
            mm, ms = mean_std(moves)
            sum_rows.append({
                "request_scale": scale,
                "policy": policy,
                "n_runs": len(grp),
                "mean_served": round(sm, 6),
                "std_served": round(ss, 6),
                "mean_waiting_end": round(wm, 6),
                "std_waiting_end": round(ws, 6),
                "mean_served_fraction": round(fm, 6),
                "std_served_fraction": round(fs, 6),
                "mean_rebalance_moves": round(mm, 6),
                "std_rebalance_moves": round(ms, 6),
            })

    with open(summary_csv, "w", encoding="utf-8", newline="") as f:
        fields = [
            "request_scale", "policy", "n_runs",
            "mean_served", "std_served",
            "mean_waiting_end", "std_waiting_end",
            "mean_served_fraction", "std_served_fraction",
            "mean_rebalance_moves", "std_rebalance_moves",
            "delta_served_CG_minus_A",
            "delta_waiting_end_CG_minus_A",
            "delta_served_fraction_CG_minus_A",
        ]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()

        for scale in loads:
            a = next((x for x in sum_rows if x["request_scale"] == scale and x["policy"] == "A"), None)
            c = next((x for x in sum_rows if x["request_scale"] == scale and x["policy"] == "CG"), None)
            for item in [a, c]:
                if item is None:
                    continue
                row = dict(item)
                if a is not None and c is not None:
                    row["delta_served_CG_minus_A"] = round(c["mean_served"] - a["mean_served"], 6)
                    row["delta_waiting_end_CG_minus_A"] = round(c["mean_waiting_end"] - a["mean_waiting_end"], 6)
                    row["delta_served_fraction_CG_minus_A"] = round(c["mean_served_fraction"] - a["mean_served_fraction"], 6)
                else:
                    row["delta_served_CG_minus_A"] = ""
                    row["delta_waiting_end_CG_minus_A"] = ""
                    row["delta_served_fraction_CG_minus_A"] = ""
                w.writerow(row)

    a_x = loads
    a_y = []
    a_e = []
    c_y = []
    c_e = []
    for scale in loads:
        a = next((x for x in sum_rows if x["request_scale"] == scale and x["policy"] == "A"), None)
        c = next((x for x in sum_rows if x["request_scale"] == scale and x["policy"] == "CG"), None)
        a_y.append(a["mean_served_fraction"] if a else 0.0)
        a_e.append(a["std_served_fraction"] if a else 0.0)
        c_y.append(c["mean_served_fraction"] if c else 0.0)
        c_e.append(c["std_served_fraction"] if c else 0.0)

    plt.figure(figsize=(8, 5))
    plt.errorbar(a_x, a_y, yerr=a_e, marker="o", label="Policy A")
    plt.errorbar(a_x, c_y, yerr=c_e, marker="o", label="Policy C_gated fix1")
    plt.xlabel("Request scale")
    plt.ylabel("Served fraction")
    plt.title("A vs C_gated fix1 robustness across load")
    plt.xticks(loads)
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.savefig(figure_png, dpi=150)
    plt.close()

    lines = []
    lines.append("A vs C_gated fix1 Robustness Summary")
    lines.append("")
    lines.append("frozen_setup")
    lines.append("fleet_size=300")
    lines.append("dispatch_interval=15")
    lines.append("candidate_caps=15/15")
    lines.append("rebalance_min_shortage=1")
    lines.append("rebalance_shortage_threshold=0.08")
    lines.append("rebalance_intensity_scale=0.35")
    lines.append("seeds=101,202,303,404,505")
    lines.append("loads=0.004,0.005,0.006")
    lines.append("")

    robust_yes = True
    best_delta = None
    best_scale = None
    for scale in loads:
        a = next((x for x in sum_rows if x["request_scale"] == scale and x["policy"] == "A"), None)
        c = next((x for x in sum_rows if x["request_scale"] == scale and x["policy"] == "CG"), None)
        if not a or not c:
            continue
        d_served = c["mean_served"] - a["mean_served"]
        d_wait = c["mean_waiting_end"] - a["mean_waiting_end"]
        d_frac = c["mean_served_fraction"] - a["mean_served_fraction"]
        lines.append(
            f"scale={scale}: A_mean_served={a['mean_served']:.3f}, CG_mean_served={c['mean_served']:.3f}, "
            f"delta_served={d_served:.3f}; A_mean_waiting={a['mean_waiting_end']:.3f}, "
            f"CG_mean_waiting={c['mean_waiting_end']:.3f}, delta_waiting={d_wait:.3f}; "
            f"delta_served_fraction={d_frac:.6f}; A_mean_moves={a['mean_rebalance_moves']:.3f}, "
            f"CG_mean_moves={c['mean_rebalance_moves']:.3f}"
        )
        if not (d_served > 0 and d_wait < 0):
            robust_yes = False
        if best_delta is None or d_frac > best_delta:
            best_delta = d_frac
            best_scale = scale

    lines.append("")
    lines.append("consistency_check")
    lines.append("Cgated_consistently_beats_A=yes" if robust_yes else "Cgated_consistently_beats_A=no")
    if best_scale is not None:
        lines.append(f"strongest_benefit_load={best_scale}")
        lines.append(f"strongest_benefit_delta_served_fraction={best_delta:.6f}")
    lines.append("advisor_presentation_ready=yes" if robust_yes else "advisor_presentation_ready=partly")
    lines.append("recommended_next_step=writeup_packaging" if robust_yes else "recommended_next_step=one_simple_optimization_baseline")

    with open(summary_txt, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(run_csv)
    print(summary_csv)
    print(summary_txt)
    print(figure_png)


if __name__ == "__main__":
    main()
