# Device boundary: Pi2

- Device identity: `GPS-002`; preserve its existing secret and authenticated bus assignment.
- Expected account: `centrabus`; previously reported hostname: `centrabus-pi`. Reconfirm physically before writes.
- Candidate monitor default KML: `/home/centrabus/centrabus-device/centrabus_route.kml`.
- Candidate monitor output and sender default input: `/home/centrabus/centrabus-device/latest_gps.json`.
- Candidate sender default queue: `/home/centrabus/centrabus-device/gps_offline_queue.sqlite3`.
- The exact existing queue path and protected environment overrides take precedence. A different existing path is a deployment blocker until reconciled; never create a fresh empty queue as a migration shortcut.
- Pi2 source age was reported near 0.5s. Its current installed service files, sender state and receiver settings were not inspected by this task. Do not apply Pi1's assumed boot/tuner settings to Pi2.
- Pi1's 15-16s problem is evidence for Pi1 only. Do not change Pi2 receiver settings because of that evidence.
- Do not install Pi1 credentials, copy Pi1 service units, modify R6 or change GNSS/RAM/baud/boot configuration from this package.
- Stage camera runtime in a new, explicitly approved directory under the current account. Do not overwrite another camera installation or run a Flask server on the Express host's port 5000.
