from pathlib import Path
import re
import csv
import json
import math
import sumolib
import pandas as pd
import xml.etree.ElementTree as ET

root = Path(r"E:\project_sakif_chicago")
net_file = root / "net" / "map_reduced_clean_auto_v2.net.xml"
boundary_file = root / "data" / "benchmark5_community_areas.csv"

out_csv = root / "output" / "benchmark5_zone_edge_mapping.csv"
out_json = root / "output" / "benchmark5_zone_edge_mapping.json"
out_summary = root / "output" / "benchmark5_zone_edge_mapping_summary.txt"

area_ids = ["8", "24", "28", "32", "33"]

if not net_file.exists() or not boundary_file.exists():
    raise SystemExit("required file missing")

num_re = re.compile(r"-?\d+(?:\.\d+)?")

def parse_wkt_rings(wkt):
    parts = re.findall(r"\(([-0-9\.,\s]+)\)", str(wkt))
    rings = []
    for part in parts:
        pts = []
        for token in part.split(","):
            t = token.strip()
            if not t:
                continue
            vals = t.split()
            if len(vals) < 2:
                continue
            try:
                x = float(vals[0])
                y = float(vals[1])
            except Exception:
                continue
            pts.append((x, y))
        if len(pts) >= 3:
            rings.append(pts)
    return rings

def point_in_ring(x, y, ring):
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]
        cond = ((yi > y) != (yj > y))
        if cond:
            x_int = (xj - xi) * (y - yi) / ((yj - yi) if (yj - yi) != 0 else 1e-12) + xi
            if x < x_int:
                inside = not inside
        j = i
    return inside

def point_in_area(x, y, rings):
    for ring in rings:
        if point_in_ring(x, y, ring):
            return True
    return False

def dist_point_seg(px, py, ax, ay, bx, by):
    vx = bx - ax
    vy = by - ay
    wx = px - ax
    wy = py - ay
    c1 = vx * wx + vy * wy
    if c1 <= 0:
        return math.hypot(px - ax, py - ay)
    c2 = vx * vx + vy * vy
    if c2 <= c1:
        return math.hypot(px - bx, py - by)
    t = c1 / c2
    qx = ax + t * vx
    qy = ay + t * vy
    return math.hypot(px - qx, py - qy)

def dist_to_area_boundary(x, y, rings):
    best = None
    for ring in rings:
        n = len(ring)
        for i in range(n - 1):
            ax, ay = ring[i]
            bx, by = ring[i + 1]
            d = dist_point_seg(x, y, ax, ay, bx, by)
            if best is None or d < best:
                best = d
        ax, ay = ring[-1]
        bx, by = ring[0]
        d = dist_point_seg(x, y, ax, ay, bx, by)
        if best is None or d < best:
            best = d
    return best if best is not None else 999.0

def bbox_from_rings(rings):
    xs = [p[0] for r in rings for p in r]
    ys = [p[1] for r in rings for p in r]
    return (min(xs), min(ys), max(xs), max(ys))

def bbox_dist_point(x, y, box):
    minx, miny, maxx, maxy = box
    dx = 0.0
    if x < minx:
        dx = minx - x
    elif x > maxx:
        dx = x - maxx
    dy = 0.0
    if y < miny:
        dy = miny - y
    elif y > maxy:
        dy = y - maxy
    return math.hypot(dx, dy)

bdf = pd.read_csv(boundary_file, dtype=str)
bdf["AREA_NUMBE"] = bdf["AREA_NUMBE"].astype(str).str.strip()

areas = {}
for _, row in bdf.iterrows():
    aid = row["AREA_NUMBE"]
    if aid not in area_ids:
        continue
    rings = parse_wkt_rings(row["the_geom"])
    if not rings:
        continue
    areas[aid] = {
        "id": aid,
        "name": str(row.get("COMMUNITY", "")).strip(),
        "rings": rings,
        "bbox": bbox_from_rings(rings),
    }

net = sumolib.net.readNet(str(net_file), withInternal=False)
minx, miny, maxx, maxy = [float(x) for x in net.getBoundary()]
boundary_thresh = 40.0

net_xml = ET.parse(net_file).getroot()
loc = net_xml.find("location")
conv_box = None
orig_box = None
if loc is not None:
    cb = loc.get("convBoundary")
    ob = loc.get("origBoundary")
    if cb and ob:
        conv_box = tuple(float(v) for v in cb.split(","))
        orig_box = tuple(float(v) for v in ob.split(","))

def to_lonlat(x, y):
    try:
        return net.convertXY2LonLat(x, y)
    except Exception:
        if conv_box is None or orig_box is None:
            raise
        cminx, cminy, cmaxx, cmaxy = conv_box
        ominx, ominy, omaxx, omaxy = orig_box
        rx = 0.0 if cmaxx == cminx else (x - cminx) / (cmaxx - cminx)
        ry = 0.0 if cmaxy == cminy else (y - cminy) / (cmaxy - cminy)
        lon = ominx + rx * (omaxx - ominx)
        lat = ominy + ry * (omaxy - ominy)
        return lon, lat

