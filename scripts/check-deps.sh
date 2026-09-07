#!/bin/sh
# Install-time dependency check. herdr aborts the install if this exits non-zero.
set -eu

if ! command -v python3 >/dev/null 2>&1; then
    echo "herdr-model-badge needs python3 on PATH (3.8 or newer)." >&2
    exit 1
fi

python3 - <<'PY'
import sys

if sys.version_info < (3, 8):
    sys.exit("herdr-model-badge needs python3 3.8 or newer; found %s" % sys.version.split()[0])
PY

echo "herdr-model-badge: python3 $(python3 -c 'import sys; print(sys.version.split()[0])') ok"
