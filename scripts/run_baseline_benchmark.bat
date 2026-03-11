@echo off
setlocal
set CFG=E:\project_sakif_chicago\cfg\baseline_benchmark.sumocfg
set LOG=E:\project_sakif_chicago\output\baseline_run.log
sumo -c "%CFG%" > "%LOG%" 2>&1
echo Baseline run finished. Log: %LOG%
endlocal
