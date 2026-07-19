#!/bin/bash
#
# check.sh <device>
#
# Provera da li uredjaj postoji i da li je block device.
# Exit: 0 OK / 10 ne postoji / 11 nije block device

source "$(dirname "$0")/common.sh"

[ $# -eq 1 ] || fail $STATUS_INTERNAL_ERROR "Usage: check.sh <device>"

check_block_device "$1"

exit $STATUS_OK
