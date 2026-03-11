@echo off
set ROOT=E:\project_sakif_chicago
set LOG=%ROOT%\output\netconvert_reduced.log
netconvert --osm-files "%ROOT%\map_reduced.osm" --output-file "%ROOT%\net\map_reduced.net.xml" --junctions.join false --tls.guess-signals true --tls.discard-simple false > "%LOG%" 2>&1
if errorlevel 1 (
  echo netconvert failed. See %LOG%
  exit /b 1
)
echo reduced network build completed. See %LOG%
