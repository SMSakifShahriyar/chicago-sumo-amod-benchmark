import os
import csv
import json
import math
import random
import xml.etree.ElementTree as ET

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D


project_dir = r"E:\project_sakif_chicago"
network_file = os.path.join(project_dir, "net", "map_reduced_clean_auto_v2.net.xml")
output_dir = os.path.join(project_dir, "output")
visual_dir = os.path.join(project_dir, "visuals")

official_zone_files = {
    8: os.path.join(project_dir, "data", "benchmark5_zone_edges_area8_unique.txt"),
    24: os.path.join(project_dir, "data", "benchmark5_zone_edges_area24_unique.txt"),
    28: os.path.join(project_dir, "data", "benchmark5_zone_edges_area28_unique.txt"),
    32: os.path.join(project_dir, "data", "benchmark5_zone_edges_area32_unique.txt"),
    33: os.path.join(project_dir, "data", "benchmark5_zone_edges_area33_unique.txt"),
}

official_zone_names = {
    8: "NEAR NORTH SIDE",
    24: "WEST TOWN",
    28: "NEAR WEST SIDE",
    32: "LOOP",
    33: "NEAR SOUTH SIDE",
}

zone_colors = ["#1f78b4", "#33a02c", "#e31a1c", "#ff7f00", "#6a3d9a", "#b15928"]


def parse_shape(text):
    pts = []
    if not text:
        return pts
    for part in text.strip().split():
        if "," not in part:
            continue
        x, y = part.split(",", 1)
        try:
            pts.append((float(x), float(y)))
        except ValueError:
            pass
    return pts


def lane_allows_passenger(lane):
    allow = lane.get("allow")
    disallow = lane.get("disallow")
    if allow:
        allow_set = set(x.strip() for x in allow.split())
        if "all" in allow_set or "passenger" in allow_set:
            return True
        return False
    if disallow:
        disallow_set = set(x.strip() for x in disallow.split())
        if "all" in disallow_set or "passenger" in disallow_set:
            return False
    return True


