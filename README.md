# chicago-sumo-amod-benchmark

Minimal, reproducible SUMO/AMoD benchmark package for Chicago reduced network.

## Included
- Network and configs for benchmark runs
- Compact 4-zone TAZ setup
- Demand build and persistent-fleet experiment scripts
- Heuristic policies A/B/C/C_gated implementation
- Final comparison outputs and advisor-facing summary

## Excluded on purpose
- Large raw taxi dataset and raw boundary download
- Heavy generated XML run artifacts and bulk logs

## Main files
- Network: `net/map_reduced_clean_auto_v2.net.xml`
- TAZ: `data/compact4_zones.taz.xml`
- Main runner: `scripts/run_persistent_fleet_experiment.py`
- Final summary: `output/advisor_facing_heuristic_summary.txt`
- Final table: `output/final_heuristic_comparison.csv`
- Final figure: `visuals/final_heuristic_comparison.png`

## Quick run
Use existing benchmark artifacts and run one policy:

```bash
python scripts/run_persistent_fleet_experiment.py \
  --policy A \
  --fleet-size 300 \
  --dispatch-interval 15 \
  --request-scale 0.005 \
  --same-zone-candidate-cap 15 \
  --global-candidate-cap 15 \
  --seed 101
```

Then switch `--policy` to `B`, `C`, or `CG` for heuristic comparisons.

## Notes
Claims are benchmark-specific and reproducible under controlled randomness.
