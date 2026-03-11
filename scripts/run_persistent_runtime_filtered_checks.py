import os
import csv
import time
import subprocess
import xml.etree.ElementTree as ET


project_dir = r"E:\project_sakif_chicago"
build_request_stream = os.path.join(project_dir, "scripts", "build_request_stream.py")
runner = os.path.join(project_dir, "scripts", "run_persistent_fleet_experiment.py")

fleet_size = 300
dispatch_interval = 15
same_zone_candidate_cap = 15
global_candidate_cap = 15
scales = [0.006, 0.001]

results_csv = os.path.join(project_dir, "output", "persistent_runtime_filtered_results.csv")
summary_txt = os.path.join(project_dir, "output", "persistent_runtime_filtered_summary.txt")
just_txt = os.path.join(project_dir, "output", "persistent_runtime_filter_justification.txt")


def fnum(v):
    try:
        return float(v)
    except Exception:
        return 0.0


def parse_key_values(path):
    data = {}
    if not os.path.exists(path):
        return data
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            s = line.strip()
            if "=" in s:
                k, v = s.split("=", 1)
                data[k.strip()] = v.strip()
    return data


def parse_statistics(path):
    teleports = 0
    collisions = 0
    if not os.path.exists(path):
        return teleports, collisions
    root = ET.parse(path).getroot()
    t = root.find("teleports")
    if t is not None:
        teleports = int(fnum(t.get("total", "0")))
    s = root.find("safety")
    if s is not None:
        collisions = int(fnum(s.get("collisions", "0")))
    return teleports, collisions


def run_one(scale):
    scale_tag = str(scale).replace(".", "p")
    request_file = os.path.join(project_dir, "data", f"compact4_request_stream_s{scale_tag}.csv")
    prefix = f"persistent_A_filtered_{scale_tag}"

    cmd_build = [
        "python", build_request_stream,
        "--scale", str(scale),
        "--output", request_file,
    ]
    build_start = time.perf_counter()
    p_build = subprocess.run(cmd_build, capture_output=True, text=True)
    build_seconds = time.perf_counter() - build_start

    cmd_run = [
        "python", runner,
        "--policy", "A",
        "--fleet-size", str(fleet_size),
        "--decision-interval", str(dispatch_interval),
        "--same-zone-candidate-cap", str(same_zone_candidate_cap),
        "--global-candidate-cap", str(global_candidate_cap),
        "--request-file", request_file,
        "--end-time", "86400",
        "--output-prefix", prefix,
        "--stage-summary-file", os.path.join(project_dir, "output", f"{prefix}_framework_summary.txt"),
    ]
    run_start = time.perf_counter()
    p_run = subprocess.run(cmd_run, capture_output=True, text=True)
    run_seconds = time.perf_counter() - run_start

    run_summary = os.path.join(project_dir, "output", f"{prefix}_summary.txt")
    stats_xml = os.path.join(project_dir, "output", f"{prefix}_statistics.xml")

    data = parse_key_values(run_summary)
    teleports, collisions = parse_statistics(stats_xml)

    total_requests = int(fnum(data.get("total_requests", "0")))
    assigned = int(fnum(data.get("requests_assigned", "0")))
    served = int(fnum(data.get("requests_served", "0")))
    waiting = int(fnum(data.get("requests_waiting_end", "0")))
    served_fraction = (served / total_requests) if total_requests > 0 else 0.0
    idle_exists = data.get("idle_exists_meaningfully", "no")

    return {
        "request_scale": scale,
        "fleet_size": fleet_size,
        "dispatch_interval": dispatch_interval,
        "same_zone_candidate_cap": same_zone_candidate_cap,
        "global_candidate_cap": global_candidate_cap,
        "build_seconds": round(build_seconds, 3),
        "runtime_seconds": round(run_seconds, 3),
        "total_requests": total_requests,
        "requests_assigned": assigned,
        "requests_served": served,
        "requests_waiting_end": waiting,
        "served_fraction": round(served_fraction, 6),
        "idle_exists_meaningfully": idle_exists,
        "teleports": teleports,
        "collisions": collisions,
        "build_return_code": p_build.returncode,
        "run_return_code": p_run.returncode,
        "request_file": request_file,
        "output_prefix": prefix,
    }


def main():
    rows = []
    for scale in scales:
        row = run_one(scale)
        rows.append(row)
        print(
            f"done scale={scale} runtime_seconds={row['runtime_seconds']} total={row['total_requests']} "
            f"served={row['requests_served']} waiting={row['requests_waiting_end']} "
            f"served_fraction={row['served_fraction']} idle={row['idle_exists_meaningfully']}"
        )

    os.makedirs(os.path.dirname(results_csv), exist_ok=True)
    with open(results_csv, "w", encoding="utf-8", newline="") as f:
        fields = [
            "request_scale",
            "fleet_size",
            "dispatch_interval",
            "same_zone_candidate_cap",
            "global_candidate_cap",
            "build_seconds",
            "runtime_seconds",
            "total_requests",
            "requests_assigned",
            "requests_served",
            "requests_waiting_end",
            "served_fraction",
            "idle_exists_meaningfully",
            "teleports",
            "collisions",
            "build_return_code",
            "run_return_code",
            "request_file",
            "output_prefix",
        ]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for row in rows:
            w.writerow(row)

    lines = []
    lines.append("persistent runtime filtered summary")
    lines.append("")
    lines.append(f"fleet_size={fleet_size}")
    lines.append(f"dispatch_interval={dispatch_interval}")
    lines.append(f"same_zone_candidate_cap={same_zone_candidate_cap}")
    lines.append(f"global_candidate_cap={global_candidate_cap}")
    lines.append(f"tested_scales={scales}")
    lines.append("")
    for r in rows:
        lines.append(
            f"scale={r['request_scale']},runtime_seconds={r['runtime_seconds']},total={r['total_requests']},"
            f"assigned={r['requests_assigned']},served={r['requests_served']},"
            f"waiting={r['requests_waiting_end']},served_fraction={r['served_fraction']},"
            f"idle={r['idle_exists_meaningfully']},teleports={r['teleports']},collisions={r['collisions']},"
            f"build_rc={r['build_return_code']},run_rc={r['run_return_code']}"
        )

    with open(summary_txt, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    with open(just_txt, "w", encoding="utf-8") as f:
        f.write("bounded candidate filter justification\n\n")
        f.write("the dispatch structure is unchanged: persistent fleet, request queue, and policy A assignment.\n")
        f.write("the filter only limits how many idle vehicles are evaluated with findRoute for each request.\n")
        f.write("zone-first priority is preserved, then nearest travel-time is computed within a deterministic bounded set.\n")
        f.write("this reduces runtime cost without adding rebalancing logic or changing the conceptual experiment model.\n")

    print("results_csv=" + results_csv)
    print("summary_txt=" + summary_txt)
    print("justification_txt=" + just_txt)


if __name__ == "__main__":
    main()
