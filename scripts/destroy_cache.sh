#!/bin/bash
#
# destroy_cache.sh <name>
#
# Flush dirty blokova (cleaner policy), zatim uklanja cache mapiranje
# i pomocne linear target-e. Origin uredjaj ostaje netaknut.

source "$(dirname "$0")/common.sh"

[ $# -eq 1 ] || fail $STATUS_INTERNAL_ERROR "Usage: destroy_cache.sh <name>"

NAME="$1"

require_root
dm_exists "$NAME" || fail $STATUS_CACHE_MISSING "Cache '$NAME' does not exist."

# Flush: prebaci na cleaner policy i sacekaj da dirty padne na 0
TABLE=$(dmsetup table "$NAME")

dmsetup suspend "$NAME" \
    && dmsetup reload "$NAME" --table "${TABLE/default/cleaner}" \
    && dmsetup resume "$NAME" \
    || fail $STATUS_INTERNAL_ERROR "Failed to switch to cleaner policy."

for _ in $(seq 1 300); do
    DIRTY=$(dmsetup status "$NAME" | awk '{print $14}')
    [ "$DIRTY" = "0" ] && break
    sleep 1
done

[ "$DIRTY" = "0" ] || fail $STATUS_INTERNAL_ERROR "Flush timeout (dirty=$DIRTY)."

dmsetup remove "$NAME" \
    || fail $STATUS_INTERNAL_ERROR "Failed to remove cache target."

dmsetup remove "${NAME}-cdata" 2>/dev/null
dmsetup remove "${NAME}-cmeta" 2>/dev/null

exit $STATUS_OK