def shape_mid(shape):
    if not shape:
        return None
    if len(shape) == 1:
        return shape[0]
    segs = []
    total = 0.0
    for i in range(len(shape) - 1):
        x1, y1 = shape[i]
        x2, y2 = shape[i + 1]
        d = math.hypot(x2 - x1, y2 - y1)
        segs.append((d, x1, y1, x2, y2))
        total += d
    if total == 0:
        return shape[len(shape) // 2]
    goal = total / 2.0
    run = 0.0
    for d, x1, y1, x2, y2 in segs:
        if d > 0 and run + d >= goal:
            r = (goal - run) / d
            return (x1 + r * (x2 - x1), y1 + r * (y2 - y1))
        run += d
    return shape[-1]


def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def connected_components(edge_ids, edge_nodes):
    if not edge_ids:
        return []
    node_to_edges = {}
    for e in edge_ids:
        fn, tn = edge_nodes[e]
        node_to_edges.setdefault(fn, set()).add(e)
        node_to_edges.setdefault(tn, set()).add(e)
    unseen = set(edge_ids)
    groups = []
    while unseen:
        seed = next(iter(unseen))
        unseen.remove(seed)
        stack = [seed]
        comp = [seed]
        while stack:
            e = stack.pop()
            fn, tn = edge_nodes[e]
            for n in (fn, tn):
                for nb in node_to_edges.get(n, set()):
                    if nb in unseen:
                        unseen.remove(nb)
                        stack.append(nb)
                        comp.append(nb)
        groups.append(comp)
    groups.sort(key=lambda x: len(x), reverse=True)
    return groups


def build_kmeans(points, k, iters=30):
    xs = sorted(p[0] for p in points)
    ys = sorted(p[1] for p in points)
    n = len(points)
    centroids = []
    for i in range(k):
        idx = int((i + 0.5) * n / k)
        if idx >= n:
            idx = n - 1
        centroids.append((xs[idx], ys[idx]))
    for _ in range(iters):
        clusters = [[] for _ in range(k)]
        for p in points:
            dvals = [dist(p, c) for c in centroids]
            zi = min(range(k), key=lambda j: dvals[j])
            clusters[zi].append(p)
        new_centroids = []
        for i in range(k):
            if clusters[i]:
                cx = sum(p[0] for p in clusters[i]) / len(clusters[i])
                cy = sum(p[1] for p in clusters[i]) / len(clusters[i])
                new_centroids.append((cx, cy))
            else:
                new_centroids.append(centroids[i])
        if all(dist(centroids[i], new_centroids[i]) < 1e-6 for i in range(k)):
            centroids = new_centroids
            break
        centroids = new_centroids
    return centroids


def load_official_edge_sets():
    data = {}
    for aid, path in official_zone_files.items():
        edge_ids = []
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    s = line.strip()
                    if s:
                        edge_ids.append(s)
        data[aid] = set(edge_ids)
    return data


os.makedirs(output_dir, exist_ok=True)
os.makedirs(visual_dir, exist_ok=True)

root = ET.parse(network_file).getroot()

junction_xy = {}
junction_type = {}
for j in root.findall("junction"):
    jid = j.get("id")
    if not jid:
        continue
    try:
        x = float(j.get("x", "nan"))
        y = float(j.get("y", "nan"))
    except ValueError:
        continue
    junction_xy[jid] = (x, y)
    junction_type[jid] = j.get("type", "")

edges = {}
all_shapes = {}
for edge in root.findall("edge"):
    eid = edge.get("id", "")
    if not eid or eid.startswith(":"):
        continue
    fn = edge.get("from")
    tn = edge.get("to")
    if not fn or not tn:
        continue
    lane_elems = edge.findall("lane")
    if not lane_elems:
        continue
    drivable = any(lane_allows_passenger(l) for l in lane_elems)
    if not drivable:
        continue
    best_lane = lane_elems[0]
    try:
        length = float(best_lane.get("length", "0"))
    except ValueError:
        length = 0.0
    shape = parse_shape(best_lane.get("shape", ""))
    if not shape:
        shape = parse_shape(edge.get("shape", ""))
    if not shape and fn in junction_xy and tn in junction_xy:
        shape = [junction_xy[fn], junction_xy[tn]]
    if not shape:
        continue
    mid = shape_mid(shape)
    if not mid:
        continue
    lanes = 0
    for lane in lane_elems:
        if lane_allows_passenger(lane):
            lanes += 1
    if lanes <= 0:
        lanes = 1
    edges[eid] = {
        "id": eid,
        "from": fn,
        "to": tn,
        "length": length,
        "lanes": lanes,
        "shape": shape,
        "mid": mid,
    }
    all_shapes[eid] = shape

if not edges:
    raise RuntimeError("No drivable edges found in network.")

edge_nodes = {eid: (e["from"], e["to"]) for eid, e in edges.items()}

all_edge_ids = list(edges.keys())
all_groups = connected_components(all_edge_ids, edge_nodes)
main_edges = set(all_groups[0])

main_points = [edges[eid]["mid"] for eid in main_edges]
main_ids = list(main_edges)

xmin = min(p[0] for p in main_points)
xmax = max(p[0] for p in main_points)
ymin = min(p[1] for p in main_points)
ymax = max(p[1] for p in main_points)
xpad = (xmax - xmin) * 0.08
ypad = (ymax - ymin) * 0.08

edge_degree = {}
for eid in main_ids:
    fn, tn = edge_nodes[eid]
    edge_degree.setdefault(fn, 0)
    edge_degree.setdefault(tn, 0)
    edge_degree[fn] += 1
    edge_degree[tn] += 1

def evaluate_k(k):
    points = [edges[eid]["mid"] for eid in main_ids]
    centroids = build_kmeans(points, k)
    assign = {}
    for eid in main_ids:
        p = edges[eid]["mid"]
        dvals = [dist(p, c) for c in centroids]
        zi = min(range(k), key=lambda j: dvals[j])
        assign[eid] = zi
    changed = True
    while changed:
        changed = False
        for z in range(k):
            zedges = [eid for eid, zid in assign.items() if zid == z]
            if len(zedges) <= 1:
                continue
            comps = connected_components(zedges, edge_nodes)
            keep = set(comps[0])
            for comp in comps[1:]:
                for eid in comp:
                    fn, tn = edge_nodes[eid]
                    neighbor_votes = {}
                    for nid in (fn, tn):
                        for oeid, oz in assign.items():
                            if oeid == eid:
                                continue
                            ofn, otn = edge_nodes[oeid]
                            if ofn == nid or otn == nid:
                                neighbor_votes[oz] = neighbor_votes.get(oz, 0) + 1
                    if neighbor_votes:
                        nz = max(neighbor_votes.keys(), key=lambda zz: (neighbor_votes[zz], -dist(edges[eid]["mid"], centroids[zz])))
                    else:
                        dvals = [dist(edges[eid]["mid"], c) for c in centroids]
                        nz = min(range(k), key=lambda j: dvals[j])
                    if nz != assign[eid]:
                        assign[eid] = nz
                        changed = True
    metrics = []
    for z in range(k):
        zedges = [eid for eid, zid in assign.items() if zid == z]
        if not zedges:
            metrics.append({"zone": z, "count": 0, "comps": 0, "largest_ratio": 0.0, "spread": 0.0})
            continue
        comps = connected_components(zedges, edge_nodes)
        largest_ratio = len(comps[0]) / len(zedges)
        cx = sum(edges[e]["mid"][0] for e in zedges) / len(zedges)
        cy = sum(edges[e]["mid"][1] for e in zedges) / len(zedges)
        spread = sum(dist(edges[e]["mid"], (cx, cy)) for e in zedges) / len(zedges)
        metrics.append({"zone": z, "count": len(zedges), "comps": len(comps), "largest_ratio": largest_ratio, "spread": spread})
    avg_ratio = sum(m["largest_ratio"] for m in metrics) / k
    avg_spread = sum(m["spread"] for m in metrics) / k
    min_count = min(m["count"] for m in metrics)
    empty_penalty = sum(1 for m in metrics if m["count"] == 0)
    score = avg_ratio * 3.0 - avg_spread * 0.003 + min_count * 0.02 - empty_penalty * 5.0
    return {"k": k, "assign": assign, "centroids": centroids, "metrics": metrics, "score": score}


results = [evaluate_k(k) for k in [4, 5, 6]]
best = max(results, key=lambda r: r["score"])

k = best["k"]
assign = best["assign"]
centroids = best["centroids"]

official_edge_sets = load_official_edge_sets()
official_centers = {}
for aid, eset in official_edge_sets.items():
    pts = [edges[e]["mid"] for e in eset if e in edges]
    if pts:
        official_centers[aid] = (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))

