#!/bin/bash
#
# lio_start.sh
#
# Pokrece LIO iz saveconfig.json (targetctl restore).

source "$(dirname "$0")/common.sh"

require_root

command -v targetctl >/dev/null 2>&1 \
    || fail $STATUS_LIO_ERROR "targetctl not found (install targetcli-fb)."

targetctl restore \
    || fail $STATUS_LIO_ERROR "targetctl restore failed."

exit $STATUS_OK
