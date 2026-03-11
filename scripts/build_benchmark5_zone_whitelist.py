from pathlib import Path
import csv
import json
import sumolib

root = Path(r"E:\project_sakif_chicago")
net_file = root / "net" / "map_reduced_clean_auto_v2.net.xml"

candidate_files = {
    "8": root / "data" / "benchmark5_zone_edges_area8.txt",
    "24": root / "data" / "benchmark5_zone_edges_area24.txt",
    "28": root / "data" / "benchmark5_zone_edges_area28.txt",
    "32": root / "data" / "benchmark5_zone_edges_area32.txt",
    "33": root / "data" / "benchmark5_zone_edges_area33.txt",
}

final_files = {
    "8": root / "data" / "benchmark5_zone_edges_area8_final.txt",
    "24": root / "data" / "benchmark5_zone_edges_area24_final.txt",
    "28": root / "data" / "benchmark5_zone_edges_area28_final.txt",
    "32": root / "data" / "benchmark5_zone_edges_area32_final.txt",
    "33": root / "data" / "benchmark5_zone_edges_area33_final.txt",
}

area_name = {
    "8": "NEAR NORTH SIDE",
    "24": "WEST TOWN",
    "28": "NEAR WEST SIDE",
    "32": "LOOP",
    "33": "NEAR SOUTH SIDE",
}

area_class = {
    "8": "partial",
    "24": "fringe",
    "28": "partial",
    "32": "interior",
    "33": "fringe",
}

out_csv = root / "output" / "benchmark5_zone_edge_whitelist.csv"
out_json = root / "output" / "benchmark5_zone_edge_whitelist.json"
out_txt = root / "output" / "benchmark5_zone_edge_whitelist_summary.txt"

for p in candidate_files.values():
    if not p.exists():
        raise SystemExit(f"missing candidate file: {p}")
if not net_file.exists():
    raise SystemExit("network file missing")

net = sumolib.net.readNet(str(net_file), withInternal=False)
edge_map = {e.getID(): e for e in net.getEdges()}


def keep_edge(aid, e):
    lanes = e.getLanes()
    if not lanes:
        return False, "no_lanes"
    if not any(l.allows("passenger") for l in lanes):
        return False, "not_passenger_drivable"
    if e.getID().startswith(":"):
        return False, "internal_id"

    lane_count = len(lanes)
    length = float(e.getLength())
    speed = max(float(l.getSpeed()) for l in lanes)
    incoming = len(e.getIncoming())
    outgoing = len(e.getOutgoing())

    if incoming == 0 or outgoing == 0:
        return False, "dead_end_like_connectivity"

    cls = area_class[aid]
    if cls == "interior":
        if length < 30:
            return False, "too_short_for_interior"
        if speed < 5.0:
            return False, "too_slow_for_interior"
        return True, "usable_interior"

    if cls == "partial":
        if length < 35:
            return False, "too_short_for_partial"
        if speed < 5.0:
            return False, "too_slow_for_partial"
        if lane_count < 1:
            return False, "insufficient_lanes_partial"
        return True, "usable_partial"

    if cls == "fringe":
        if lane_count < 2:
            return False, "fringe_needs_multilane"
        if length < 60:
            return False, "fringe_needs_longer_gateway"
        if speed < 8.33:
            return False, "fringe_needs_faster_gateway"
        return True, "usable_fringe_gateway"

    return False, "unknown_class"

rows = []
per_area_final = {}

