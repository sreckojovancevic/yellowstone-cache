#!/bin/bash
#
# lio_stop.sh
#
# Zaustavlja LIO (uklanja runtime konfiguraciju iz kernela).
# saveconfig.json ostaje netaknut — on je source of truth.

source "$(dirname "$0")/common.sh"

require_root

command -v targetctl >/dev/null 2>&1 \
    || fail $STATUS_LIO_ERROR "targetctl not found (install targetcli-fb)."

targetctl clear \
    || fail $STATUS_LIO_ERROR "targetctl clear failed."

exit $STATUS_OK
