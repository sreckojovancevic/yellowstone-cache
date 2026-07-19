#!/bin/bash
#
# create_cache.sh <name> <origin_device> <cache_device> <mode>
#
# Kreira dm-cache mapiranje:
#   <name>-cmeta  - linear target za metadata (pocetak cache uredjaja)
#   <name>-cdata  - linear target za podatke (ostatak cache uredjaja)
#   <name>        - cache target iznad origin uredjaja
#
# mode: writethrough | writeback

set -o pipefail
source "$(dirname "$0")/common.sh"

[ $# -eq 4 ] || fail $STATUS_INTERNAL_ERROR \
    "Usage: create_cache.sh <name> <origin> <cache_dev> <mode>"

NAME="$1"
ORIGIN="$2"
CACHE_DEV="$3"
MODE="$4"

require_root
check_block_device "$ORIGIN"
check_block_device "$CACHE_DEV"

case "$MODE" in
    writethrough|writeback) ;;
    *) fail $STATUS_CONFIG_ERROR "Invalid mode: $MODE" ;;
esac

dm_exists "$NAME" && fail $STATUS_CACHE_EXISTS "Cache '$NAME' already exists."

ORIGIN_SECTORS=$(blockdev --getsz "$ORIGIN") \
    || fail $STATUS_INTERNAL_ERROR "Cannot read origin size."
CACHE_SECTORS=$(blockdev --getsz "$CACHE_DEV") \
    || fail $STATUS_INTERNAL_ERROR "Cannot read cache device size."

# Metadata: 1% cache uredjaja, minimum 4 MiB (8192 sektora)
META_SECTORS=$(( CACHE_SECTORS / 100 ))
[ "$META_SECTORS" -lt 8192 ] && META_SECTORS=8192
DATA_SECTORS=$(( CACHE_SECTORS - META_SECTORS ))

[ "$DATA_SECTORS" -gt 0 ] \
    || fail $STATUS_INTERNAL_ERROR "Cache device too small."

# Cache block: 256 KiB (512 sektora)
BLOCK_SIZE=512

cleanup_on_error() {
    dmsetup remove "$NAME" 2>/dev/null
    dmsetup remove "${NAME}-cdata" 2>/dev/null
    dmsetup remove "${NAME}-cmeta" 2>/dev/null
    exit $STATUS_INTERNAL_ERROR
}

dmsetup create "${NAME}-cmeta" \
    --table "0 $META_SECTORS linear $CACHE_DEV 0" \
    || cleanup_on_error

dmsetup create "${NAME}-cdata" \
    --table "0 $DATA_SECTORS linear $CACHE_DEV $META_SECTORS" \
    || cleanup_on_error

# Nuliranje pocetka metadata oblasti -> dm-cache tretira metadata kao nov
dd if=/dev/zero of="/dev/mapper/${NAME}-cmeta" bs=4K count=1 \
    conv=fsync 2>/dev/null || cleanup_on_error

dmsetup create "$NAME" --table \
    "0 $ORIGIN_SECTORS cache /dev/mapper/${NAME}-cmeta /dev/mapper/${NAME}-cdata $ORIGIN $BLOCK_SIZE 1 $MODE default 0" \
    || cleanup_on_error

echo "/dev/mapper/$NAME"
exit $STATUS_OK
