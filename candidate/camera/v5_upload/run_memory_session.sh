#!/usr/bin/env bash
# Explicit foreground session; same ownership, readiness and restoration guard.
stage=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P) || exit 1
exec bash "$stage/run_memory_trial.sh" "$@" --keep-running
