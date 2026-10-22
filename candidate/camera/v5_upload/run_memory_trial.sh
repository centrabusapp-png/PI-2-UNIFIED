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
backend_url=
shift
while (( $# )); do
  case "$1" in
    --approve-gps-camera-mode) [[ $full_system == false ]] || exit 1; full_system=true ;;
    --keep-running) [[ $keep_running == false ]] || exit 1; keep_running=true ;;
    --preview-only) [[ $preview_only == false ]] || exit 1; preview_only=true ;;
    --backend-url) [[ -z "$backend_url" && $# -ge 2 ]] || exit 1; backend_url=$2; shift ;;
    *) echo 'STOP: unknown camera option'; exit 1 ;;
  esac
  shift
done
endpoint=()
[[ -z "$backend_url" ]] || endpoint=(--backend-url "$backend_url")
if [[ $(hostname -s) != centrabus-pi || $(id -un) != centrabus ]]; then
  echo 'STOP: wrong Pi/account'; exit 1
fi
stage=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P) || exit 1
runtime=/home/centrabus/Desktop/PI-2-UNIFIED-main/candidate/camera
private=/home/centrabus/centrabus-camera-v5-trial-20261020-945b22/camera-private.json
cd -- "$stage" || exit 1
sha256sum -c SHA256SUMS || exit 1
timeout --kill-after=3s 20s python3 -I -B "$stage/live_memory.py" \
  --runtime-dir "$runtime" --private-config "$private" "${endpoint[@]}" --check || exit 1
[[ $(timedatectl show -p NTPSynchronized --value) == yes ]] || { echo 'STOP: clock not synchronized'; exit 1; }
available=$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)
[[ $available =~ ^[0-9]+$ && $available -ge 524288 ]] || { echo 'STOP: insufficient available memory'; exit 1; }
timeout --kill-after=3s 30s python3 -I -B - "$stage" "$private" "$full_system" "$backend_url" <<'PY'
import importlib.util
from pathlib import Path
import sys
try:
    spec = importlib.util.spec_from_file_location('reviewed_transport', Path(sys.argv[1]) / 'dashboard_publish.py')
    transport = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(transport)
    config = transport.load_config(Path(sys.argv[2]))
    live_spec = importlib.util.spec_from_file_location('reviewed_live', Path(sys.argv[1]) / 'live_memory.py')
    live = importlib.util.module_from_spec(live_spec)
    live_spec.loader.exec_module(live)
    config = live.session_config(config, sys.argv[4] or None)
except Exception:
    print('CAMERA_STOP=CONFIG_REJECTED; private details withheld')
    raise SystemExit(20)
try:
    live.wait_camera_backend(config, sys.argv[3] == 'true')
except live.BackendReadinessError as error:
    print('CAMERA_STOP=' + str(error) + '; BACKEND=' + config['backend_url'])
    raise SystemExit(75 if error.retryable else 20)
PY
backend_rc=$?
[[ $backend_rc == 0 ]] || exit "$backend_rc"
command -v fuser >/dev/null && command -v flock >/dev/null || { echo 'STOP: owner/lock check unavailable'; exit 1; }
mkdir -p -- /home/centrabus/.cache || exit 1
# Same guard lock as the previous uploader. This is an empty lock file, no images.
exec 9>/home/centrabus/.cache/centrabus-v5-preview-trial.lock || exit 1
flock -n 9 || { echo 'STOP: another camera trial is running'; exit 1; }
media=(wireplumber.service pipewire.service pipewire.socket pipewire-pulse.service pipewire-pulse.socket)
gps=(gpsd.service centrabus-gps-monitor.service centrabus-gps-sender.service)
# BEGIN MEDIA STATE FUNCTIONS (also exercised with a fake systemctl offline).
declare -A media_before media_load
media_active=()
query_media() {
  local report rc key value
  report=$(timeout --kill-after=3s 8s systemctl --user show "$1" -p LoadState -p ActiveState --no-pager)
  rc=$?
  media_query_load= media_query_state=
  while IFS='=' read -r key value; do
    case "$key" in LoadState) media_query_load=$value ;; ActiveState) media_query_state=$value ;; esac
  done <<< "$report"
  # Some systemctl releases return 1 for an explicit not-found unit report.
  [[ $rc == 0 || ( $rc == 1 && $media_query_load == not-found && $media_query_state == inactive ) ]]
}
snapshot_media() {
  local unit load state
  for unit in "${media[@]}"; do
    query_media "$unit" || {
      printf 'CAMERA_STOP=MEDIA_INSPECTION_FAILED; UNIT=%s\n' "$unit"; return 20;
    }
    load=$media_query_load state=$media_query_state
    printf 'CAMERA_MEDIA_BASELINE=%s; LOAD=%s; STATE=%s\n' "$unit" "$load" "$state"
    # An inactive/missing desktop service is normal on a headless Pi. Failed,
    # masked, transitional or unreadable states still require explicit review.
    if [[ $load != loaded && ! ( $load == not-found && $state == inactive ) ]] ||
       [[ $state != active && $state != inactive ]]; then
      printf 'CAMERA_STOP=MEDIA_STATE_UNSAFE; UNIT=%s\n' "$unit"; return 20
    fi
    media_before[$unit]=$state
    media_load[$unit]=$load
    [[ $state != active ]] || media_active+=("$unit")
  done
}
media_unchanged() {
  local unit state load
  for unit in "${media[@]}"; do
    query_media "$unit" || return 1
    load=$media_query_load state=$media_query_state
    if [[ $load != "${media_load[$unit]}" || $state != "${media_before[$unit]}" ]]; then
      printf 'CAMERA_MEDIA_CHANGED=%s; EXPECTED=%s; ACTUAL=%s; LOAD=%s\n' "$unit" "${media_before[$unit]}" "$state" "$load"
      return 1
    fi
  done
}
restore_media_units() {
  # Start only units that THIS session stopped; never enable an inactive unit.
  if ((${#media_active[@]})); then
    timeout --kill-after=3s 20s systemctl --user start "${media_active[@]}" || return 1
  fi
  media_unchanged
}
# END MEDIA STATE FUNCTIONS
snapshot_media || exit 20
gps_before=$(systemctl show "${gps[@]}" -p Id -p ActiveState -p MainPID -p NRestarts --no-pager) || exit 1
[[ -n "$gps_before" ]] || exit 1
sudo -v || exit 1
# Recheck after any password prompt before changing desktop media.
media_unchanged || { echo 'CAMERA_STOP=MEDIA_CHANGED_DURING_START; no media changed'; exit 75; }
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
  restore_media_units || restored=STOP_REVIEW
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
if ((${#media_active[@]})); then
  timeout --kill-after=3s 20s systemctl --user stop "${media_active[@]}" || exit 1
fi
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
arguments+=("${endpoint[@]}")
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
