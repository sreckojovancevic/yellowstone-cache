#!/bin/bash
#
# resolve_device.sh <device>
#
# Ispisuje stabilnu /dev/disk/by-id/ putanju za uredjaj.
# Prednost ima wwn-* ime. Ako stabilno ime ne postoji (npr. /dev/ram0,
# dm uredjaji), vraca originalnu putanju.

source "$(dirname "$0")/common.sh"

[ $# -eq 1 ] || fail $STATUS_INTERNAL_ERROR "Usage: resolve_device.sh <device>"

DEV=$(readlink -f "$1") || fail $STATUS_DEVICE_MISSING "Cannot resolve: $1"
[ -b "$DEV" ] || fail $STATUS_DEVICE_MISSING "Not a block device: $1"

FALLBACK=""

for link in /dev/disk/by-id/*; do
    [ -e "$link" ] || continue
    [ "$(readlink -f "$link")" = "$DEV" ] || continue

    case "$(basename "$link")" in
        wwn-*) echo "$link"; exit $STATUS_OK ;;
        *)     [ -z "$FALLBACK" ] && FALLBACK="$link" ;;
    esac
done

if [ -n "$FALLBACK" ]; then
    echo "$FALLBACK"
else
    echo "$1"
fi

exit $STATUS_OK
