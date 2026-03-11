import os
import csv
import subprocess
import xml.etree.ElementTree as ET


project_dir = r"E:\project_sakif_chicago"
runner = os.path.join(project_dir, "scripts", "run_persistent_fleet_experiment.py")
request_file = os.path.join(project_dir, "data", "compact4_request_stream.csv")
out_csv = os.path.join(project_dir, "output", "persistent_A_calibration_results.csv")
out_txt = os.path.join(project_dir, "output", "persistent_A_calibration_summary.txt")

fleet_sizes = [300, 600, 900, 1200]
dispatch_intervals = [30, 15, 10]


def fnum(v):
    try:
        return float(v)
    except Exception:
        return 0.0


def parse_summary_txt(path):
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


def parse_tele_coll(summary_xml):
    teleports = 0
    collisions = 0
    if not os.path.exists(summary_xml):
        return 0, 0
    root = ET.parse(summary_xml).getroot()
    for step in root.findall("step"):
        teleports = max(teleports, int(fnum(step.get("teleports", "0"))))
        collisions = max(collisions, int(fnum(step.get("collisions", "0"))))
    return teleports, collisions


def run_one(fleet_size, interval):
    prefix = f"persistent_A_calib_f{fleet_size}_d{interval}"
    summary_txt = os.path.join(project_dir, "output", f"{prefix}_summary.txt")
    summary_xml = os.path.join(project_dir, "output", f"{prefix}_summary.xml")
    cmd = [
        "python",
        runner,
        "--policy", "A",
        "--fleet-size", str(fleet_size),
        "--decision-interval", str(interval),
        "--request-file", request_file,
        "--end-time", "86400",
        "--output-prefix", prefix,
        "--stage-summary-file", os.path.join(project_dir, "output", f"{prefix}_framework_summary.txt"),
    ]
    p = subprocess.run(cmd, capture_output=True, text=True)
    txt = parse_summary_txt(summary_txt)
    teleports, collisions = parse_tele_coll(summary_xml)
    total_requests = int(fnum(txt.get("total_requests", "0")))
    assigned = int(fnum(txt.get("requests_assigned", "0")))
    served = int(fnum(txt.get("requests_served", "0")))
    waiting_end = int(fnum(txt.get("requests_waiting_end", "0")))
    served_fraction = (served / total_requests) if total_requests > 0 else 0.0
    idle_exists = txt.get("idle_exists_meaningfully", "no")
    return {
        "fleet_size": fleet_size,
        "dispatch_interval": interval,
        "total_requests": total_requests,
        "requests_assigned": assigned,
        "requests_served": served,
        "requests_waiting_end": waiting_end,
        "served_fraction": round(served_fraction, 6),
        "idle_exists_meaningfully": idle_exists,
        "teleports": teleports,
        "collisions": collisions,
        "run_return_code": p.returncode,
    }


rows = []
for fleet_size in fleet_sizes:
    for interval in dispatch_intervals:
        row = run_one(fleet_size, interval)
        rows.append(row)
        print(
            f"done fleet={fleet_size} interval={interval} "
            f"served={row['requests_served']} waiting={row['requests_waiting_end']} "
            f"served_fraction={row['served_fraction']}"
        )

os.makedirs(os.path.dirname(out_csv), exist_ok=True)
with open(out_csv, "w", encoding="utf-8", newline="") as f:
    fields = [
        "fleet_size",
        "dispatch_interval",
        "total_requests",
        "requests_assigned",
        "requests_served",
        "requests_waiting_end",
        "served_fraction",
        "idle_exists_meaningfully",
        "teleports",
        "collisions",
        "run_return_code",
    ]
    w = csv.DictWriter(f, fieldnames=fields)
    w.writeheader()
    for r in rows:
        w.writerow(r)

valid_rows = [r for r in rows if r["run_return_code"] == 0]
if valid_rows:
    ranked = sorted(
        valid_rows,
        key=lambda r: (
            r["served_fraction"],
            -r["teleports"],
            -r["collisions"],
            -r["fleet_size"],
            r["dispatch_interval"],
        ),
        reverse=True,
    )
    best = ranked[0]
else:
    best = None

lines = []
lines.append("persistent A calibration summary")
lines.append("")
lines.append(f"grid_fleet_sizes={fleet_sizes}")
lines.append(f"grid_dispatch_intervals={dispatch_intervals}")
lines.append("")
for r in sorted(rows, key=lambda x: (x["fleet_size"], x["dispatch_interval"])):
    lines.append(
        f"fleet={r['fleet_size']},interval={r['dispatch_interval']},"
        f"served={r['requests_served']},waiting={r['requests_waiting_end']},"
        f"served_fraction={r['served_fraction']},idle={r['idle_exists_meaningfully']},"
        f"teleports={r['teleports']},collisions={r['collisions']},rc={r['run_return_code']}"
    )

lines.append("")
if best:
    lines.append("recommended_setting")
    lines.append(f"fleet_size={best['fleet_size']}")
    lines.append(f"dispatch_interval={best['dispatch_interval']}")
    lines.append(f"served_fraction={best['served_fraction']}")
    lines.append(f"served={best['requests_served']}")
    lines.append(f"waiting_end={best['requests_waiting_end']}")
    lines.append(f"idle_exists_meaningfully={best['idle_exists_meaningfully']}")
    lines.append(f"teleports={best['teleports']}")
    lines.append(f"collisions={best['collisions']}")
    ready = "yes"
    if best["served_fraction"] < 0.20:
        ready = "no"
    if best["idle_exists_meaningfully"] != "yes":
        ready = "no"
    lines.append(f"ready_for_policy_B={ready}")
else:
    lines.append("recommended_setting=none")
    lines.append("ready_for_policy_B=no")

with open(out_txt, "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")

print("results_csv=" + out_csv)
print("summary_txt=" + out_txt)
