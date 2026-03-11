from pathlib import Path
import csv
import json
import re
import math
import xml.etree.ElementTree as ET
import pandas as pd
import sumolib

root = Path(r"E:\project_sakif_chicago")
net_file = root / "net" / "map_reduced_clean_auto_v2.net.xml"
boundary_file = root / "data" / "benchmark5_community_areas.csv"
mapping_csv = root / "output" / "benchmark5_zone_edge_mapping.csv"

final_in = {
    "8": root / "data" / "benchmark5_zone_edges_area8_final.txt",
    "24": root / "data" / "benchmark5_zone_edges_area24_final.txt",
    "28": root / "data" / "benchmark5_zone_edges_area28_final.txt",
    "32": root / "data" / "benchmark5_zone_edges_area32_final.txt",
    "33": root / "data" / "benchmark5_zone_edges_area33_final.txt",
}

final_out = {
    "8": root / "data" / "benchmark5_zone_edges_area8_unique.txt",
    "24": root / "data" / "benchmark5_zone_edges_area24_unique.txt",
    "28": root / "data" / "benchmark5_zone_edges_area28_unique.txt",
    "32": root / "data" / "benchmark5_zone_edges_area32_unique.txt",
    "33": root / "data" / "benchmark5_zone_edges_area33_unique.txt",
}

out_csv = root / "output" / "benchmark5_zone_edge_unique.csv"
out_json = root / "output" / "benchmark5_zone_edge_unique.json"
out_txt = root / "output" / "benchmark5_zone_edge_unique_summary.txt"

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
min_needed = {
    "8": 6,
    "24": 3,
    "28": 6,
    "32": 8,
    "33": 3,
}
target_max = {
    "8": 8,
    "24": 4,
    "28": 8,
    "32": 12,
    "33": 4,
}

for p in [net_file, boundary_file, mapping_csv, *final_in.values()]:
    if not p.exists():
        raise SystemExit(f"missing file: {p}")

num_re = re.compile(r"-?\d+(?:\.\d+)?")

def parse_wkt_rings(wkt):
    parts = re.findall(r"\(([-0-9\.,\s]+)\)", str(wkt))
    rings = []
    for part in parts:
        pts = []
        for tok in part.split(","):
            t = tok.strip()
            if not t:
                continue
            vals = t.split()
            if len(vals) < 2:
                continue
            try:
                x = float(vals[0]); y = float(vals[1])
            except Exception:
                continue
            pts.append((x, y))
        if len(pts) >= 3:
            rings.append(pts)
    return rings

def point_in_ring(x, y, ring):
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if ((yi > y) != (yj > y)):
            xint = (xj - xi) * (y - yi) / ((yj - yi) if (yj - yi) != 0 else 1e-12) + xi
            if x < xint:
                inside = not inside
        j = i
    return inside

def point_in_area(x, y, rings):
    for r in rings:
        if point_in_ring(x, y, r):
            return True
    return False

def bbox_from_rings(rings):
    xs = [p[0] for r in rings for p in r]
    ys = [p[1] for r in rings for p in r]
    return (min(xs), min(ys), max(xs), max(ys))

def bbox_dist(x, y, box):
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
for _, r in bdf.iterrows():
    aid = r["AREA_NUMBE"]
    if aid not in area_name:
        continue
    rings = parse_wkt_rings(r.get("the_geom", ""))
    if rings:
        areas[aid] = {"rings": rings, "bbox": bbox_from_rings(rings)}

net = sumolib.net.readNet(str(net_file), withInternal=False)
net_xml = ET.parse(net_file).getroot()
loc = net_xml.find("location")
conv_box = tuple(float(v) for v in loc.get("convBoundary").split(",")) if loc is not None and loc.get("convBoundary") else None
orig_box = tuple(float(v) for v in loc.get("origBoundary").split(",")) if loc is not None and loc.get("origBoundary") else None
nminx, nminy, nmaxx, nmaxy = [float(v) for v in net.getBoundary()]
boundary_thresh_xy = 40.0

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

