import csv
import statistics
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import matplotlib.pyplot as plt

script_dir = Path(__file__).resolve().parent
project_dir = script_dir.parent
out_dir = project_dir / "output"
vis_dir = project_dir / "visuals"
runner = script_dir / "run_persistent_fleet_experiment.py"
request_builder = script_dir / "build_request_stream.py"

loads = [0.004, 0.005, 0.006]
seeds = [101, 202, 303, 404, 505]
policies = ["A", "CG"]

expected_fleet_size = 300
expected_decision_interval = 15
expected_same_zone_cap = 15
expected_global_cap = 15
expected_max_rebalance_share = 0.15
expected_max_rebalance_count = 25
expected_rebalance_shortage_threshold = 0.08
expected_rebalance_min_shortage = 1
expected_rebalance_intensity_scale = 0.35
expected_network_file = str((project_dir / "net" / "map_reduced_clean_auto_v2.net.xml").resolve())

run_csv = out_dir / "A_vs_Cgated_stochastic_runs.csv"
summary_csv = out_dir / "A_vs_Cgated_stochastic_summary.csv"
summary_txt = out_dir / "A_vs_Cgated_stochastic_summary.txt"
figure_png = vis_dir / "A_vs_Cgated_stochastic.png"


class ValidationError(RuntimeError):
    pass


def fnum(v):
    try:
        return float(v)
    except Exception:
        return 0.0


def scale_tag(scale):
    return f"0p{int(round(scale * 1000)):03d}"


def request_file_for(scale, seed):
    return project_dir / "data" / f"compact4_request_stream_s{scale_tag(scale)}_seed{seed}.csv"


def parse_kv_file(path):
    if not path.exists():
        raise ValidationError(f"missing file: {path}")
    d = {}
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            s = line.strip()
            if "=" in s:
                k, v = s.split("=", 1)
                d[k.strip()] = v.strip()
    return d


def parse_stats_xml(path):
    if not path.exists():
        raise ValidationError(f"missing statistics xml: {path}")
    try:
        root = ET.parse(path).getroot()
    except Exception as e:
        raise ValidationError(f"malformed statistics xml {path}: {e}")
    tele = 0
    col = 0
    t = root.find("teleports")
    if t is not None:
        tele = int(fnum(t.get("total", "0")))
    s = root.find("safety")
    if s is not None:
        col = int(fnum(s.get("collisions", "0")))
    return tele, col


def assert_key(d, key, src):
    if key not in d:
        raise ValidationError(f"missing key '{key}' in {src}")


def as_abs(p):
    return str(Path(p).resolve())


def assert_equal_str(name, actual, expected):
    if str(actual) != str(expected):
        raise ValidationError(f"provenance mismatch for {name}: actual='{actual}' expected='{expected}'")


def assert_equal_int(name, actual, expected):
    try:
        a = int(float(str(actual)))
    except Exception:
        raise ValidationError(f"provenance value not int for {name}: '{actual}'")
    if a != int(expected):
        raise ValidationError(f"provenance mismatch for {name}: actual={a} expected={expected}")


def assert_equal_float(name, actual, expected, tol=1e-9):
    try:
        a = float(str(actual))
    except Exception:
        raise ValidationError(f"provenance value not float for {name}: '{actual}'")
    if abs(a - float(expected)) > tol:
        raise ValidationError(f"provenance mismatch for {name}: actual={a} expected={expected}")


def ensure_request_file(scale, seed):
    req = request_file_for(scale, seed)
    if req.exists():
        return req
    cmd = [
        "python", str(request_builder),
        "--scale", str(scale),
        "--seed", str(seed),
        "--output", str(req),
    ]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise ValidationError(
            f"request build failed for scale={scale} seed={seed}\nstdout:\n{p.stdout}\nstderr:\n{p.stderr}"
        )
    if not req.exists():
        raise ValidationError(f"request builder returned success but file missing: {req}")
    return req


def expected_paths(policy, scale, seed):
    tag = f"stoch_{policy}_s{seed}_r{scale_tag(scale)}"
    return {
        "tag": tag,
        "summary_txt": out_dir / f"{tag}_summary.txt",
        "framework_txt": out_dir / f"{tag}_framework_summary.txt",
        "statistics_xml": out_dir / f"{tag}_statistics.xml",
        "run_log": out_dir / f"{tag}_run.log",
        "policy_log": out_dir / f"{tag}_policy_log.csv",
        "summary_xml": out_dir / f"{tag}_summary.xml",
        "tripinfo_xml": out_dir / f"{tag}_tripinfo.xml",
    }


