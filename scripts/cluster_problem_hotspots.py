import csv
import json
import math
from pathlib import Path
from collections import Counter

root = Path(r"E:\project_sakif_chicago")
in_csv = root / "output" / "problem_junctions.csv"
out_csv = root / "output" / "problem_hotspots.csv"
out_json = root / "output" / "problem_hotspots.json"
out_summary = root / "output" / "problem_hotspots_summary.txt"
out_top = root / "output" / "problem_hotspots_top.txt"

if not in_csv.exists():
    print("missing input:", in_csv)
    raise SystemExit(1)

rows = []
with in_csv.open(newline="", encoding="utf-8") as f:
    r = csv.DictReader(f)
    for row in r:
        try:
            rows.append({
                "junction_id": row["junction_id"],
                "x": float(row["x"]),
                "y": float(row["y"]),
                "score": float(row["score"]),
                "reasons": row["reasons"],
                "junction_type": row["junction_type"],
            })
        except Exception:
            pass

if len(rows) < 3:
    print("not enough rows")
    raise SystemExit(1)

points = [(r["x"], r["y"]) for r in rows]


def run_kmeans(points, k, max_iter=30):
    n = len(points)
    sorted_idx = sorted(range(n), key=lambda i: (points[i][0], points[i][1]))
    centers = []
    for j in range(k):
        idx = sorted_idx[int((j + 0.5) * n / k)]
        centers.append([points[idx][0], points[idx][1]])

    assign = [0] * n
    for _ in range(max_iter):
        changed = False
        for i, (x, y) in enumerate(points):
            best_c = 0
            best_d2 = None
            for c, (cx, cy) in enumerate(centers):
                dx = x - cx
                dy = y - cy
                d2 = dx * dx + dy * dy
                if best_d2 is None or d2 < best_d2:
                    best_d2 = d2
                    best_c = c
            if assign[i] != best_c:
                assign[i] = best_c
                changed = True

        sums_x = [0.0] * k
        sums_y = [0.0] * k
        counts = [0] * k
        for i, (x, y) in enumerate(points):
            c = assign[i]
            sums_x[c] += x
            sums_y[c] += y
            counts[c] += 1

        for c in range(k):
            if counts[c] > 0:
                centers[c][0] = sums_x[c] / counts[c]
                centers[c][1] = sums_y[c] / counts[c]

        if not changed:
            break

    clusters = [[] for _ in range(k)]
    for i, c in enumerate(assign):
        clusters[c].append(i)

    clusters = [c for c in clusters if c]
    centers2 = []
    for c in clusters:
        cx = sum(points[i][0] for i in c) / len(c)
        cy = sum(points[i][1] for i in c) / len(c)
        centers2.append((cx, cy))

    within_sum = 0.0
    within_count = 0
    for cidx, c in enumerate(clusters):
        cx, cy = centers2[cidx]
        for i in c:
            dx = points[i][0] - cx
            dy = points[i][1] - cy
            within_sum += math.hypot(dx, dy)
            within_count += 1
    within_avg = within_sum / max(1, within_count)

    if len(centers2) >= 2:
        sep_vals = []
        for i in range(len(centers2)):
            best = None
            for j in range(len(centers2)):
                if i == j:
                    continue
                dx = centers2[i][0] - centers2[j][0]
                dy = centers2[i][1] - centers2[j][1]
                d = math.hypot(dx, dy)
                if best is None or d < best:
                    best = d
            sep_vals.append(best)
        sep = sum(sep_vals) / len(sep_vals)
    else:
        sep = 0.0

    quality = sep / (within_avg + 1e-6)
    return clusters, centers2, within_avg, sep, quality


best = None
for k in range(3, 9):
    clusters, centers, within_avg, sep, quality = run_kmeans(points, k)
    data = {
        "k": k,
        "clusters": clusters,
        "centers": centers,
        "within_avg": within_avg,
        "sep": sep,
        "quality": quality,
    }
    if best is None or data["quality"] > best["quality"]:
        best = data

clusters = best["clusters"]