edge_info = {}
for e in net.getEdges():
    eid = e.getID()
    lanes = e.getLanes()
    if not lanes:
        continue
    fx, fy = e.getFromNode().getCoord(); tx, ty = e.getToNode().getCoord()
    mx, my = (fx + tx) / 2.0, (fy + ty) / 2.0
    mlon, mlat = to_lonlat(mx, my)
    edge_info[eid] = {
        "edge": e,
        "lane_count": len(lanes),
        "length": float(e.getLength()),
        "speed": max(float(l.getSpeed()) for l in lanes),
        "incoming": len(e.getIncoming()),
        "outgoing": len(e.getOutgoing()),
        "passenger": any(l.allows("passenger") for l in lanes),
        "boundary_like": min(abs(fx - nminx), abs(fx - nmaxx), abs(fy - nminy), abs(fy - nmaxy), abs(tx - nminx), abs(tx - nmaxx), abs(ty - nminy), abs(ty - nmaxy)) <= boundary_thresh_xy,
        "mid_lon": mlon,
        "mid_lat": mlat,
    }

existing_final = {}
for aid, p in final_in.items():
    vals = []
    for line in p.read_text(encoding="utf-8").splitlines():
        eid = line.strip()
        if eid:
            vals.append(eid)
    existing_final[aid] = set(vals)

map_df = pd.read_csv(mapping_csv, dtype=str)
map_df["score"] = pd.to_numeric(map_df["score"], errors="coerce").fillna(0.0)

# Build candidate pool per area from mapping csv (excluding explicit avoid class)
pool = {aid: {} for aid in area_name}
for _, r in map_df.iterrows():
    aid = str(r.get("area_id", "")).strip()
    eid = str(r.get("edge_id", "")).strip()
    cls = str(r.get("candidate_class", "")).strip()
    if aid not in pool or not eid or cls == "edges_to_avoid":
        continue
    if eid not in edge_info:
        continue
    info = edge_info[eid]
    if not info["passenger"]:
        continue
    if eid.startswith(":"):
        continue

    # strict suitability by area class
    ac = area_class[aid]
    ok = True
    reason = ""
    if ac == "interior":
        if info["length"] < 30 or info["speed"] < 5.0 or info["incoming"] == 0 or info["outgoing"] == 0:
            ok = False
            reason = "interior_filter_failed"
    elif ac == "partial":
        if info["length"] < 25 or info["speed"] < 4.0 or (info["incoming"] == 0 and info["outgoing"] == 0):
            ok = False
            reason = "partial_filter_failed"
    else:
        # fringe: strict gateway but allow one-side connectivity
        if info["lane_count"] < 2 or info["length"] < 45 or info["speed"] < 7.0:
            ok = False
            reason = "fringe_gateway_filter_failed"

    if not ok:
        continue

    base = float(r["score"])
    if eid in existing_final[aid]:
        base += 15.0

    inside = 1 if point_in_area(info["mid_lon"], info["mid_lat"], areas[aid]["rings"]) else 0
    base += inside * 12.0
    if info["boundary_like"]:
        base += 2.0
    base += min(6.0, info["lane_count"] * 1.5)

    old = pool[aid].get(eid)
    cand = {
        "edge_id": eid,
        "score": base,
        "inside": inside,
        "source_class": cls,
    }
    if old is None or cand["score"] > old["score"]:
        pool[aid][eid] = cand

# Area 33 strict expansion from full network if needed
if len(pool["33"]) < 6:
    for eid, info in edge_info.items():
        if eid in pool["33"]:
            continue
        if not info["passenger"]:
            continue
        if info["lane_count"] < 2 or info["length"] < 45 or info["speed"] < 7.0:
            continue
        # near area33 polygon by bbox distance proxy via inside check or boundary-like
        inside = 1 if point_in_area(info["mid_lon"], info["mid_lat"], areas["33"]["rings"]) else 0
        if not inside and not info["boundary_like"]:
            continue
        score = 20.0 + inside * 20.0 + info["lane_count"] * 1.2 + min(8.0, info["length"] / 20.0)
        pool["33"][eid] = {
            "edge_id": eid,
            "score": score,
            "inside": inside,
            "source_class": "fringe_extra",
        }

