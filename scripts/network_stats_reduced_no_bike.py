from pathlib import Path
import xml.etree.ElementTree as ET

root = Path(r"E:\project_sakif_chicago")
net_file = root / "net" / "map_reduced_no_bike.net.xml"

if not net_file.exists():
    print("network file not found")
    raise SystemExit(1)

tree = ET.parse(net_file)
net = tree.getroot()

edges = [e for e in net.findall("edge") if not e.get("function")]
lanes = net.findall(".//lane")
junctions = net.findall("junction")
tl_junctions = [j for j in junctions if j.get("type") == "traffic_light"]

check_ids = {
    "219240981#2",
    "219240981#3",
    "219240981#4",
    "-219240981#2",
    "-219240981#3",
    "-219240981#4",
}
edge_ids = {e.get("id", "") for e in edges}

print(f"edges: {len(edges)}")
print(f"lanes: {len(lanes)}")
print(f"junctions: {len(junctions)}")
print(f"traffic_light_junctions: {len(tl_junctions)}")
for eid in sorted(check_ids):
    print(f"edge_exists {eid}: {str(eid in edge_ids).lower()}")