hotspots = []
for idx, c in enumerate(clusters, start=1):
    pts = [rows[i] for i in c]
    count = len(pts)
    cx = sum(p["x"] for p in pts) / count
    cy = sum(p["y"] for p in pts) / count

    minx = min(p["x"] for p in pts)
    maxx = max(p["x"] for p in pts)
    miny = min(p["y"] for p in pts)
    maxy = max(p["y"] for p in pts)
    span_x = maxx - minx
    span_y = maxy - miny
    diag = math.hypot(span_x, span_y)

    pts_sorted = sorted(pts, key=lambda p: p["score"], reverse=True)
    top_ids = [p["junction_id"] for p in pts_sorted[:8]]

    reason_counter = Counter()
    for p in pts:
        for reason in p["reasons"].split(";"):
            rr = reason.strip()
            if rr:
                reason_counter[rr.split(":")[0]] += 1
    dominant_reasons = [k for k, _ in reason_counter.most_common(4)]

    tl_count = sum(1 for p in pts if p["junction_type"] == "traffic_light")
    dead_end_count = sum(1 for p in pts if p["junction_type"] == "dead_end")
    avg_score = sum(p["score"] for p in pts) / count
    max_score = pts_sorted[0]["score"]

    if diag <= 220 and count <= 120:
        area_type = "local geometry problem"
    elif diag <= 420 and count <= 260:
        area_type = "mixed local cluster"
    else:
        area_type = "broader area"

    priority = count * 1.0 + avg_score * 3.0 + max_score * 1.5

    hotspots.append({
        "hotspot_id": f"HS{idx}",
        "center_x": round(cx, 3),
        "center_y": round(cy, 3),
        "junction_count": count,
        "avg_score": round(avg_score, 3),
        "max_score": round(max_score, 3),
        "diag_span": round(diag, 3),
        "traffic_light_count": tl_count,
        "dead_end_count": dead_end_count,
        "dominant_reasons": dominant_reasons,
        "top_junction_ids": top_ids,
        "area_type": area_type,
        "priority": round(priority, 3),
    })

hotspots.sort(key=lambda h: h["priority"], reverse=True)
for i, h in enumerate(hotspots, start=1):
    h["rank"] = i

with out_csv.open("w", newline="", encoding="utf-8") as f:
    fields = [
        "rank",
        "hotspot_id",
        "center_x",
        "center_y",
        "junction_count",
        "avg_score",
        "max_score",
        "diag_span",
        "traffic_light_count",
        "dead_end_count",
        "area_type",
        "priority",
        "dominant_reasons",
        "top_junction_ids",
    ]
    w = csv.DictWriter(f, fieldnames=fields)
    w.writeheader()
    for h in hotspots:
        row = dict(h)
        row["dominant_reasons"] = ";".join(h["dominant_reasons"])
        row["top_junction_ids"] = ";".join(h["top_junction_ids"])
        w.writerow(row)

with out_json.open("w", encoding="utf-8") as f:
    json.dump({
        "method": "kmeans",
        "k": best["k"],
        "within_avg": round(best["within_avg"], 3),
        "separation": round(best["sep"], 3),
        "quality": round(best["quality"], 3),
        "hotspots": hotspots,
    }, f, indent=2)

lines = []
lines.append("Problem hotspot summary")
lines.append("")
lines.append("Input: " + str(in_csv))
lines.append("Flagged junctions used: " + str(len(rows)))
lines.append("Clustering method: k-means on x/y coordinates")
lines.append("k search range: 3..8")
lines.append("Chosen k: " + str(best["k"]))
lines.append("Within-cluster avg distance: " + str(round(best["within_avg"], 3)))
lines.append("Cluster separation score: " + str(round(best["sep"], 3)))
lines.append("")
lines.append("Interpretation:")
lines.append("- local geometry problem: compact cluster likely one local artifact")
lines.append("- mixed local cluster: medium-size area with related issues")
lines.append("- broader area: larger zone for staged cleanup")
lines.append("")
lines.append("Ranked hotspots:")
for h in hotspots:
    lines.append(
        f"{h['rank']}. {h['hotspot_id']} center=({h['center_x']}, {h['center_y']}) count={h['junction_count']} area={h['area_type']} reasons={','.join(h['dominant_reasons'])} top={','.join(h['top_junction_ids'][:5])}"
    )
out_summary.write_text("\n".join(lines), encoding="utf-8")

with out_top.open("w", encoding="utf-8") as f:
    for h in hotspots[:5]:
        f.write(f"{h['hotspot_id']} center=({h['center_x']},{h['center_y']}) top={','.join(h['top_junction_ids'][:5])}\n")

print("done")
print("k", best["k"])
print("hotspots", len(hotspots))
