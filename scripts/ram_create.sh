#!/bin/bash
#
# ram_create.sh <size_mb> [prealloc]
#
# Kreira RAM disk preko brd modula i ispisuje putanju (/dev/ram0).
# Ako je brd vec ucitan sa istom velicinom - ponovo ga koristi.
# Ako je ucitan sa drugom velicinom - greska (potreban rmmod).
#
# prealloc=1: dodirni svaku stranicu odmah (dd nulama preko celog
# uredjaja) - memorija je REZERVISANA unapred umesto lenje alokacije.

source "$(dirname "$0")/common.sh"

[ $# -ge 1 ] || fail $STATUS_INTERNAL_ERROR \
    "Usage: ram_create.sh <size_mb> [prealloc]"

SIZE_MB="$1"
PREALLOC="${2:-0}"
require_root

case "$SIZE_MB" in
    ''|*[!0-9]*) fail $STATUS_CONFIG_ERROR "Invalid size: $SIZE_MB" ;;
esac

WANT_SECTORS=$(( SIZE_MB * 2048 ))

if [ -b /dev/ram0 ]; then
    HAVE_SECTORS=$(blockdev --getsz /dev/ram0) \
        || fail $STATUS_INTERNAL_ERROR "Cannot read /dev/ram0 size."

    [ "$HAVE_SECTORS" -eq "$WANT_SECTORS" ] \
        || fail $STATUS_CACHE_EXISTS \
           "/dev/ram0 exists with different size (rmmod brd first)."
else
    # rd_size je u KiB
    modprobe brd rd_nr=1 rd_size=$(( SIZE_MB * 1024 )) \
        || fail $STATUS_INTERNAL_ERROR "modprobe brd failed."

    [ -b /dev/ram0 ] \
        || fail $STATUS_INTERNAL_ERROR "/dev/ram0 did not appear."
fi

if [ "$PREALLOC" = "1" ]; then
    dd if=/dev/zero of=/dev/ram0 bs=1M count="$SIZE_MB" \
        oflag=direct 2>/dev/null \
        || fail $STATUS_INTERNAL_ERROR "RAM preallocation failed."
fi

echo /dev/ram0
exit $STATUS_OK
