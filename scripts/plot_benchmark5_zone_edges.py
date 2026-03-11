import os
import math
import json
import xml.etree.ElementTree as ET

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D


project_dir = r"E:\project_sakif_chicago"
network_file = os.path.join(project_dir, "net", "map_reduced_clean_auto_v2.net.xml")
visual_dir = os.path.join(project_dir, "visuals")
output_dir = os.path.join(project_dir, "output")

zone_files = {
    8: os.path.join(project_dir, "data", "benchmark5_zone_edges_area8_unique.txt"),
    24: os.path.join(project_dir, "data", "benchmark5_zone_edges_area24_unique.txt"),
    28: os.path.join(project_dir, "data", "benchmark5_zone_edges_area28_unique.txt"),
    32: os.path.join(project_dir, "data", "benchmark5_zone_edges_area32_unique.txt"),
    33: os.path.join(project_dir, "data", "benchmark5_zone_edges_area33_unique.txt"),
}

zone_names = {
    8: "NEAR NORTH SIDE",
    24: "WEST TOWN",
    28: "NEAR WEST SIDE",
    32: "LOOP",
    33: "NEAR SOUTH SIDE",
}

zone_colors = {
    8: "#d73027",
    24: "#4575b4",
    28: "#1a9850",
    32: "#fdae61",
    33: "#984ea3",
}


def parse_shape(text):
    if not text:
        return []
    pts = []
    for part in text.strip().split():
        if "," not in part:
            continue
        x, y = part.split(",", 1)
        try:
            pts.append((float(x), float(y)))
        except ValueError:
            pass
    return pts


def read_zone_edges(path):
    edges = []
    if not os.path.exists(path):
        return edges
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            edge_id = line.strip()
            if edge_id:
                edges.append(edge_id)
    return edges