# Partial-area fallback expansion to reduce under-coverage due overlap constraints
for aid in ["8", "28"]:
    if len(pool[aid]) >= 20:
        continue
    rings = areas[aid]["rings"]
    box = areas[aid]["bbox"]
    for eid, info in edge_info.items():
        if eid in pool[aid]:
            continue
        if not info["passenger"]:
            continue
        if info["length"] < 20 or info["speed"] < 4.0:
            continue
        if info["incoming"] == 0 and info["outgoing"] == 0:
            continue
        inside = 1 if point_in_area(info["mid_lon"], info["mid_lat"], rings) else 0
        d = bbox_dist(info["mid_lon"], info["mid_lat"], box)
        if not inside and d > 0.02:
            continue
        score = 14.0 + inside * 10.0 + info["lane_count"] * 1.2 + min(8.0, info["length"] / 25.0) - d * 200.0
        if info["boundary_like"]:
            score += 1.0
        pool[aid][eid] = {
            "edge_id": eid,
            "score": score,
            "inside": inside,
            "source_class": "partial_extra",
        }

# Candidate counts
candidate_counts = {aid: len(pool[aid]) for aid in pool}

# Stage 1: satisfy minimum counts with slot-based bipartite matching
slot_candidates = {}
slots = []
for aid in ["8", "24", "28", "32", "33"]:
    cands = [c["edge_id"] for c in sorted(pool[aid].values(), key=lambda c: (-c["score"], c["edge_id"]))]
    for i in range(min_needed[aid]):
        sid = f"{aid}#{i}"
        slots.append((sid, aid))
        slot_candidates[sid] = cands

slots.sort(key=lambda x: (len(slot_candidates[x[0]]), int(x[1]), x[0]))

slot_to_edge = {}
edge_to_slot = {}

def try_match(slot_id, seen_edges):
    for eid in slot_candidates[slot_id]:
        if eid in seen_edges:
            continue
        seen_edges.add(eid)
        other_slot = edge_to_slot.get(eid)
        if other_slot is None:
            edge_to_slot[eid] = slot_id
            slot_to_edge[slot_id] = eid
            return True
        if try_match(other_slot, seen_edges):
            edge_to_slot[eid] = slot_id
            slot_to_edge[slot_id] = eid
            return True
    return False

for sid, _ in slots:
    if sid in slot_to_edge:
        continue
    try_match(sid, set())

assigned = {aid: [] for aid in area_name}
for sid, aid in slots:
    if sid in slot_to_edge:
        assigned[aid].append(slot_to_edge[sid])

used_edges = set()
for aid in assigned:
    for eid in assigned[aid]:
        used_edges.add(eid)

# Stage 2: fill up to target_max with remaining unique edges
for aid in ["8", "24", "28", "32", "33"]:
    cands = sorted(pool[aid].values(), key=lambda c: (-c["score"], c["edge_id"]))
    have = set(assigned[aid])
    for c in cands:
        if len(assigned[aid]) >= target_max[aid]:
            break
        eid = c["edge_id"]
        if eid in used_edges:
            continue
        if eid in have:
            continue
        assigned[aid].append(eid)
        used_edges.add(eid)
        have.add(eid)

# Deterministic ordering inside each area
for aid in assigned:
    assigned[aid].sort(key=lambda eid: (-edge_info[eid]["lane_count"], -edge_info[eid]["length"], eid))

# Added edges for 33 relative to current final file
added_to_33 = [eid for eid in assigned["33"] if eid not in existing_final["33"]]

# write unique files
for aid, p in final_out.items():
    vals = assigned[aid]
    p.write_text("\n".join(vals) + ("\n" if vals else ""), encoding="utf-8")

