@echo off
set ROOT=E:\project_sakif_chicago
sumo -c "%ROOT%\cfg\smoke_test_reduced.sumocfg" --duration-log.statistics true --statistic-output "%ROOT%\output\smoke_test_reduced_stats.xml" > "%ROOT%\output\smoke_test_reduced.log" 2>&1
if errorlevel 1 (
  echo smoke test failed. See output\smoke_test_reduced.log
  exit /b 1
)
echo smoke test completed. See output\smoke_test_reduced.log
