import os
import csv


project_dir = r"E:\project_sakif_chicago"
plan_file = os.path.join(project_dir, "output", "persistent_fleet_framework_plan.txt")
components_file = os.path.join(project_dir, "output", "persistent_fleet_components.csv")

reuse_items = [
    r"E:\project_sakif_chicago\net\map_reduced_clean_auto_v2.net.xml",
    r"E:\project_sakif_chicago\data\compact4_zones.taz.xml",
    r"E:\project_sakif_chicago\output\compact4_od_matrix.csv",
    r"E:\project_sakif_chicago\output\compact4_time_profile.csv",
    r"E:\project_sakif_chicago\data\compact4_benchmark_flows_10.xml",
    r"E:\project_sakif_chicago\scripts\run_rebalancing_experiment.py",
]

components = [
    {
        "component_name": "request_stream_builder",
        "purpose": "convert hourly OD demand into timestamped passenger requests",
        "minimal_input": "compact4_benchmark_flows_10.xml + compact4_zones.taz.xml",
        "minimal_output": "requests_10pct.csv with request_id,time,origin_zone,destination_zone",
        "reuse_from_current_benchmark": "yes",
        "priority_order": 1,
    },
    {
        "component_name": "persistent_vehicle_initializer",
        "purpose": "create a fixed fleet at t=0 that stays in simulation all day",
        "minimal_input": "network + zone edge lists + chosen fleet size",
        "minimal_output": "fleet_state with vehicle_id,current_zone,status,current_edge",
        "reuse_from_current_benchmark": "partly",
        "priority_order": 2,
    },
    {
        "component_name": "idle_vehicle_tracker",
        "purpose": "track when each vehicle is idle, serving, or rebalancing",
        "minimal_input": "TraCI vehicle state each step",
        "minimal_output": "live idle set by zone",
        "reuse_from_current_benchmark": "no",
        "priority_order": 3,
    },
    {
        "component_name": "request_assignment_rule",
        "purpose": "assign open requests to idle vehicles using nearest/zone-first rule",
        "minimal_input": "open requests + idle vehicles + travel cost proxy",
        "minimal_output": "dispatch decisions request_id->vehicle_id",
        "reuse_from_current_benchmark": "no",
        "priority_order": 4,
    },
    {
        "component_name": "vehicle_service_lifecycle",
        "purpose": "move vehicle through states idle->pickup->dropoff->idle",
        "minimal_input": "dispatch decisions + TraCI route control",
        "minimal_output": "state transitions and service completion timestamps",
        "reuse_from_current_benchmark": "no",
        "priority_order": 5,
    },
    {
        "component_name": "rebalancing_hook",
        "purpose": "run policy B only on truly idle vehicles between assignment steps",
        "minimal_input": "idle vehicles by zone + demand-gap signal + caps",
        "minimal_output": "empty vehicle reposition actions",
        "reuse_from_current_benchmark": "yes",
        "priority_order": 6,
    },
    {
        "component_name": "metrics_and_logs",
        "purpose": "collect service and system metrics for A/B comparison",
        "minimal_input": "simulation events + tripinfo + summary + policy actions",
        "minimal_output": "run summary, policy log, A_vs_B report",
        "reuse_from_current_benchmark": "yes",
        "priority_order": 7,
    },
]

lines = []
lines.append("persistent fleet framework plan")
lines.append("")
lines.append("why fixed-trip replay blocks meaningful rebalancing")
lines.append("1. replay file already contains full passenger routes with vehicle ownership fixed at generation time")
lines.append("2. each route vehicle is consumed by a single predefined trip and then leaves operational control")
lines.append("3. there is no persistent fleet pool that remains available for future requests")
lines.append("4. there is no open request queue to dispatch against")
lines.append("5. no stable idle state exists as a decision resource, so policy B has nothing to move")
lines.append("")
lines.append("minimal persistent-fleet architecture")
lines.append("A. request representation")
lines.append("use request stream records: request_id, request_time, origin_zone, destination_zone")
lines.append("derive from existing 10% OD/hour demand so demand shape stays unchanged")
lines.append("")
lines.append("B. vehicle persistence")
lines.append("initialize a fixed fleet at simulation start")
lines.append("vehicles do not disappear after serving one request")
lines.append("after dropoff each vehicle returns to idle state")
lines.append("")
lines.append("C. idle tracking")
lines.append("track each vehicle status: idle, serving, rebalancing")
lines.append("maintain idle vehicle lists by zone at decision intervals")
lines.append("")
lines.append("D. request assignment")
lines.append("at each dispatch interval, assign open requests to idle vehicles with a simple nearest/zone-first rule")
lines.append("no predictive or RL assignment in first version")
lines.append("")
lines.append("E. idle transition")
lines.append("vehicle becomes idle immediately after completing passenger dropoff")
lines.append("idle vehicles can be selected for next request or rebalancing move")
lines.append("")
lines.append("F. rebalancing window")
lines.append("run policy B only after request assignment at each decision interval")
lines.append("move only currently idle vehicles")
lines.append("")
lines.append("what can be reused directly")
for item in reuse_items:
    lines.append(f"- {item}")
lines.append("")
lines.append("new minimal files to add later")
lines.append("- data/requests_10pct.csv")
lines.append("- scripts/run_persistent_fleet_experiment.py")
lines.append("- output/persistent_A_* and output/persistent_B_*")
lines.append("")
lines.append("first implementation step")
lines.append("implement request_stream_builder + persistent_vehicle_initializer in one script")
lines.append("goal: simulation runs with persistent vehicles and request queue, even with policy A only")
lines.append("")
lines.append("policy B status")
lines.append("policy B should be paused for performance claims until persistent fleet framework exists")
lines.append("policy B code path can remain, but evaluation should be marked non-informative under replay setup")

os.makedirs(os.path.dirname(plan_file), exist_ok=True)
with open(plan_file, "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")

with open(components_file, "w", encoding="utf-8", newline="") as f:
    fields = [
        "component_name",
        "purpose",
        "minimal_input",
        "minimal_output",
        "reuse_from_current_benchmark",
        "priority_order",
    ]
    w = csv.DictWriter(f, fieldnames=fields)
    w.writeheader()
    for c in components:
        w.writerow(c)

print("plan file:", plan_file)
print("components file:", components_file)