def edge_midpoint(shape):
    if len(shape) == 0:
        return None
    if len(shape) == 1:
        return shape[0]
    total = 0.0
    segs = []
    for i in range(len(shape) - 1):
        x1, y1 = shape[i]
        x2, y2 = shape[i + 1]
        d = math.hypot(x2 - x1, y2 - y1)
        segs.append((d, (x1, y1), (x2, y2)))
        total += d
    if total == 0:
        return shape[len(shape) // 2]
    target = total / 2.0
    run = 0.0
    for d, p1, p2 in segs:
        if run + d >= target and d > 0:
            r = (target - run) / d
            return (p1[0] + r * (p2[0] - p1[0]), p1[1] + r * (p2[1] - p1[1]))
        run += d
    return shape[-1]


def connected_components(edge_ids, edge_nodes):
    if not edge_ids:
        return 0
    node_to_edges = {}
    for e in edge_ids:
        fn, tn = edge_nodes.get(e, (None, None))
        for n in (fn, tn):
            if n is None:
                continue
            node_to_edges.setdefault(n, set()).add(e)
    unseen = set(edge_ids)
    comps = 0
    while unseen:
        seed = next(iter(unseen))
        stack = [seed]
        unseen.remove(seed)
        while stack:
            e = stack.pop()
            fn, tn = edge_nodes.get(e, (None, None))
            for n in (fn, tn):
                if n is None:
                    continue
                for nb in node_to_edges.get(n, set()):
                    if nb in unseen:
                        unseen.remove(nb)
                        stack.append(nb)
        comps += 1
    return comps


os.makedirs(visual_dir, exist_ok=True)
os.makedirs(output_dir, exist_ok=True)

tree = ET.parse(network_file)
root = tree.getroot()

all_shapes = []
edge_shape = {}
edge_nodes = {}

for edge in root.findall("edge"):
    edge_id = edge.get("id", "")
    if edge_id.startswith(":"):
        continue
    fn = edge.get("from")
    tn = edge.get("to")
    edge_nodes[edge_id] = (fn, tn)
    lane = edge.find("lane")
    shape = []
    if lane is not None:
        shape = parse_shape(lane.get("shape", ""))
    if not shape:
        shape = parse_shape(edge.get("shape", ""))
    if shape:
        edge_shape[edge_id] = shape
        all_shapes.append(shape)

zone_edges = {z: read_zone_edges(p) for z, p in zone_files.items()}

def draw(include_labels):
    fig, ax = plt.subplots(figsize=(12, 12), dpi=180)
    for shp in all_shapes:
        xs = [p[0] for p in shp]
        ys = [p[1] for p in shp]
        ax.plot(xs, ys, color="#c9c9c9", linewidth=0.5, alpha=0.8, zorder=1)
    zone_centers = {}
    for z in [8, 24, 28, 32, 33]:
        pts = []
        for e in zone_edges.get(z, []):
            shp = edge_shape.get(e)
            if not shp:
                continue
            xs = [p[0] for p in shp]
            ys = [p[1] for p in shp]
            ax.plot(xs, ys, color=zone_colors[z], linewidth=2.3, alpha=0.95, zorder=3)
            mid = edge_midpoint(shp)
            if mid:
                pts.append(mid)
        if pts:
            cx = sum(p[0] for p in pts) / len(pts)
            cy = sum(p[1] for p in pts) / len(pts)
            zone_centers[z] = (cx, cy)
    if include_labels:
        for z, c in zone_centers.items():
            label = f"{z} {zone_names[z]}"
            ax.text(c[0], c[1], label, fontsize=9, weight="bold", color=zone_colors[z], zorder=4)
    legend_items = []
    for z in [8, 24, 28, 32, 33]:
        legend_items.append(Line2D([0], [0], color=zone_colors[z], lw=3, label=f"{z} {zone_names[z]}"))
    ax.legend(handles=legend_items, loc="upper right", frameon=True, fontsize=9)
    ax.set_title("Benchmark5 Zone-Edge Assignments on Cleaned Network")
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlabel("x")
    ax.set_ylabel("y")
    ax.grid(False)
    return fig, zone_centers


fig1, centers = draw(include_labels=False)
png1 = os.path.join(visual_dir, "benchmark5_zone_edges.png")
fig1.savefig(png1, bbox_inches="tight")
plt.close(fig1)

fig2, _ = draw(include_labels=True)
png2 = os.path.join(visual_dir, "benchmark5_zone_edges_labeled.png")
fig2.savefig(png2, bbox_inches="tight")
plt.close(fig2)

summary_path = os.path.join(output_dir, "benchmark5_zone_visual_check.txt")
summary = []
summary.append("benchmark5 zone visual check")
summary.append("")

result_json = {
    "zone_counts": {},
    "zone_centers": {},
    "zone_flags": {},
    "files": {
        "plot": png1,
        "plot_labeled": png2,
    },
}

for z in [8, 24, 28, 32, 33]:
    existing = [e for e in zone_edges.get(z, []) if e in edge_shape]
    cnt = len(existing)
    comps = connected_components(existing, edge_nodes)
    center = centers.get(z)
    if center:
        center_txt = f"({center[0]:.3f}, {center[1]:.3f})"
        result_json["zone_centers"][str(z)] = {"x": round(center[0], 3), "y": round(center[1], 3)}
    else:
        center_txt = "n/a"
        result_json["zone_centers"][str(z)] = None
    flags = []
    if cnt < 3:
        flags.append("too few edges")
    if comps > 1:
        flags.append(f"disconnected groups={comps}")
    if not flags:
        flags.append("looks coherent")
    result_json["zone_counts"][str(z)] = cnt
    result_json["zone_flags"][str(z)] = flags
    summary.append(f"{z} {zone_names[z]}: count={cnt}, center={center_txt}, status={'; '.join(flags)}")

with open(summary_path, "w", encoding="utf-8") as f:
    f.write("\n".join(summary) + "\n")

json_path = os.path.join(output_dir, "benchmark5_zone_visual_check.json")
with open(json_path, "w", encoding="utf-8") as f:
    json.dump(result_json, f, indent=2)

print("plot created:", png1)
print("plot created:", png2)
print("summary created:", summary_path)
print("summary json created:", json_path)
