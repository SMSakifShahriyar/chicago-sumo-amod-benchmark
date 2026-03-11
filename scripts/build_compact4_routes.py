import os
import subprocess
import xml.etree.ElementTree as ET


project_dir = r"E:\project_sakif_chicago"

network_file = os.path.join(project_dir, "net", "map_reduced_clean_auto_v2.net.xml")
taz_file = os.path.join(project_dir, "data", "compact4_zones.taz.xml")
flows_file = os.path.join(project_dir, "data", "compact4_benchmark_flows.xml")
trips_file = os.path.join(project_dir, "data", "compact4_benchmark.trips.xml")
routes_file = os.path.join(project_dir, "routes", "compact4_benchmark.rou.xml")
cfg_file = os.path.join(project_dir, "cfg", "compact4_benchmark.sumocfg")
log_file = os.path.join(project_dir, "output", "compact4_benchmark_route_build.log")

sumo_bin = r"C:\Program Files (x86)\Eclipse\Sumo\bin"
od2trips_exe = os.path.join(sumo_bin, "od2trips.exe")
duarouter_exe = os.path.join(sumo_bin, "duarouter.exe")

os.makedirs(os.path.dirname(routes_file), exist_ok=True)
os.makedirs(os.path.dirname(cfg_file), exist_ok=True)
os.makedirs(os.path.dirname(log_file), exist_ok=True)

cmd1 = [
    od2trips_exe,
    "-n", taz_file,
    "-z", flows_file,
    "-o", trips_file,
    "--spread.uniform",
    "--seed", "42"
]

cmd2 = [
    duarouter_exe,
    "-n", network_file,
    "-r", trips_file,
    "-a", taz_file,
    "--with-taz",
    "--ignore-errors",
    "-o", routes_file,
    "--seed", "42"
]


def run_and_capture(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


rc1, out1, err1 = run_and_capture(cmd1)
rc2, out2, err2 = (999, "", "")
if rc1 == 0:
    rc2, out2, err2 = run_and_capture(cmd2)

log_lines = []
log_lines.append("compact4 benchmark route build log")
log_lines.append("")
log_lines.append("command_od2trips")
log_lines.append(" ".join(cmd1))
log_lines.append(f"return_code={rc1}")
log_lines.append("stdout")
log_lines.append(out1.strip())
log_lines.append("stderr")
log_lines.append(err1.strip())
log_lines.append("")
log_lines.append("command_duarouter")
log_lines.append(" ".join(cmd2))
log_lines.append(f"return_code={rc2}")
log_lines.append("stdout")
log_lines.append(out2.strip())
log_lines.append("stderr")
log_lines.append(err2.strip())

with open(log_file, "w", encoding="utf-8") as f:
    f.write("\n".join(log_lines) + "\n")

cfg_root = ET.Element("configuration")
inp = ET.SubElement(cfg_root, "input")
ET.SubElement(inp, "net-file", {"value": network_file})
ET.SubElement(inp, "route-files", {"value": routes_file})
t = ET.SubElement(cfg_root, "time")
ET.SubElement(t, "begin", {"value": "0"})
ET.SubElement(t, "end", {"value": "86400"})
rpt = ET.SubElement(cfg_root, "report")
ET.SubElement(rpt, "verbose", {"value": "true"})
ET.SubElement(rpt, "no-step-log", {"value": "true"})

ET.ElementTree(cfg_root).write(cfg_file, encoding="utf-8", xml_declaration=True)

print("trips file:", trips_file)
print("routes file:", routes_file)
print("config file:", cfg_file)
print("log file:", log_file)
print("od2trips_rc:", rc1)
print("duarouter_rc:", rc2)
