import os
import re
import xml.etree.ElementTree as ET


project_dir = r"E:\project_sakif_chicago"
tripinfo_file = os.path.join(project_dir, "output", "baseline_tripinfo.xml")
summary_file = os.path.join(project_dir, "output", "baseline_summary.xml")
stats_file = os.path.join(project_dir, "output", "baseline_statistics.xml")
edge_file = os.path.join(project_dir, "output", "baseline_queue_or_edge_stats.xml")
log_file = os.path.join(project_dir, "output", "baseline_run.log")
out_file = os.path.join(project_dir, "output", "baseline_benchmark_summary.txt")


def fnum(v):
    try:
        return float(v)
    except Exception:
        return 0.0


inserted = 0
arrived = 0
running = 0
waiting = 0
teleports = 0
collisions = 0

if os.path.exists(summary_file):
    root = ET.parse(summary_file).getroot()
    for step in root.findall("step"):
        inserted = max(inserted, int(fnum(step.get("inserted", "0"))))
        arrived = max(arrived, int(fnum(step.get("ended", "0"))))
        running = int(fnum(step.get("running", str(running))))
        waiting = int(fnum(step.get("waiting", str(waiting))))
        teleports = max(teleports, int(fnum(step.get("teleports", str(teleports)))))
        collisions = max(collisions, int(fnum(step.get("collisions", str(collisions)))))

trip_count = 0
sum_duration = 0.0
sum_route_length = 0.0
sum_waiting = 0.0
sum_time_loss = 0.0

if os.path.exists(tripinfo_file):
    root = ET.parse(tripinfo_file).getroot()
    for t in root.findall("tripinfo"):
        trip_count += 1
        sum_duration += fnum(t.get("duration", "0"))
        sum_route_length += fnum(t.get("routeLength", "0"))
        sum_waiting += fnum(t.get("waitingTime", "0"))
        sum_time_loss += fnum(t.get("timeLoss", "0"))

avg_duration = (sum_duration / trip_count) if trip_count > 0 else 0.0
avg_route_length = (sum_route_length / trip_count) if trip_count > 0 else 0.0
avg_waiting = (sum_waiting / trip_count) if trip_count > 0 else 0.0
avg_time_loss = (sum_time_loss / trip_count) if trip_count > 0 else 0.0

teleport_events = []
teleport_reasons = {}
if os.path.exists(log_file):
    with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            s = line.strip()
            if "Teleporting vehicle" in s:
                teleport_events.append(s)
                reason = "unknown"
                if "jam" in s.lower():
                    reason = "jam"
                elif "wrong lane" in s.lower():
                    reason = "wrong lane"
                teleport_reasons[reason] = teleport_reasons.get(reason, 0) + 1

log_collisions = 0
if os.path.exists(log_file):
    with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if "collision" in line.lower():
                log_collisions += 1

bottlenecks = []
if os.path.exists(edge_file):
    root = ET.parse(edge_file).getroot()
    for interval in root.findall("interval"):
        for edge in interval.findall("edge"):
            edge_id = edge.get("id", "")
            if not edge_id:
                continue
            waiting_time = fnum(edge.get("waitingTime", "0"))
            speed = fnum(edge.get("speed", "0"))
            sampled = fnum(edge.get("sampledSeconds", "0"))
            if sampled <= 0:
                continue
            score = waiting_time * 1.0 + max(0.0, 15.0 - speed) * 4.0
            bottlenecks.append((score, edge_id, waiting_time, speed, sampled))

bottlenecks.sort(key=lambda x: x[0], reverse=True)
top_bottlenecks = bottlenecks[:10]

unfinished = max(0, inserted - arrived)
accepted = "yes"
if teleports > 0 or collisions > 0 or unfinished > 0:
    accepted = "no"

lines = []
lines.append("baseline benchmark summary")
lines.append("")
lines.append(f"inserted_vehicles={inserted}")
lines.append(f"arrived_vehicles={arrived}")
lines.append(f"unfinished_vehicles={unfinished}")
lines.append(f"teleports={teleports}")
lines.append(f"collisions={collisions}")
lines.append("")
lines.append(f"avg_trip_duration={round(avg_duration, 6)}")
lines.append(f"avg_route_length={round(avg_route_length, 6)}")
lines.append(f"avg_waiting_time={round(avg_waiting, 6)}")
lines.append(f"avg_time_loss={round(avg_time_loss, 6)}")
lines.append("")
lines.append("teleport_reasons")
if teleport_reasons:
    for k, v in sorted(teleport_reasons.items(), key=lambda x: x[1], reverse=True):
        lines.append(f"{k}={v}")
else:
    lines.append("none")
lines.append("")
lines.append("top_bottleneck_edges")
if top_bottlenecks:
    for _, edge_id, wt, sp, smp in top_bottlenecks:
        lines.append(f"{edge_id},waitingTime={round(wt,6)},speed={round(sp,6)},sampledSeconds={round(smp,6)}")
else:
    lines.append("none")
lines.append("")
lines.append(f"log_collision_mentions={log_collisions}")
lines.append(f"baseline_accepted={accepted}")

with open(out_file, "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")

print("summary file:", out_file)
print(f"inserted={inserted}")
print(f"arrived={arrived}")
print(f"unfinished={unfinished}")
print(f"teleports={teleports}")
print(f"collisions={collisions}")
print(f"avg_duration={round(avg_duration, 6)}")
print(f"avg_route_length={round(avg_route_length, 6)}")
print(f"avg_waiting_time={round(avg_waiting, 6)}")
print(f"avg_time_loss={round(avg_time_loss, 6)}")
print(f"baseline_accepted={accepted}")