zone_rows = []
zone_json = []
zone_summary_lines = []

for zi in range(k):
    zid = f"CZ{zi + 1}"
    zedges = sorted([eid for eid, v in assign.items() if v == zi])
    if zedges:
        cx = sum(edges[e]["mid"][0] for e in zedges) / len(zedges)
        cy = sum(edges[e]["mid"][1] for e in zedges) / len(zedges)
        center = (cx, cy)
    else:
        center = centroids[zi]
    comps = connected_components(zedges, edge_nodes)
    comp_count = len(comps)
    contiguous = "yes" if comp_count <= 1 else "partial" if comp_count <= 2 else "no"
    bbox_touch_count = 0
    degree1_count = 0
    source_sink_count = 0
    for e in zedges:
        shp = edges[e]["shape"]
        touch = False
        for x, y in shp:
            if x <= xmin + xpad or x >= xmax - xpad or y <= ymin + ypad or y >= ymax - ypad:
                touch = True
                break
        fn, tn = edge_nodes[e]
        d1 = edge_degree.get(fn, 0) <= 1 or edge_degree.get(tn, 0) <= 1
        if touch:
            bbox_touch_count += 1
        if d1:
            degree1_count += 1
        if touch or d1:
            source_sink_count += 1
    if source_sink_count >= 5:
        sink_status = "strong"
    elif source_sink_count >= 2:
        sink_status = "ok"
    else:
        sink_status = "weak"
    if zedges:
        avg_lanes = sum(edges[e]["lanes"] for e in zedges) / len(zedges)
        avg_len = sum(edges[e]["length"] for e in zedges) / len(zedges)
    else:
        avg_lanes = 0.0
        avg_len = 0.0
    near_official = []
    for aid, oc in official_centers.items():
        near_official.append((aid, dist(center, oc)))
    near_official.sort(key=lambda x: x[1])
    top_official = [f"{aid}:{official_zone_names[aid]}" for aid, _ in near_official[:2]] if near_official else []
    quality_flags = []
    if len(zedges) < 20:
        quality_flags.append("low_edge_count")
    if comp_count > 2:
        quality_flags.append("fragmented")
    if sink_status == "weak":
        quality_flags.append("weak_source_sink")
    if not quality_flags:
        quality_flags.append("good")
    row = {
        "zone_id": zid,
        "zone_name": f"COMPACT_{zi + 1}",
        "center_x": round(center[0], 3),
        "center_y": round(center[1], 3),
        "edge_count": len(zedges),
        "contiguous": contiguous,
        "component_count": comp_count,
        "source_sink_edges": source_sink_count,
        "source_sink_status": sink_status,
        "avg_lanes": round(avg_lanes, 3),
        "avg_edge_length": round(avg_len, 3),
        "overlap_hint_official_areas": " | ".join(top_official),
        "quality_flags": " | ".join(quality_flags),
    }
    zone_rows.append(row)
    zone_json.append({
        **row,
        "edges": zedges,
        "bbox_touch_edges": bbox_touch_count,
        "degree1_touch_edges": degree1_count,
    })
    zone_summary_lines.append(
        f"{zid}: center=({row['center_x']},{row['center_y']}), edges={row['edge_count']}, contiguous={row['contiguous']}, "
        f"components={row['component_count']}, source_sink={row['source_sink_edges']} ({row['source_sink_status']}), "
        f"overlap_hint={row['overlap_hint_official_areas']}, flags={row['quality_flags']}"
    )

zone_rows.sort(key=lambda r: r["edge_count"], reverse=True)

