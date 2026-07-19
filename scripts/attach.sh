#!/bin/bash
#
# attach.sh <name>
#
# Aktivira (resume) suspendovan cache uredjaj.

source "$(dirname "$0")/common.sh"

[ $# -eq 1 ] || fail $STATUS_INTERNAL_ERROR "Usage: attach.sh <name>"

NAME="$1"

require_root
dm_exists "$NAME" || fail $STATUS_CACHE_MISSING "Cache '$NAME' does not exist."

dmsetup resume "$NAME" \
    || fail $STATUS_INTERNAL_ERROR "Failed to resume '$NAME'."

exit $STATUS_OK
