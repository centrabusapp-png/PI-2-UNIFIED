#!/usr/bin/env bash
# Explicit Pi2 operator trial only. Never installed or started by the dashboard.
set +e
set +u
umask 077
if [[ $# -lt 1 || $# -gt 2 || $1 != --approve-preview-trial || ( $# == 2 && $2 != --approve-gps-camera-mode ) ]]; then
  echo 'STOP: explicit --approve-preview-trial [--approve-gps-camera-mode] required'; exit 1
fi
full_system=false
[[ $# == 2 ]] && full_system=true
if [[ $(hostname -s) != centrabus-pi || $(id -un) != centrabus ]]; then
  echo 'STOP: wrong Pi/account'; exit 1
fi
stage=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P) || exit 1
runtime=/home/centrabus/Desktop/PI-2-UNIFIED-main/candidate/camera
private=/home/centrabus/centrabus-camera-v5-trial-20261020-945b22/camera-private.json
cd -- "$stage" || exit 1
sha256sum -c SHA256SUMS || exit 1
timeout --kill-after=3s 20s python3 -I -B "$stage/preview_v5.py" \
  --runtime-dir "$runtime" --private-config "$private" --check || exit 1
[[ $(timedatectl show -p NTPSynchronized --value) == yes ]] || { echo 'STOP: clock not synchronized'; exit 1; }
available=$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)
[[ $available =~ ^[0-9]+$ && $available -ge 524288 ]] || { echo 'STOP: less than 512MiB available memory'; exit 1; }

# This readiness request has no secret, image or GPS payload. No redirects/proxy.
timeout --kill-after=3s 10s python3 -I -B - "$stage" "$private" "$full_system" <<'PY'
import importlib.util
from pathlib import Path
import sys
import json
import urllib.request
try:
    spec = importlib.util.spec_from_file_location('reviewed_transport', Path(sys.argv[1]) / 'dashboard_publish.py')
    transport = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(transport)
    config = transport.load_config(Path(sys.argv[2]))
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *_args, **_kwargs):
            raise ValueError('Redirect rejected')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(config['backend_url'] + '/readyz', timeout=3) as response:
        data = response.read(8193)
        if response.status != 200 or len(data) > 8192:
            raise ValueError('Readiness unavailable')
    data = json.loads(data)
    full = sys.argv[3] == 'true'
    if not (data.get('ready') is True and data.get('cameraPreviewEnabled') is True
            and data.get('cameraFramesEnabled') is True and data.get('gpsPersistenceEnabled') is full
            and data.get('simulation') is False
            and (not full or data.get('localFullSystem') is True)):
        raise ValueError('Explicit camera/GPS mode not verified')
except Exception:
    print('STOP: verify the reviewed laptop backend mode and configured LAN address; no services changed')
    raise SystemExit(1)
print('CAMERA_PREVIEW_BACKEND_READY=PASS; GPS_WRITES=' + str(full).lower())
PY
[[ $? == 0 ]] || exit 1
command -v fuser >/dev/null && command -v flock >/dev/null || { echo 'STOP: owner/lock check unavailable'; exit 1; }
mkdir -p -- /home/centrabus/.cache || exit 1
exec 9>/home/centrabus/.cache/centrabus-v5-preview-trial.lock || exit 1
flock -n 9 || { echo 'STOP: another preview trial is running'; exit 1; }
media=(wireplumber.service pipewire.service pipewire.socket pipewire-pulse.service pipewire-pulse.socket)
gps=(gpsd.service centrabus-gps-monitor.service centrabus-gps-sender.service)
for unit in "${media[@]}"; do
  [[ $(systemctl --user show "$unit" -p ActiveState --value) == active ]] || { echo 'STOP: media baseline changed; review before stopping anything'; exit 1; }
done
gps_before=$(systemctl show "${gps[@]}" -p Id -p ActiveState -p MainPID -p NRestarts --no-pager) || exit 1
[[ -n "$gps_before" ]] || exit 1
sudo -v || exit 1
restore_media() {
  result=$?
  trap - EXIT
  trap '' HUP INT TERM
  restored=PASS
  timeout --kill-after=3s 20s systemctl --user start "${media[@]}" || restored=STOP_REVIEW
  for unit in "${media[@]}"; do
    [[ $(systemctl --user show "$unit" -p ActiveState --value) == active ]] || restored=STOP_REVIEW
  done
  printf 'MEDIA_RESTORE=%s\n' "$restored"
  if gps_after=$(systemctl show "${gps[@]}" -p Id -p ActiveState -p MainPID -p NRestarts --no-pager) && [[ "$gps_after" == "$gps_before" ]]; then
    echo 'GPS_SERVICE_STATE_UNCHANGED=PASS'
  else
    echo 'GPS_SERVICE_STATE_UNCHANGED=STOP_REVIEW; no GPS restart attempted'
    result=1
  fi
  [[ "$restored" == PASS ]] || result=1
  exit "$result"
}
trap restore_media EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
timeout --kill-after=3s 20s systemctl --user stop "${media[@]}" || exit 1
shopt -s nullglob
devices=(/dev/video* /dev/media* /dev/v4l-subdev*)
((${#devices[@]})) || { echo 'STOP: no camera device nodes'; exit 1; }
# PSmisc fuser on this Pi does not accept a standalone -- here.
owners=$(sudo -n fuser -v "${devices[@]}" 2>&1)
owner_rc=$?
if [[ "$owner_rc" != 1 || -n "$owners" ]]; then
  printf '%s\n' "$owners"
  echo 'STOP: camera owner remains or owner check failed'; exit 1
fi
output="$stage/preview-$(date -u +%Y%m%dT%H%M%SZ)-$$"
printf 'TRIAL_OUTPUT=%s\n' "$output"
timeout --signal=INT --kill-after=5s 90s python3 -I -B -u "$stage/preview_v5.py" \
  --runtime-dir "$runtime" --private-config "$private" \
  --output-dir "$output" --seconds 60 --approve-camera-upload
trial_rc=$?
printf 'CAMERA_PREVIEW_TRIAL_EXIT=%s\n' "$trial_rc"
exit "$trial_rc"