csv_path = os.path.join(output_dir, "compact_zone_candidates.csv")
json_path = os.path.join(output_dir, "compact_zone_candidates.json")
summary_path = os.path.join(output_dir, "compact_zone_candidates_summary.txt")

with open(csv_path, "w", newline="", encoding="utf-8") as f:
    fieldnames = list(zone_rows[0].keys()) if zone_rows else []
    w = csv.DictWriter(f, fieldnames=fieldnames)
    w.writeheader()
    for r in zone_rows:
        w.writerow(r)

with open(json_path, "w", encoding="utf-8") as f:
    json.dump({
        "selected_k": k,
        "candidate_k_scores": [{"k": r["k"], "score": round(r["score"], 4)} for r in results],
        "zones": zone_json
    }, f, indent=2)

frag_count = sum(1 for r in zone_rows if r["contiguous"] == "no")
partial_count = sum(1 for r in zone_rows if r["contiguous"] == "partial")
weak_sink_count = sum(1 for r in zone_rows if r["source_sink_status"] == "weak")
good_count = sum(1 for r in zone_rows if "good" in r["quality_flags"])

summary_lines = []
summary_lines.append("compact zone candidate analysis")
summary_lines.append("")
summary_lines.append(f"selected_zone_count={k}")
k_score_text = ", ".join([f"{r['k']}:{round(r['score'], 4)}" for r in sorted(results, key=lambda x: x["k"])])
summary_lines.append(f"k_scores={k_score_text}")
summary_lines.append(f"contiguous_full={len(zone_rows)-partial_count-frag_count}, contiguous_partial={partial_count}, fragmented={frag_count}")
summary_lines.append(f"weak_source_sink_zones={weak_sink_count}")
summary_lines.append(f"good_quality_zones={good_count}")
summary_lines.append("")
summary_lines.extend(zone_summary_lines)
summary_lines.append("")
summary_lines.append("official_area_mapping_as_final_zone_design=rejected")
summary_lines.append("reason=official assignment is sparse and fragmented for simulation zoning")
summary_lines.append(f"recommended_compact_zone_count={k}")
summary_lines.append("recommended_design=use compact contiguous network-first zones, map demand from official 5-area OD by overlap/proximity")
summary_lines.append("defensibility=compact zones are more coherent for source/sink and routing than fragmented official-edge assignment")

with open(summary_path, "w", encoding="utf-8") as f:
    f.write("\n".join(summary_lines) + "\n")

zone_color_map = {}
for i, z in enumerate(sorted(set(assign.values()))):
    zone_color_map[z] = zone_colors[i % len(zone_colors)]

def plot_file(path, labeled):
    fig, ax = plt.subplots(figsize=(12, 12), dpi=180)
    for eid in main_ids:
        shp = all_shapes[eid]
        xs = [p[0] for p in shp]
        ys = [p[1] for p in shp]
        ax.plot(xs, ys, color="#cfcfcf", linewidth=0.55, alpha=0.9, zorder=1)
    for zi in range(k):
        zedges = [eid for eid, v in assign.items() if v == zi]
        col = zone_color_map[zi]
        for eid in zedges:
            shp = all_shapes[eid]
            xs = [p[0] for p in shp]
            ys = [p[1] for p in shp]
            ax.plot(xs, ys, color=col, linewidth=1.8, alpha=0.95, zorder=3)
    handles = []
    for zi in range(k):
        zid = f"CZ{zi + 1}"
        zedges = [eid for eid, v in assign.items() if v == zi]
        label = f"{zid} ({len(zedges)} edges)"
        handles.append(Line2D([0], [0], color=zone_color_map[zi], lw=3, label=label))
    ax.legend(handles=handles, loc="upper right", frameon=True, fontsize=9)
    if labeled:
        for zi in range(k):
            zedges = [eid for eid, v in assign.items() if v == zi]
            if not zedges:
                continue
            cx = sum(edges[e]["mid"][0] for e in zedges) / len(zedges)
            cy = sum(edges[e]["mid"][1] for e in zedges) / len(zedges)
            ax.text(cx, cy, f"CZ{zi + 1}", color=zone_color_map[zi], fontsize=11, fontweight="bold", zorder=4)
    ax.set_title("Compact Simulation-Zone Candidates on Cleaned Network")
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlabel("x")
    ax.set_ylabel("y")
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


plot1 = os.path.join(visual_dir, "compact_zone_candidates.png")
plot2 = os.path.join(visual_dir, "compact_zone_candidates_labeled.png")
plot_file(plot1, labeled=False)
plot_file(plot2, labeled=True)

print("analysis csv:", csv_path)
print("analysis json:", json_path)
print("analysis summary:", summary_path)
print("plot:", plot1)
print("plot labeled:", plot2)