def validate_existing_run(policy, scale, seed, req_file):
    paths = expected_paths(policy, scale, seed)
    summary_path = paths["summary_txt"]
    if not summary_path.exists():
        return None

    summary = parse_kv_file(summary_path)

    required_summary_keys = [
        "summary_generation_timestamp",
        "policy",
        "request_file",
        "request_scale",
        "seed",
        "fleet_size",
        "decision_interval",
        "same_zone_candidate_cap",
        "global_candidate_cap",
        "rebalance_min_shortage",
        "rebalance_shortage_threshold",
        "rebalance_intensity_scale",
        "max_rebalance_share",
        "max_rebalance_count",
        "network_file",
        "statistics_output_enabled",
        "statistics_file",
        "summary_xml_file",
        "tripinfo_file",
        "policy_log_file",
        "run_log_file",
        "stage_summary_file",
        "output_prefix",
        "total_requests",
        "requests_served",
        "requests_waiting_end",
        "rebalance_moves",
    ]
    for k in required_summary_keys:
        assert_key(summary, k, summary_path)

    expected_scale = f"{scale:.3f}"
    assert_equal_str("policy", summary["policy"], policy)
    assert_equal_str("request_file", as_abs(summary["request_file"]), as_abs(req_file))
    assert_equal_str("request_scale", summary["request_scale"], expected_scale)
    assert_equal_int("seed", summary["seed"], seed)
    assert_equal_int("fleet_size", summary["fleet_size"], expected_fleet_size)
    assert_equal_int("decision_interval", summary["decision_interval"], expected_decision_interval)
    assert_equal_int("same_zone_candidate_cap", summary["same_zone_candidate_cap"], expected_same_zone_cap)
    assert_equal_int("global_candidate_cap", summary["global_candidate_cap"], expected_global_cap)
    assert_equal_int("rebalance_min_shortage", summary["rebalance_min_shortage"], expected_rebalance_min_shortage)
    assert_equal_float("rebalance_shortage_threshold", summary["rebalance_shortage_threshold"], expected_rebalance_shortage_threshold)
    assert_equal_float("rebalance_intensity_scale", summary["rebalance_intensity_scale"], expected_rebalance_intensity_scale)
    assert_equal_float("max_rebalance_share", summary["max_rebalance_share"], expected_max_rebalance_share)
    assert_equal_int("max_rebalance_count", summary["max_rebalance_count"], expected_max_rebalance_count)
    assert_equal_str("network_file", as_abs(summary["network_file"]), expected_network_file)

    assert_equal_str("output_prefix", summary["output_prefix"], paths["tag"])
    assert_equal_str("summary_xml_file", as_abs(summary["summary_xml_file"]), as_abs(paths["summary_xml"]))
    assert_equal_str("tripinfo_file", as_abs(summary["tripinfo_file"]), as_abs(paths["tripinfo_xml"]))
    assert_equal_str("policy_log_file", as_abs(summary["policy_log_file"]), as_abs(paths["policy_log"]))
    assert_equal_str("run_log_file", as_abs(summary["run_log_file"]), as_abs(paths["run_log"]))
    assert_equal_str("stage_summary_file", as_abs(summary["stage_summary_file"]), as_abs(paths["framework_txt"]))

    if not req_file.exists():
        raise ValidationError(f"request file listed in summary does not exist: {req_file}")

    if not paths["framework_txt"].exists():
        raise ValidationError(f"missing framework summary txt: {paths['framework_txt']}")

    if not paths["run_log"].exists():
        raise ValidationError(f"missing run log: {paths['run_log']}")

    if not paths["policy_log"].exists():
        raise ValidationError(f"missing policy log: {paths['policy_log']}")

    if not paths["summary_xml"].exists():
        raise ValidationError(f"missing summary xml: {paths['summary_xml']}")

    if not paths["tripinfo_xml"].exists():
        raise ValidationError(f"missing tripinfo xml: {paths['tripinfo_xml']}")

    if summary["statistics_output_enabled"].lower() not in ["yes", "no"]:
        raise ValidationError("statistics_output_enabled must be yes/no")

    if summary["statistics_output_enabled"].lower() == "yes":
        assert_equal_str("statistics_file", as_abs(summary["statistics_file"]), as_abs(paths["statistics_xml"]))
        tele, col = parse_stats_xml(paths["statistics_xml"])
    else:
        tele = 0
        col = 0

    try:
        total = int(float(summary["total_requests"]))
        served = int(float(summary["requests_served"]))
        waiting = int(float(summary["requests_waiting_end"]))
        moves = int(float(summary["rebalance_moves"]))
    except Exception:
        raise ValidationError("summary metrics are malformed (total_requests/requests_served/requests_waiting_end/rebalance_moves)")

    frac = (served / total) if total > 0 else 0.0

    return {
        "policy": policy,
        "request_scale": scale,
        "seed": seed,
        "request_file": str(req_file),
        "total_requests": total,
        "requests_served": served,
        "requests_waiting_end": waiting,
        "served_fraction": round(frac, 6),
        "teleports": tele,
        "collisions": col,
        "rebalance_moves": moves,
        "run_return_code": 0,
        "runtime_sec": "",
        "output_prefix": paths["tag"],
        "source": "existing",
    }