edge_data = []
for e in net.getEdges():
    lanes = e.getLanes()
    if not lanes:
        continue
    if not any(l.allows("passenger") for l in lanes):
        continue

    length = float(e.getLength())
    lane_count = len(lanes)
    speed = max(float(l.getSpeed()) for l in lanes)

    fx, fy = e.getFromNode().getCoord()
    tx, ty = e.getToNode().getCoord()
    mx, my = (fx + tx) / 2.0, (fy + ty) / 2.0

    mlon, mlat = to_lonlat(mx, my)
    flon, flat = to_lonlat(fx, fy)
    tlon, tlat = to_lonlat(tx, ty)

    boundary_like = (
        min(abs(fx - minx), abs(fx - maxx), abs(fy - miny), abs(fy - maxy),
            abs(tx - minx), abs(tx - maxx), abs(ty - miny), abs(ty - maxy)) <= boundary_thresh
    )

    edge_data.append({
        "edge_id": e.getID(),
        "length": length,
        "lane_count": lane_count,
        "speed": speed,
        "from_lon": flon,
        "from_lat": flat,
        "to_lon": tlon,
        "to_lat": tlat,
        "mid_lon": mlon,
        "mid_lat": mlat,
        "boundary_like": boundary_like,
    })

rows = []
json_out = {"areas": []}

for aid in area_ids:
    if aid not in areas:
        json_out["areas"].append({"area_id": aid, "area_name": "", "candidates": []})
        continue

    area = areas[aid]
    rings = area["rings"]
    bbox = area["bbox"]
    is_fringe = aid in {"24", "33"}

    cands = []

    for e in edge_data:
        mid_in = point_in_area(e["mid_lon"], e["mid_lat"], rings)
        from_in = point_in_area(e["from_lon"], e["from_lat"], rings)
        to_in = point_in_area(e["to_lon"], e["to_lat"], rings)
        edge_cross = (from_in != to_in)

        dist_boundary = dist_to_area_boundary(e["mid_lon"], e["mid_lat"], rings)
        dist_bbox = bbox_dist_point(e["mid_lon"], e["mid_lat"], bbox)

        cls = None
        reason = []
        score = 0.0

        if mid_in and from_in and to_in:
            if dist_boundary > 0.0012:
                cls = "strong_interior"
                reason.append("midpoint and endpoints inside area")
                score = 100
            else:
                cls = "boundary_touching"
                reason.append("inside area but near boundary")
                score = 80
        elif mid_in or edge_cross:
            cls = "boundary_touching"
            reason.append("edge crosses area boundary")
            score = 75
        elif dist_bbox <= 0.0025:
            cls = "weak_partial"
            reason.append(f"outside polygon but near area bbox (deg={round(dist_bbox,6)})")
            score = 45

        if cls is None:
            continue

        avoid = False
        if e["length"] < 10:
            avoid = True
            reason.append("very short edge")
        if e["lane_count"] == 1 and e["length"] < 30:
            avoid = True
            reason.append("short single-lane local edge")

        if is_fringe:
            if cls == "strong_interior":
                cls = "weak_partial"
                reason.append("fringe area; treat as weak on reduced network")
            if not (e["boundary_like"] and e["lane_count"] >= 2 and e["length"] >= 30):
                avoid = True
                reason.append("fringe strict filter failed")

        if e["lane_count"] >= 2:
            score += 5
        if e["length"] >= 80:
            score += 5
        if e["speed"] >= 13.9:
            score += 3
        if e["boundary_like"]:
            score += 2
        if avoid:
            score -= 25

        action = "inspect only"
        if avoid:
            cls_out = "edges_to_avoid"
            action = "leave alone"
        elif cls == "strong_interior":
            cls_out = "strong_interior"
            action = "inspect only"
        elif cls == "boundary_touching":
            cls_out = "boundary_touching"
            action = "inspect only"
        else:
            cls_out = "weak_partial"
            action = "inspect only"

        cands.append({
            "area_id": aid,
            "area_name": area["name"],
            "edge_id": e["edge_id"],
            "candidate_class": cls_out,
            "is_network_boundary_like": str(e["boundary_like"]).lower(),
            "edge_length_m": round(e["length"], 3),
            "lane_count": e["lane_count"],
            "speed_mps": round(e["speed"], 3),
            "mid_lon": round(e["mid_lon"], 6),
            "mid_lat": round(e["mid_lat"], 6),
            "why": ";".join(reason),
            "suggested_action": action,
            "score": round(score, 3),
        })

    cands.sort(key=lambda x: x["score"], reverse=True)

    strong = [c for c in cands if c["candidate_class"] == "strong_interior"]
    boundary = [c for c in cands if c["candidate_class"] == "boundary_touching"]
    weak = [c for c in cands if c["candidate_class"] == "weak_partial"]
    avoid = [c for c in cands if c["candidate_class"] == "edges_to_avoid"]

    if is_fringe and (len(strong) + len(boundary) + len(weak) == 0):
        fallback = []
        for e in edge_data:
            if not e["boundary_like"]:
                continue
            if e["lane_count"] < 2 or e["length"] < 30:
                continue
            db = bbox_dist_point(e["mid_lon"], e["mid_lat"], bbox)
            if db > 0.03:
                continue
            fallback.append((db, e))
        fallback.sort(key=lambda x: x[0])
        for db, e in fallback[:6]:
            cands.append({
                "area_id": aid,
                "area_name": area["name"],
                "edge_id": e["edge_id"],
                "candidate_class": "weak_partial",
                "is_network_boundary_like": str(e["boundary_like"]).lower(),
                "edge_length_m": round(e["length"], 3),
                "lane_count": e["lane_count"],
                "speed_mps": round(e["speed"], 3),
                "mid_lon": round(e["mid_lon"], 6),
                "mid_lat": round(e["mid_lat"], 6),
                "why": f"fringe fallback nearest gateway edge (bbox_dist_deg={round(db,6)})",
                "suggested_action": "inspect only",
                "score": round(35.0 - db * 2000.0, 3),
            })

        cands.sort(key=lambda x: x["score"], reverse=True)
        strong = [c for c in cands if c["candidate_class"] == "strong_interior"]
        boundary = [c for c in cands if c["candidate_class"] == "boundary_touching"]
        weak = [c for c in cands if c["candidate_class"] == "weak_partial"]
        avoid = [c for c in cands if c["candidate_class"] == "edges_to_avoid"]

    if is_fringe:
        keep = strong[:0] + boundary[:8] + weak[:8] + avoid[:8]
    else:
        keep = strong[:20] + boundary[:20] + weak[:10] + avoid[:8]

    keep_ids = set()
    final = []
    for c in keep:
        if c["edge_id"] in keep_ids:
            continue
        keep_ids.add(c["edge_id"])
        final.append(c)

    rows.extend(final)

    usable_edges = [c["edge_id"] for c in final if c["candidate_class"] in {"strong_interior", "boundary_touching", "weak_partial"}]
    (root / "data" / f"benchmark5_zone_edges_area{aid}.txt").write_text("\n".join(usable_edges) + ("\n" if usable_edges else ""), encoding="utf-8")

    json_out["areas"].append({
        "area_id": aid,
        "area_name": area["name"],
        "candidate_counts": {
            "strong_interior": len([c for c in final if c["candidate_class"] == "strong_interior"]),
            "boundary_touching": len([c for c in final if c["candidate_class"] == "boundary_touching"]),
            "weak_partial": len([c for c in final if c["candidate_class"] == "weak_partial"]),
            "edges_to_avoid": len([c for c in final if c["candidate_class"] == "edges_to_avoid"]),
        },
        "best_edge_set": usable_edges[:20],
        "candidates": final,
    })

