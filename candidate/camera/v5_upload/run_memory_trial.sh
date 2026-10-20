#!/usr/bin/env bash
# Explicit RAM-only camera trial, no generated image/output directory.
set +e
set +u
umask 077
ulimit -c 0 || exit 1
if [[ $# -lt 1 || $1 != --approve-memory-preview ]]; then
  echo 'STOP: --approve-memory-preview [--approve-gps-camera-mode] [--keep-running] [--preview-only] required'; exit 1
fi
full_system=false
keep_running=false
preview_only=false
shift
for option in "$@"; do
  case "$option" in
    --approve-gps-camera-mode) [[ $full_system == false ]] || exit 1; full_system=true ;;
    --keep-running) [[ $keep_running == false ]] || exit 1; keep_running=true ;;
    --preview-only) [[ $preview_only == false ]] || exit 1; preview_only=true ;;
    *) echo 'STOP: unknown camera option'; exit 1 ;;
  esac
done
if [[ $(hostname -s) != centrabus-pi || $(id -un) != centrabus ]]; then
  echo 'STOP: wrong Pi/account'; exit 1
fi
stage=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P) || exit 1
runtime=/home/centrabus/Desktop/PI-2-UNIFIED-main/candidate/camera
private=/home/centrabus/centrabus-camera-v5-trial-20261020-945b22/camera-private.json
cd -- "$stage" || exit 1
sha256sum -c SHA256SUMS || exit 1
timeout --kill-after=3s 20s python3 -I -B "$stage/live_memory.py" \
  --runtime-dir "$runtime" --private-config "$private" --check || exit 1
[[ $(timedatectl show -p NTPSynchronized --value) == yes ]] || { echo 'STOP: clock not synchronized'; exit 1; }
available=$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)
[[ $available =~ ^[0-9]+$ && $available -ge 524288 ]] || { echo 'STOP: insufficient available memory'; exit 1; }
timeout --kill-after=3s 10s python3 -I -B - "$stage" "$private" "$full_system" <<'PY'
import importlib.util
from pathlib import Path
import sys, json, urllib.request
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
        body = response.read(8193)
        if response.status != 200 or len(body) > 8192:
            raise ValueError('Readiness unavailable')
    data, full = json.loads(body), sys.argv[3] == 'true'
    if not (data.get('ready') is True and data.get('cameraLiveMemoryEnabled') is True
            and data.get('cameraFramesEnabled') is True and data.get('gpsPersistenceEnabled') is full
            and data.get('simulation') is False and (not full or data.get('localFullSystem') is True)):
        raise ValueError('Reviewed mode not verified')
except Exception:
    print('STOP: restart the updated laptop backend and verify its configured LAN address/mode')
    raise SystemExit(1)
print('RAM_CAMERA_BACKEND_READY=PASS; IMAGE_FILES_WRITTEN=false')
PY
[[ $? == 0 ]] || exit 1
command -v fuser >/dev/null && command -v flock >/dev/null || { echo 'STOP: owner/lock check unavailable'; exit 1; }
mkdir -p -- /home/centrabus/.cache || exit 1
# Same guard lock as the previous uploader. This is an empty lock file, no images.
exec 9>/home/centrabus/.cache/centrabus-v5-preview-trial.lock || exit 1
flock -n 9 || { echo 'STOP: another camera trial is running'; exit 1; }
media=(wireplumber.service pipewire.service pipewire.socket pipewire-pulse.service pipewire-pulse.socket)
gps=(gpsd.service centrabus-gps-monitor.service centrabus-gps-sender.service)
for unit in "${media[@]}"; do
  [[ $(systemctl --user show "$unit" -p ActiveState --value) == active ]] || { echo 'STOP: media baseline changed; review first'; exit 1; }
done
gps_before=$(systemctl show "${gps[@]}" -p Id -p ActiveState -p MainPID -p NRestarts --no-pager) || exit 1
[[ -n "$gps_before" ]] || exit 1
sudo -v || exit 1
child_pid=
restore_media() {
  result=$?
  trap - EXIT
  trap '' HUP INT TERM
  # Only this guard's own continuous-session child is stopped. Do not leave a
  # camera owner behind when SSH disconnects or the operator interrupts.
  if [[ -n "$child_pid" ]] && kill -0 "$child_pid" 2>/dev/null; then
    kill -TERM "$child_pid" 2>/dev/null
    for ((attempt=0; attempt<100; attempt++)); do
      kill -0 "$child_pid" 2>/dev/null || break
      sleep .1
    done
    if kill -0 "$child_pid" 2>/dev/null; then
      kill -KILL "$child_pid" 2>/dev/null
    fi
    wait "$child_pid" 2>/dev/null
  fi
  restored=PASS
  timeout --kill-after=3s 20s systemctl --user start "${media[@]}" || restored=STOP_REVIEW
  for unit in "${media[@]}"; do
    [[ $(systemctl --user show "$unit" -p ActiveState --value) == active ]] || restored=STOP_REVIEW
  done
  printf 'MEDIA_RESTORE=%s\n' "$restored"
  if gps_after=$(systemctl show "${gps[@]}" -p Id -p ActiveState -p MainPID -p NRestarts --no-pager) && [[ "$gps_after" == "$gps_before" ]]; then
    echo 'GPS_SERVICE_STATE_UNCHANGED=PASS'
  else
    echo 'GPS_SERVICE_STATE_UNCHANGED=STOP_REVIEW; no GPS service operation attempted'
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
owners=$(sudo -n fuser -v "${devices[@]}" 2>&1)
owner_rc=$?
if [[ "$owner_rc" != 1 || -n "$owners" ]]; then
  printf '%s\n' "$owners"
  echo 'STOP: camera owner remains or owner check failed'; exit 1
fi
arguments=(--runtime-dir "$runtime" --private-config "$private" --approve-camera-upload)
[[ $preview_only == false ]] || arguments+=(--preview-only)
if [[ $keep_running == true ]]; then
  echo 'RAM_CAMERA_MODE=CONTINUOUS; stop with Ctrl+C; media restores when this session ends'
  python3 -I -B -u "$stage/live_memory.py" "${arguments[@]}" --continuous &
  child_pid=$!
  wait "$child_pid"
  trial_rc=$?
  child_pid=
else
  timeout --signal=INT --kill-after=5s 90s python3 -I -B -u "$stage/live_memory.py" "${arguments[@]}" --seconds 60
  trial_rc=$?
fi
printf 'RAM_CAMERA_TRIAL_EXIT=%s\n' "$trial_rc"
exit "$trial_rc"
