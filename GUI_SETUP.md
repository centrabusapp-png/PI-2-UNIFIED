# Pi2 Wi-Fi configuration app

Use the package launcher on the Pi desktop:

```bash
python3 setup-pi.py
```

The browser session listens on 127.0.0.1 only. Opening the HTML file directly
shows launch instructions with controls disabled; it cannot configure Wi-Fi.

Status and scans are explicit actions. Enable connections uses the existing
native OS authorization flow. A connection trial creates a separate private
profile with a NetworkManager checkpoint and offers Keep or Rollback. Existing
profiles are preserved. A known-good fallback and local keyboard/display are
needed for separately approved physical testing.

The app distinguishes Wi-Fi, Internet, API readiness, authenticated setup
presence and GPS freshness. GPS freshness is not checked by Wi-Fi setup.
Setup check-ins require explicit operator approval and the existing backend
readiness contract. Merely opening the app does not switch networks or start
check-ins. API origins are remembered only after validation; credentials and
private session tokens are never stored in browser persistence.

The updated source includes native authorization renewal, browser-session
recovery, corrected file-view assets, connected-SSID grouping and conservative
checkpoint cleanup. These behaviors have mocked software coverage; this
publication does not assert physical Wi-Fi acceptance.

Run the package tests from the repository root:

```bash
python3 -B -m unittest discover -s tests -p 'test*.py'
node tests/setup_gui_ui.test.cjs
```

These tests mock Wi-Fi and backend operations. See `PUBLICATION_2026-10-20.md` for
results and `candidate/setup_gui/README.md` for the source workflow.

This public document omits local environment inventories and observations.
Publishing source does not install software, change network profiles, modify
GPS operation or send backend check-ins.