for aid, fpath in candidate_files.items():
    seen = set()
    candidates = []
    for line in fpath.read_text(encoding="utf-8").splitlines():
        eid = line.strip()
        if not eid or eid in seen:
            continue
        seen.add(eid)
        candidates.append(eid)

    kept = []
    for eid in candidates:
        if eid not in edge_map:
            rows.append({
                "area_id": aid,
                "area_name": area_name[aid],
                "area_class": area_class[aid],
                "edge_id": eid,
                "exists_in_network": "no",
                "passenger_drivable": "",
                "lane_count": "",
                "length_m": "",
                "speed_mps": "",
                "incoming_conn_count": "",
                "outgoing_conn_count": "",
                "keep": "no",
                "reason": "missing_in_network",
            })
            continue

        e = edge_map[eid]
        lanes = e.getLanes()
        lane_count = len(lanes)
        length = round(float(e.getLength()), 3)
        speed = round(max(float(l.getSpeed()) for l in lanes), 3) if lanes else 0.0
        incoming = len(e.getIncoming())
        outgoing = len(e.getOutgoing())
        passenger = any(l.allows("passenger") for l in lanes) if lanes else False

        keep, reason = keep_edge(aid, e)
        if keep:
            kept.append((eid, lane_count, length, speed))

        rows.append({
            "area_id": aid,
            "area_name": area_name[aid],
            "area_class": area_class[aid],
            "edge_id": eid,
            "exists_in_network": "yes",
            "passenger_drivable": "yes" if passenger else "no",
            "lane_count": lane_count,
            "length_m": length,
            "speed_mps": speed,
            "incoming_conn_count": incoming,
            "outgoing_conn_count": outgoing,
            "keep": "yes" if keep else "no",
            "reason": reason,
        })

    kept.sort(key=lambda x: (-x[1], -x[2], -x[3], x[0]))
    final_ids = [x[0] for x in kept]
    per_area_final[aid] = final_ids
    final_files[aid].write_text("\n".join(final_ids) + ("\n" if final_ids else ""), encoding="utf-8")

with out_csv.open("w", newline="", encoding="utf-8") as f:
    fields = [
        "area_id", "area_name", "area_class", "edge_id", "exists_in_network",
        "passenger_drivable", "lane_count", "length_m", "speed_mps",
        "incoming_conn_count", "outgoing_conn_count", "keep", "reason"
    ]
    w = csv.DictWriter(f, fieldnames=fields)
    w.writeheader()
    for r in rows:
        w.writerow(r)

overlap_map = {}
for aid, eids in per_area_final.items():
    for eid in eids:
        overlap_map.setdefault(eid, []).append(aid)

overlap_edges = {eid: aids for eid, aids in overlap_map.items() if len(aids) > 1}

summary_area = {}
for aid in ["8", "24", "28", "32", "33"]:
    kept = per_area_final[aid]
    cls = area_class[aid]
    enough = False
    if cls == "interior":
        enough = len(kept) >= 8
    elif cls == "partial":
        enough = len(kept) >= 6
    else:
        enough = len(kept) >= 3
    summary_area[aid] = {
        "area_name": area_name[aid],
        "area_class": cls,
        "usable_edge_count": len(kept),
        "is_valid_for_simulation": enough,
        "best_edges": kept[:12],
    }

json_out = {
    "network": str(net_file),
    "areas": summary_area,
    "overlap_edges_multi_area": overlap_edges,
}
out_json.write_text(json.dumps(json_out, indent=2), encoding="utf-8")

lines = []
lines.append("Benchmark5 zone-edge whitelist summary")
lines.append("network: " + str(net_file))
lines.append("")
for aid in ["8", "24", "28", "32", "33"]:
    s = summary_area[aid]
    lines.append(f"{aid} {s['area_name']}")
    lines.append(f"- area_class: {s['area_class']}")
    lines.append(f"- usable_edge_count: {s['usable_edge_count']}")
    lines.append(f"- valid_for_simulation: {'yes' if s['is_valid_for_simulation'] else 'no'}")
    lines.append("- best_edges: " + ", ".join(s["best_edges"]))
    lines.append("")

lines.append(f"multi_area_edge_overlap_count: {len(overlap_edges)}")
if overlap_edges:
    lines.append("multi_area_overlap_edges:")
    for eid, aids in sorted(overlap_edges.items()):
        lines.append(f"- {eid}: {','.join(sorted(aids, key=int))}")

all_valid = all(summary_area[a]["is_valid_for_simulation"] for a in summary_area)
lines.append("")
lines.append("final assessment:")
lines.append(f"- all_5_areas_valid: {'yes' if all_valid else 'no'}")
lines.append("- 24_and_33_fringe_status: acceptable fringe zones if used as controlled gateways")
if all_valid:
    lines.append("- proceed_next_step: yes, build final SUMO TAZ/zone file from these whitelists")
else:
    lines.append("- proceed_next_step: no, repair low-edge areas before TAZ build")

out_txt.write_text("\n".join(lines), encoding="utf-8")

print("done")
for aid in ["8", "24", "28", "32", "33"]:
    print(aid, len(per_area_final[aid]))
print("overlap", len(overlap_edges))