# build outputs
rows = []
for aid in ["8", "24", "28", "32", "33"]:
    for eid in assigned[aid]:
        info = edge_info[eid]
        rows.append({
            "area_id": aid,
            "area_name": area_name[aid],
            "area_class": area_class[aid],
            "edge_id": eid,
            "lane_count": info["lane_count"],
            "length_m": round(info["length"], 3),
            "speed_mps": round(info["speed"], 3),
            "incoming_conn_count": info["incoming"],
            "outgoing_conn_count": info["outgoing"],
            "boundary_like": str(info["boundary_like"]).lower(),
            "added_for_area33": "yes" if (aid == "33" and eid in added_to_33) else "no",
        })

with out_csv.open("w", newline="", encoding="utf-8") as f:
    fields = [
        "area_id", "area_name", "area_class", "edge_id", "lane_count", "length_m", "speed_mps",
        "incoming_conn_count", "outgoing_conn_count", "boundary_like", "added_for_area33"
    ]
    w = csv.DictWriter(f, fieldnames=fields)
    w.writeheader()
    for r in rows:
        w.writerow(r)

# overlap check
edge_owner = {}
for aid, eids in assigned.items():
    for eid in eids:
        edge_owner.setdefault(eid, []).append(aid)
remaining_overlap = {eid: v for eid, v in edge_owner.items() if len(v) > 1}

valid = {aid: (len(assigned[aid]) >= min_needed[aid]) for aid in assigned}
all_valid = all(valid.values())

json_out = {
    "network": str(net_file),
    "deterministic_rule": {
        "selection": "scarcity-first area ordering by candidate count, then descending candidate score, unique edge assignment",
        "score_components": "mapping score + existing-final preference + inside-polygon bonus + lane/boundary bonuses",
        "fringe_handling": "24 and 33 use strict gateway filters; area 33 expanded with strict fringe extra candidates",
    },
    "candidate_counts": candidate_counts,
    "min_required": min_needed,
    "target_max": target_max,
    "added_edges_area33": added_to_33,
    "unique_edge_counts": {aid: len(assigned[aid]) for aid in assigned},
    "area_valid": valid,
    "remaining_overlap_edges": remaining_overlap,
    "area_edges": assigned,
}
out_json.write_text(json.dumps(json_out, indent=2), encoding="utf-8")

lines = []
lines.append("Benchmark5 zone-edge unique summary")
lines.append("network: " + str(net_file))
lines.append("")
lines.append("deterministic rule used:")
lines.append("- candidate pool from benchmark5_zone_edge_mapping.csv (excluding edges_to_avoid)")
lines.append("- strict suitability filters by area class (interior/partial/fringe)")
lines.append("- uniqueness via scarcity-first assignment and score ranking")
lines.append("- each edge assigned to exactly one area")
lines.append("")
lines.append("added edges for area 33:")
if added_to_33:
    for eid in added_to_33:
        lines.append(f"- {eid}")
else:
    lines.append("- none")
lines.append("")
for aid in ["8", "24", "28", "32", "33"]:
    lines.append(f"{aid} {area_name[aid]}")
    lines.append(f"- class: {area_class[aid]}")
    lines.append(f"- candidate_pool_size: {candidate_counts[aid]}")
    lines.append(f"- min_required: {min_needed[aid]}")
    lines.append(f"- final_unique_count: {len(assigned[aid])}")
    lines.append(f"- valid: {'yes' if valid[aid] else 'no'}")
    lines.append("- edges: " + ", ".join(assigned[aid]))
    lines.append("")

lines.append(f"remaining_overlap_count: {len(remaining_overlap)}")
lines.append(f"area33_valid: {'yes' if valid['33'] else 'no'}")
lines.append(f"all_5_areas_valid: {'yes' if all_valid else 'no'}")
lines.append(f"next_step_final_taz_creation: {'yes' if all_valid and len(remaining_overlap)==0 else 'no'}")
out_txt.write_text("\n".join(lines), encoding="utf-8")

print("done")
for aid in ["8", "24", "28", "32", "33"]:
    print(aid, len(assigned[aid]), valid[aid])
print("added33", added_to_33)
print("remaining_overlap", len(remaining_overlap))
