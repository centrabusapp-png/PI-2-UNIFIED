# Local Wi-Fi configuration app

Launch from the package root on the Pi desktop:

```bash
python3 setup-pi.py
```

The app opens an authenticated browser session on 127.0.0.1. A direct HTML file
view shows launch instructions with controls disabled. Status, scanning,
connection authorization and setup check-ins are explicit actions.

Connections use native OS authorization and a new private trial profile with a
NetworkManager checkpoint. Keep confirms a verified trial; Rollback returns to
the original fallback. Existing profiles are preserved. Browser recovery and
authorization renewal retain these checks. Physical trials need separate
operator approval and an accessible local fallback.

Wi-Fi, Internet, API readiness and authenticated setup presence are separate
states. The app does not check GPS freshness. Check-ins require explicit consent
and a ready backend that advertises the setup-presence capability. The browser
remembers only a validated API origin, not passwords, bearer tokens or secrets.

The interface groups duplicate access points without replacing a currently
connected selection with a stronger duplicate. File-view assets resolve beside
the page, while the live app uses its local authenticated session.

Mocked verification from the package root:

```bash
python3 -B -m unittest discover -s tests -p 'test*.py'
node tests/setup_gui_ui.test.cjs
```

The 184 Python and 20 frontend tests use synthetic fixtures and mocked OS/backend
operations. They do not switch networks, start a sender or perform real check-ins.
No local environment inventory or physical capability report is published here.
