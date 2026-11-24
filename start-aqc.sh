#!/bin/sh
# Open the saved-results app with an existing Python. No installs or downloads.
set -u

AQC_ROOT=$(CDPATH= cd -P "$(dirname "$0")" && pwd) || {
    printf '%s\n' 'AQC: cannot locate the extracted application folder.' >&2
    exit 2
}
cd "$AQC_ROOT" || exit 2

if [ ! -f "$AQC_ROOT/aqc_app/__main__.py" ]; then
    printf '%s\n' 'AQC: application files are missing.' 'Extract the complete repository/archive, then run start-aqc.sh again.' >&2
    exit 2
fi

aqc_python_usable() {
    "$1" -I -S -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1
}

if [ -n "${AQC_PYTHON:-}" ]; then
    if ! aqc_python_usable "$AQC_PYTHON"; then
        printf '%s\n' 'AQC: AQC_PYTHON must name an existing Python 3.10 or newer executable.' 'Use an executable path without extra command-line arguments.' >&2
        exit 2
    fi
    AQC_EXECUTABLE=$AQC_PYTHON
else
    AQC_EXECUTABLE=
    for AQC_CANDIDATE in "$AQC_ROOT/.venv/bin/python" python3 python; do
        if aqc_python_usable "$AQC_CANDIDATE"; then
            AQC_EXECUTABLE=$AQC_CANDIDATE
            break
        fi
    done
    if [ -z "$AQC_EXECUTABLE" ]; then
        printf '%s\n' 'AQC: Python 3.10 or newer was not found.' 'Install Python separately, or set AQC_PYTHON to an existing Python executable.' 'Opening saved results does not require RDKit, NumPy, Matplotlib, pip, or a virtual environment.' >&2
        exit 2
    fi
fi

printf '%s\n' 'Starting AQC on this computer. Keep this terminal open; press Ctrl+C to stop.'
exec "$AQC_EXECUTABLE" -m aqc_app "$@"
