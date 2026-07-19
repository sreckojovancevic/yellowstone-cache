#!/bin/bash
#
# Yellowstone Cache - zajednicke funkcije za skripte
#
# Exit kodovi MORAJU odgovarati lib/status.py

STATUS_OK=0
STATUS_DEVICE_MISSING=10
STATUS_NOT_BLOCK=11
STATUS_CONFIG_ERROR=20
STATUS_LIO_ERROR=30
STATUS_CACHE_EXISTS=40
STATUS_CACHE_DISABLED=41
STATUS_CACHE_MISSING=42
STATUS_INTERNAL_ERROR=99

fail() {
    # fail <exit_code> <message>
    echo "$2" >&2
    exit "$1"
}

require_root() {
    [ "$(id -u)" -eq 0 ] || fail $STATUS_INTERNAL_ERROR "Must run as root."
}

check_block_device() {
    # check_block_device <device>
    [ -e "$1" ] || fail $STATUS_DEVICE_MISSING "Device does not exist: $1"
    [ -b "$1" ] || fail $STATUS_NOT_BLOCK "Not a block device: $1"
}

dm_exists() {
    # dm_exists <name>
    dmsetup info "$1" >/dev/null 2>&1
}
