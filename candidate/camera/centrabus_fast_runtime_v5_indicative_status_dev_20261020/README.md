# Indicative gauge monitor

Run from the repository root on the Pi:

```bash
python3 -B -u candidate/camera/centrabus_fast_runtime_v5_indicative_status_dev_20261020/fast_reader.py
```

Runs until Ctrl+C. Cycles 1–10 save annotated JPGs; later cycles print to the
terminal only. The header is CENTRABUS with actual PHT capture date/time.
FUEL shows percentage and angle. FRONT/REAR show pressure and angle.
BATTERY/OIL show percentage, Low/Normal/High and angle. COOLANT shows
percentage, Cold/Normal/Hot and angle. Missing or unreliable readings show N/A.

Indicative labels reuse the original 25/75 bands and are not physically
verified. The latest detectors, BATTERY correction, COOLANT conversion and
formal condition configuration are preserved. Keep the sibling calibration
reference directory with this version; the Linux symlink resolves it.

Camera-free checks from this directory:

```bash
python3 -B -m unittest -v test_continuous test_condition test_battery_consistency test_battery_coolant test_condition_calibration test_indicative_status
python3 -B verify_geometry.py
python3 -B check_condition_config.py --transitions
```

61 tests and 28 geometry checks pass; one private-survey test is skipped. Historical workspace regression also
retained all 480 candidates across 80 images and all 59,475 existing reading
fields across 658 archived detections. Detailed local reports and live image
sessions are excluded from this public source package. No camera or Supabase
operation was performed during publication.

The internal calibration survey is excluded. Runtime detector and formal
configuration source are unchanged; only its survey-specific test is skipped.
