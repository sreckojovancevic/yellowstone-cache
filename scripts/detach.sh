#!/bin/bash
#
# detach.sh <name>
#
# Suspenduje cache uredjaj (I/O se zadrzava dok se ne pozove attach).
# Suspend radi implicitni flush kes buffera.

source "$(dirname "$0")/common.sh"

[ $# -eq 1 ] || fail $STATUS_INTERNAL_ERROR "Usage: detach.sh <name>"

NAME="$1"

require_root
dm_exists "$NAME" || fail $STATUS_CACHE_MISSING "Cache '$NAME' does not exist."

dmsetup suspend "$NAME" \
    || fail $STATUS_INTERNAL_ERROR "Failed to suspend '$NAME'."

exit $STATUS_OK
