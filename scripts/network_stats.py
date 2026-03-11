from pathlib import Path
import xml.etree.ElementTree as ET

root = Path(r"E:\project_sakif_chicago")
net_file = root / "net" / "map.net.xml"

if not net_file.exists():
    print("network file not found")
    raise SystemExit(1)

tree = ET.parse(net_file)
net = tree.getroot()

edges = [e for e in net.findall("edge") if not e.get("function")]
lanes = net.findall(".//lane")
junctions = net.findall("junction")

internal_junctions = [j for j in junctions if j.get("type") == "internal" or j.get("id", "").startswith(":")]
normal_junctions = [j for j in junctions if j not in internal_junctions]

in_count = {}
out_count = {}
for e in edges:
    fr = e.get("from")
    to = e.get("to")
    if fr:
        out_count[fr] = out_count.get(fr, 0) + 1
    if to:
        in_count[to] = in_count.get(to, 0) + 1

boundary_dead_end = 0
for j in normal_junctions:
    jid = j.get("id")
    t = j.get("type", "")
    indeg = in_count.get(jid, 0)
    outdeg = out_count.get(jid, 0)
    if "dead_end" in t or indeg == 0 or outdeg == 0:
        boundary_dead_end += 1

tl_junctions = [j for j in junctions if j.get("type") == "traffic_light"]
tl_logic = net.findall("tlLogic")

print(f"edges: {len(edges)}")
print(f"lanes: {len(lanes)}")
print(f"junctions: {len(junctions)}")
print(f"internal_junctions: {len(internal_junctions)}")
print(f"boundary_or_dead_end_junctions: {boundary_dead_end}")
print(f"traffic_light_junctions: {len(tl_junctions)}")
print(f"tl_logic_objects: {len(tl_logic)}")
