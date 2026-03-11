@echo off
set ROOT=E:\project_sakif_chicago
sumo -c "%ROOT%\cfg\smoke_test_clean_auto_v2.sumocfg" --duration-log.statistics true --statistic-output "%ROOT%\output\smoke_test_clean_auto_v2_stats.xml" > "%ROOT%\output\smoke_test_clean_auto_v2.log" 2>&1
if errorlevel 1 (
  echo smoke test failed. See output\smoke_test_clean_auto_v2.log
  exit /b 1
)
echo smoke test completed. See output\smoke_test_clean_auto_v2.log
