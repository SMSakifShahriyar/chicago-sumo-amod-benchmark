import os
import csv
import xml.etree.ElementTree as ET


project_dir = r"E:\project_sakif_chicago"
net_file = os.path.join(project_dir, "net", "map_reduced_clean_auto_v2.net.xml")
taz_file = os.path.join(project_dir, "data", "compact4_zones.taz.xml")

zone_out = {
    "cz1": os.path.join(project_dir, "data", "compact4_service_edges_cz1.txt"),
    "cz2": os.path.join(project_dir, "data", "compact4_service_edges_cz2.txt"),
    "cz3": os.path.join(project_dir, "data", "compact4_service_edges_cz3.txt"),
    "cz4": os.path.join(project_dir, "data", "compact4_service_edges_cz4.txt"),
}
summary_file = os.path.join(project_dir, "output", "compact4_service_edge_summary.txt")
table_file = os.path.join(project_dir, "output", "compact4_service_edge_table.csv")

min_length = 20.0


def fnum(v):
    try:
        return float(v)
    except Exception:
        return 0.0


def lane_drivable(lane):
    allow = lane.get("allow")
    disallow = lane.get("disallow")
    if allow:
        s = set(x.strip() for x in allow.split())
        return "all" in s or "passenger" in s
    if disallow:
        s = set(x.strip() for x in disallow.split())
        return not ("all" in s or "passenger" in s)
    return True


root = ET.parse(net_file).getroot()

edge_data = {}
for edge in root.findall("edge"):
    eid = edge.get("id", "")
    if not eid or eid.startswith(":"):
        continue
    fn = edge.get("from")
    tn = edge.get("to")
    if not fn or not tn:
        continue
    if edge.get("function", "") == "internal":
        continue
    lanes = edge.findall("lane")
    if not lanes:
        continue
    drivable_lanes = [ln for ln in lanes if lane_drivable(ln)]
    if not drivable_lanes:
        continue
    ln0 = drivable_lanes[0]
    length = fnum(ln0.get("length", "0"))
    speed = fnum(ln0.get("speed", "0"))
    if length < min_length:
        continue
    edge_data[eid] = {
        "from": fn,
        "to": tn,
        "length": length,
        "speed": speed,
        "lanes": len(drivable_lanes),
    }

adj = {e: set() for e in edge_data}
rev = {e: set() for e in edge_data}
from_index = {}
to_index = {}
for e, d in edge_data.items():
    from_index.setdefault(d["from"], []).append(e)
    to_index.setdefault(d["to"], []).append(e)
for e, d in edge_data.items():
    nxt = from_index.get(d["to"], [])
    for e2 in nxt:
        if e2 == e:
            continue
        adj[e].add(e2)
        rev[e2].add(e)

nodes = list(edge_data.keys())
visited = set()
order = []

for n in nodes:
    if n in visited:
        continue
    stack = [(n, 0)]
    visited.add(n)
    while stack:
        cur, state = stack.pop()
        if state == 0:
            stack.append((cur, 1))
            for nx in adj[cur]:
                if nx not in visited:
                    visited.add(nx)
                    stack.append((nx, 0))
        else:
            order.append(cur)

visited.clear()
comps = []
for n in reversed(order):
    if n in visited:
        continue
    comp = []
    stack = [n]
    visited.add(n)
    while stack:
        cur = stack.pop()
        comp.append(cur)
        for nx in rev[cur]:
            if nx not in visited:
                visited.add(nx)
                stack.append(nx)
    comps.append(comp)

comps.sort(key=lambda x: len(x), reverse=True)
main_scc = set(comps[0]) if comps else set()

in_deg = {e: len(rev[e]) for e in edge_data}
out_deg = {e: len(adj[e]) for e in edge_data}

taz_root = ET.parse(taz_file).getroot()
zone_edges_raw = {}
for t in taz_root.findall("taz"):
    zid = t.get("id", "").strip()
    zone_edges_raw[zid] = [e.strip() for e in (t.get("edges", "") or "").split() if e.strip()]

zone_edges_final = {}
table_rows = []
for zid in sorted(zone_edges_raw.keys()):
    chosen = []
    for e in zone_edges_raw[zid]:
        if e not in edge_data:
            continue
        if e not in main_scc:
            continue
        if in_deg[e] <= 0 or out_deg[e] <= 0:
            continue
        chosen.append(e)
    if len(chosen) < 5:
        backup = []
        for e in zone_edges_raw[zid]:
            if e in edge_data and in_deg[e] > 0 and out_deg[e] > 0:
                backup.append((in_deg[e] + out_deg[e], e))
        backup.sort(reverse=True)
        for _, e in backup:
            if e not in chosen:
                chosen.append(e)
            if len(chosen) >= 5:
                break
    zone_edges_final[zid] = chosen
    for e in chosen:
        d = edge_data[e]
        table_rows.append({
            "zone": zid,
            "edge_id": e,
            "length": round(d["length"], 3),
            "speed": round(d["speed"], 3),
            "lanes": d["lanes"],
            "in_degree": in_deg[e],
            "out_degree": out_deg[e],
            "in_main_scc": "yes" if e in main_scc else "no",
        })

for zid, path in zone_out.items():
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for e in zone_edges_final.get(zid, []):
            f.write(e + "\n")

os.makedirs(os.path.dirname(table_file), exist_ok=True)
with open(table_file, "w", encoding="utf-8", newline="") as f:
    fields = ["zone", "edge_id", "length", "speed", "lanes", "in_degree", "out_degree", "in_main_scc"]
    w = csv.DictWriter(f, fieldnames=fields)
    w.writeheader()
    for r in table_rows:
        w.writerow(r)

lines = []
lines.append("compact4 service edge summary")
lines.append("")
lines.append(f"candidate_edges_after_drivable_noninternal_nontiny={len(edge_data)}")
lines.append(f"main_scc_edge_count={len(main_scc)}")
for zid in sorted(zone_edges_final.keys()):
    lines.append(f"{zid}_service_edges={len(zone_edges_final[zid])}")
lines.append("")
lines.append("filters")
lines.append(f"min_length={min_length}")
lines.append("drivable=passenger/all lanes only")
lines.append("internal_edges=excluded")
lines.append("reachability=main_scc + in_degree>0 + out_degree>0")
lines.append("pickup_dropoff=use service edge list only")

with open(summary_file, "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")

for zid, path in zone_out.items():
    print(f"{zid}_file={path}")
    print(f"{zid}_count={len(zone_edges_final.get(zid, []))}")
print("summary_file=" + summary_file)
print("table_file=" + table_file)
