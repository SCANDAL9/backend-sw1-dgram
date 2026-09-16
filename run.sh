#!/usr/bin/env bash
# Launch the dgram backend from a nix-shell.
# greenlet (used by SQLAlchemy async) needs libstdc++.so.6 at runtime;
# auto-locate it under /nix/store and add it to LD_LIBRARY_PATH.
set -e
cd "$(dirname "$0")"

gcc_lib=""
for d in /nix/store/*-gcc-*-lib/lib; do
  [ -e "$d/libstdc++.so.6" ] || continue
  [ "$(od -An -tu1 -j4 -N1 "$d/libstdc++.so.6" 2>/dev/null | tr -d ' ')" = "2" ] \
    && gcc_lib="$d" && break
done
if [ -n "$gcc_lib" ] && [ "$(uname)" = "Linux" ]; then
  export LD_LIBRARY_PATH="$gcc_lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi

exec .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload "$@"