def run_one(policy, scale, seed):
    req_file = ensure_request_file(scale, seed)

    existing = validate_existing_run(policy, scale, seed, req_file)
    if existing is not None:
        return existing

    paths = expected_paths(policy, scale, seed)
    cmd = [
        "python", str(runner),
        "--policy", policy,
        "--fleet-size", str(expected_fleet_size),
        "--decision-interval", str(expected_decision_interval),
        "--same-zone-candidate-cap", str(expected_same_zone_cap),
        "--global-candidate-cap", str(expected_global_cap),
        "--max-rebalance-share", str(expected_max_rebalance_share),
        "--max-rebalance-count", str(expected_max_rebalance_count),
        "--rebalance-shortage-threshold", str(expected_rebalance_shortage_threshold),
        "--rebalance-min-shortage", str(expected_rebalance_min_shortage),
        "--rebalance-intensity-scale", str(expected_rebalance_intensity_scale),
        "--request-file", str(req_file),
        "--end-time", "86400",
        "--seed", str(seed),
        "--output-prefix", paths["tag"],
        "--stage-summary-file", str(paths["framework_txt"]),
    ]

    t0 = time.time()
    p = subprocess.run(cmd, capture_output=True, text=True)
    runtime = round(time.time() - t0, 3)

    if p.returncode != 0:
        raise ValidationError(
            f"run failed for policy={policy} scale={scale} seed={seed}\n"
            f"stdout:\n{p.stdout}\n"
            f"stderr:\n{p.stderr}"
        )

    validated = validate_existing_run(policy, scale, seed, req_file)
    if validated is None:
        raise ValidationError(f"run completed but summary artifact missing for policy={policy} scale={scale} seed={seed}")
    validated["source"] = "new"
    validated["runtime_sec"] = runtime
    return validated