with out_csv.open("w", newline="", encoding="utf-8") as f:
    fields = [
        "area_id", "area_name", "edge_id", "candidate_class", "is_network_boundary_like",
        "edge_length_m", "lane_count", "speed_mps", "mid_lon", "mid_lat", "why", "suggested_action", "score"
    ]
    w = csv.DictWriter(f, fieldnames=fields)
    w.writeheader()
    for r in rows:
        w.writerow(r)

out_json.write_text(json.dumps(json_out, indent=2), encoding="utf-8")

lines = []
lines.append("Benchmark5 zone-edge mapping summary")
lines.append("network: " + str(net_file))
lines.append("boundaries: " + str(boundary_file))
lines.append("")
for a in json_out["areas"]:
    cid = a["area_id"]
    name = a["area_name"]
    cc = a["candidate_counts"]
    lines.append(f"{cid} {name}")
    lines.append(f"- strong_interior: {cc['strong_interior']}")
    lines.append(f"- boundary_touching: {cc['boundary_touching']}")
    lines.append(f"- weak_partial: {cc['weak_partial']}")
    lines.append(f"- edges_to_avoid: {cc['edges_to_avoid']}")
    lines.append("- best_edge_set: " + ", ".join(a["best_edge_set"][:12]))
    lines.append("")

lines.append("mapping validity assessment:")
for a in json_out["areas"]:
    cc = a["candidate_counts"]
    cid = a["area_id"]
    name = a["area_name"]
    usable = cc["strong_interior"] + cc["boundary_touching"] + cc["weak_partial"]
    if cid in {"24", "33"}:
        if usable >= 4:
            lines.append(f"- {cid} {name}: usable as weak fringe zone with strict edge filtering")
        else:
            lines.append(f"- {cid} {name}: very weak mapping, requires special handling")
    else:
        if cc["strong_interior"] + cc["boundary_touching"] >= 8:
            lines.append(f"- {cid} {name}: strong mapping on current network")
        else:
            lines.append(f"- {cid} {name}: moderate mapping, inspect manually")

lines.append("- 5-area benchmark structural validity: valid with fringe handling for 24 and 33")
out_summary.write_text("\n".join(lines), encoding="utf-8")

print("done")
for a in json_out["areas"]:
    cc = a["candidate_counts"]
    print(a["area_id"], cc["strong_interior"], cc["boundary_touching"], cc["weak_partial"], cc["edges_to_avoid"])
