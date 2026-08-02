#!/bin/bash
set -e

# OpenPup redirects Code Puppy's config into OPENPUP_HOME. Sync only the
# host-level model/auth files there; generated agents and runtime state remain
# owned by OpenPup under /data.
if [ -d /host-code-puppy ]; then
    mkdir -p /data/code_puppy
    if [ -f /host-code-puppy/puppy.cfg ]; then
        cp -f /host-code-puppy/puppy.cfg /data/code_puppy/puppy.cfg
    fi
    find /host-code-puppy -maxdepth 1 -type f -name '*.json' \
        -exec cp -f {} /data/code_puppy/ \;
fi

exec "$@"