def write_outputs(rows):
    with open(run_csv, "w", encoding="utf-8", newline="") as f:
        fields = [
            "policy", "request_scale", "seed", "request_file", "total_requests",
            "requests_served", "requests_waiting_end", "served_fraction",
            "teleports", "collisions", "rebalance_moves", "run_return_code",
            "runtime_sec", "output_prefix", "source",
        ]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)

    valid = [r for r in rows if r["run_return_code"] == 0]
    expected_total = len(loads) * len(seeds) * len(policies)
    if len(valid) != expected_total:
        raise ValidationError(f"incomplete valid run set: got {len(valid)} expected {expected_total}")

    for scale in loads:
        for seed in seeds:
            pair = [r for r in valid if float(r["request_scale"]) == scale and int(r["seed"]) == seed]
            if len(pair) != 2:
                raise ValidationError(f"missing A/CG pair for scale={scale} seed={seed}")
            rf = {Path(r["request_file"]).resolve() for r in pair}
            if len(rf) != 1:
                raise ValidationError(f"request fairness violation: A/CG use different request files for scale={scale} seed={seed}")

    sum_rows = []
    for scale in loads:
        for policy in policies:
            grp = [r for r in valid if float(r["request_scale"]) == scale and r["policy"] == policy]
            served = [float(r["requests_served"]) for r in grp]
            waiting = [float(r["requests_waiting_end"]) for r in grp]
            frac = [float(r["served_fraction"]) for r in grp]
            moves = [float(r["rebalance_moves"]) for r in grp]
            sm = statistics.mean(served)
            ss = statistics.stdev(served) if len(served) > 1 else 0.0
            wm = statistics.mean(waiting)
            ws = statistics.stdev(waiting) if len(waiting) > 1 else 0.0
            fm = statistics.mean(frac)
            fs = statistics.stdev(frac) if len(frac) > 1 else 0.0
            mm = statistics.mean(moves)
            ms = statistics.stdev(moves) if len(moves) > 1 else 0.0
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
            if a is None or c is None:
                raise ValidationError(f"missing aggregated A/CG rows for scale={scale}")
            for item in [a, c]:
                row = dict(item)
                row["delta_served_CG_minus_A"] = round(c["mean_served"] - a["mean_served"], 6)
                row["delta_waiting_end_CG_minus_A"] = round(c["mean_waiting_end"] - a["mean_waiting_end"], 6)
                row["delta_served_fraction_CG_minus_A"] = round(c["mean_served_fraction"] - a["mean_served_fraction"], 6)
                w.writerow(row)

    x = loads
    ay = []
    ae = []
    cy = []
    ce = []
    for scale in loads:
        a = next(xr for xr in sum_rows if xr["request_scale"] == scale and xr["policy"] == "A")
        c = next(xr for xr in sum_rows if xr["request_scale"] == scale and xr["policy"] == "CG")
        ay.append(a["mean_served_fraction"])
        ae.append(a["std_served_fraction"])
        cy.append(c["mean_served_fraction"])
        ce.append(c["std_served_fraction"])

    plt.figure(figsize=(8, 5))
    plt.errorbar(x, ay, yerr=ae, marker="o", label="Policy A")
    plt.errorbar(x, cy, yerr=ce, marker="o", label="Policy C_gated fix1")
    plt.xlabel("Request scale")
    plt.ylabel("Served fraction")
    plt.title("A vs C_gated fix1 stochastic robustness")
    plt.xticks(loads)
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.savefig(figure_png, dpi=150)
    plt.close()

    lines = []
    lines.append("A vs C_gated fix1 Stochastic Robustness Summary")
    lines.append("")
    lines.append("frozen_setup")
    lines.append(f"fleet_size={expected_fleet_size}")
    lines.append(f"dispatch_interval={expected_decision_interval}")
    lines.append(f"candidate_caps={expected_same_zone_cap}/{expected_global_cap}")
    lines.append(f"rebalance_min_shortage={expected_rebalance_min_shortage}")
    lines.append(f"rebalance_shortage_threshold={expected_rebalance_shortage_threshold}")
    lines.append(f"rebalance_intensity_scale={expected_rebalance_intensity_scale}")
    lines.append("seeds=" + ",".join(str(s) for s in seeds))
    lines.append("loads=" + ",".join(f"{x:.3f}" for x in loads))
    lines.append("")

    robust = True
    best_load = None
    best_delta = None
    for scale in loads:
        a = next((x for x in sum_rows if x["request_scale"] == scale and x["policy"] == "A"), None)
        c = next((x for x in sum_rows if x["request_scale"] == scale and x["policy"] == "CG"), None)
        d_served = c["mean_served"] - a["mean_served"]
        d_wait = c["mean_waiting_end"] - a["mean_waiting_end"]
        d_frac = c["mean_served_fraction"] - a["mean_served_fraction"]
        lines.append(
            f"scale={scale:.3f}: A_mean_served={a['mean_served']:.3f} (sd={a['std_served']:.3f}), "
            f"CG_mean_served={c['mean_served']:.3f} (sd={c['std_served']:.3f}), delta_served={d_served:.3f}; "
            f"A_mean_waiting={a['mean_waiting_end']:.3f}, CG_mean_waiting={c['mean_waiting_end']:.3f}, "
            f"delta_waiting={d_wait:.3f}; delta_served_fraction={d_frac:.6f}"
        )
        if not (d_served > 0 and d_wait < 0):
            robust = False
        if best_delta is None or d_frac > best_delta:
            best_delta = d_frac
            best_load = scale

    lines.append("")
    lines.append("consistency_check")
    lines.append("Cgated_consistently_beats_A=yes" if robust else "Cgated_consistently_beats_A=no")
    if best_load is not None:
        lines.append(f"strongest_benefit_load={best_load:.3f}")
        lines.append(f"strongest_benefit_delta_served_fraction={best_delta:.6f}")

    with open(summary_txt, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main():
    out_dir.mkdir(parents=True, exist_ok=True)
    vis_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for scale in loads:
        for seed in seeds:
            for policy in policies:
                row = run_one(policy, scale, seed)
                rows.append(row)
                print(
                    f"{row['source']} scale={scale:.3f} seed={seed} policy={policy} "
                    f"served={row['requests_served']} waiting={row['requests_waiting_end']} "
                    f"frac={row['served_fraction']} runtime={row['runtime_sec']}"
                )

    write_outputs(rows)

    if not run_csv.exists() or not summary_csv.exists() or not summary_txt.exists() or not figure_png.exists():
        raise ValidationError("final outputs missing after write stage")

    print(run_csv)
    print(summary_csv)
    print(summary_txt)
    print(figure_png)


if __name__ == "__main__":
    main()
