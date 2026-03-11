import csv
import json
from pathlib import Path
import xml.etree.ElementTree as ET

root = Path(r"E:\project_sakif_chicago")
net_file = root / "net" / "map_reduced_clean_auto_v2.net.xml"
out_csv = root / "output" / "intersection_audit_list.csv"
out_json = root / "output" / "intersection_audit_list.json"
out_summary = root / "output" / "intersection_audit_summary.txt"
out_top10 = root / "output" / "intersection_audit_top10.txt"

if not net_file.exists():
    print("network file not found")
    raise SystemExit(1)

tree = ET.parse(net_file)
net = tree.getroot()

junctions = {}
for j in net.findall("junction"):
    jid = j.get("id", "")
    if jid.startswith(":") or j.get("type", "") == "internal":
        continue
    x = float(j.get("x", "0") or 0)
    y = float(j.get("y", "0") or 0)
    inc_lanes = [v for v in (j.get("incLanes", "") or "").split(" ") if v]
    int_lanes = [v for v in (j.get("intLanes", "") or "").split(" ") if v]
    junctions[jid] = {
        "junction_id": jid,
        "x": x,
        "y": y,
        "junction_type": j.get("type", ""),
        "inc_lane_count": len(inc_lanes),
        "int_lane_count": len(int_lanes),
    }

edges = {}
incoming = {jid: [] for jid in junctions}
outgoing = {jid: [] for jid in junctions}
for e in net.findall("edge"):
    if e.get("function"):
        continue
    eid = e.get("id", "")
    fr = e.get("from", "")
    to = e.get("to", "")
    lanes = e.findall("lane")
    lane_count = len(lanes)
    speed = 0.0
    if lanes:
        try:
            speed = max(float(l.get("speed", "0") or 0) for l in lanes)
        except Exception:
            speed = 0.0
    priority = 0
    try:
        priority = int(e.get("priority", "0") or 0)
    except Exception:
        priority = 0
    edges[eid] = {
        "id": eid,
        "from": fr,
        "to": to,
        "lane_count": lane_count,
        "speed": speed,
        "priority": priority,
    }
    if fr in outgoing:
        outgoing[fr].append(eid)
    if to in incoming:
        incoming[to].append(eid)

rows = []
for jid, j in junctions.items():
    in_edges = incoming.get(jid, [])
    out_edges = outgoing.get(jid, [])
    in_edge_count = len(in_edges)
    out_edge_count = len(out_edges)
    degree = in_edge_count + out_edge_count
    in_lane_total = sum(edges[e]["lane_count"] for e in in_edges if e in edges)
    out_lane_total = sum(edges[e]["lane_count"] for e in out_edges if e in edges)
    lane_complexity = in_lane_total + out_lane_total + j["int_lane_count"]
    major_edge_count = 0
    major_lane_mass = 0
    for e in in_edges + out_edges:
        if e not in edges:
            continue
        ed = edges[e]
        if ed["lane_count"] >= 2 or ed["speed"] >= 13.9 or ed["priority"] >= 8:
            major_edge_count += 1
            major_lane_mass += ed["lane_count"]

    score = 0.0
    reasons = []
    if j["junction_type"] == "traffic_light":
        score += 4.0
        reasons.append("signalized")
    if degree >= 6:
        score += 2.5 + (degree - 5) * 0.5
        reasons.append(f"high_degree:{degree}")
    if lane_complexity >= 18:
        score += 2.5 + (lane_complexity - 17) * 0.15
        reasons.append(f"high_lane_complexity:{lane_complexity}")
    if major_edge_count >= 4:
        score += 2.0 + (major_edge_count - 3) * 0.4
        reasons.append(f"major_corridor_links:{major_edge_count}")
    if major_lane_mass >= 10:
        score += 1.2 + (major_lane_mass - 9) * 0.2
        reasons.append(f"major_lane_mass:{major_lane_mass}")

    likely_review = "yes" if score >= 9.5 or (j["junction_type"] == "traffic_light" and lane_complexity >= 16) else "maybe"

    if score > 0:
        rows.append({
            "junction_id": jid,
            "x": round(j["x"], 3),
            "y": round(j["y"], 3),
            "junction_type": j["junction_type"],
            "incoming_edges": in_edge_count,
            "outgoing_edges": out_edge_count,
            "degree": degree,
            "incoming_lane_total": in_lane_total,
            "outgoing_lane_total": out_lane_total,
            "internal_lanes": j["int_lane_count"],
            "lane_complexity": lane_complexity,
            "major_edge_count": major_edge_count,
            "major_lane_mass": major_lane_mass,
            "score": round(score, 3),
            "selected_reason": ";".join(reasons),
            "likely_needs_geometry_or_connection_review": likely_review,
        })

rows.sort(key=lambda r: r["score"], reverse=True)
shortlist = rows[:15]

with out_csv.open("w", newline="", encoding="utf-8") as f:
    fields = [
        "rank",
        "junction_id",
        "x",
        "y",
        "junction_type",
        "incoming_edges",
        "outgoing_edges",
        "degree",
        "incoming_lane_total",
        "outgoing_lane_total",
        "internal_lanes",
        "lane_complexity",
        "major_edge_count",
        "major_lane_mass",
        "score",
        "selected_reason",
        "likely_needs_geometry_or_connection_review",
    ]
    w = csv.DictWriter(f, fieldnames=fields)
    w.writeheader()
    for i, r in enumerate(shortlist, start=1):
        row = dict(r)
        row["rank"] = i
        w.writerow(row)

with out_json.open("w", encoding="utf-8") as f:
    json.dump(shortlist, f, indent=2)

with out_top10.open("w", encoding="utf-8") as f:
    for i, r in enumerate(shortlist[:10], start=1):
        f.write(f"{i}. {r['junction_id']} ({r['x']}, {r['y']}) type={r['junction_type']} score={r['score']}\n")

harmless_candidates = [r for r in rows if r["score"] < 7.0][:8]

lines = []
lines.append("Intersection audit summary")
lines.append("")
lines.append("network: " + str(net_file))
lines.append("normal junctions analyzed: " + str(len(junctions)))
lines.append("shortlist size: " + str(len(shortlist)))
lines.append("")
lines.append("audit logic:")
lines.append("- prioritize traffic-light junctions")
lines.append("- prioritize high-degree nodes")
lines.append("- prioritize high lane complexity")
lines.append("- prioritize corridor-like links by speed/lanes/priority")
lines.append("")
lines.append("highest priority intersections (ranked):")
for i, r in enumerate(shortlist, start=1):
    lines.append(f"{i}. {r['junction_id']} | type={r['junction_type']} | degree={r['degree']} | lane_complexity={r['lane_complexity']} | score={r['score']} | review={r['likely_needs_geometry_or_connection_review']} | reason={r['selected_reason']}")
lines.append("")
lines.append("probably lower risk for now:")
if harmless_candidates:
    for r in harmless_candidates:
        lines.append(f"- {r['junction_id']} | type={r['junction_type']} | score={r['score']}")
else:
    lines.append("- no low-score candidates in prioritized set")
lines.append("")
lines.append("assessment:")
if shortlist and shortlist[0]["score"] >= 12:
    lines.append("- network likely needs a limited focused intersection patching pass, not a broad rebuild")
else:
    lines.append("- network appears relatively stable; apply only minor spot checks")

out_summary.write_text("\n".join(lines), encoding="utf-8")

print("done")
print("shortlist", len(shortlist))
if shortlist:
    print("top", shortlist[0]["junction_id"], shortlist[0]["score"])
