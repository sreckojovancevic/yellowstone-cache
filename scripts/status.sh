#!/bin/bash
#
# status.sh <name>
#
# Ispisuje sirovi `dmsetup status` red za cache uredjaj na stdout.
# Parsiranje radi lib/stats.py.

source "$(dirname "$0")/common.sh"

[ $# -eq 1 ] || fail $STATUS_INTERNAL_ERROR "Usage: status.sh <name>"

NAME="$1"

dm_exists "$NAME" || fail $STATUS_CACHE_MISSING "Cache '$NAME' does not exist."

dmsetup status "$NAME" \
    || fail $STATUS_INTERNAL_ERROR "Failed to read status of '$NAME'."

exit $STATUS_OK
