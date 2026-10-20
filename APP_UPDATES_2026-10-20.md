# Updated camera and Wi-Fi apps

Camera monitoring:

```bash
python3 -B -u candidate/camera/centrabus_fast_runtime_v5_indicative_status_dev_20261020/fast_reader.py
```

Wi-Fi configuration, from a Pi desktop:

```bash
python3 setup-pi.py
```

Both commands are for operator use. No physical camera, Wi-Fi change, service
installation, GPS sender or Supabase operation was run during publication.

The camera version is separate from previous code. It preserves the latest
needle detection and numerical conversions, restores indicative labels, runs
until Ctrl+C and saves annotated JPGs only for the first ten cycles. Labels are
not physically verified. See its README for camera-free tests.

The Wi-Fi app includes native authorization, protected trials with Keep/Rollback,
browser recovery and separate API/setup readiness. See GUI_SETUP.md and the app
README. Existing source archives and earlier camera versions remain unchanged.

Software checks: 184 package Python tests, 20 frontend cases, 61 camera tests and 28 geometry checks pass; one private-survey test is skipped. Test totals are in PUBLICATION_2026-10-20.md. Local environment
reports, credentials and live runtime sessions are excluded from this update.

The internal calibration survey is excluded. Runtime detector and formal
configuration source are unchanged; only its survey-specific test is skipped.
