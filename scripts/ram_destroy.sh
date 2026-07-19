#!/bin/bash
#
# ram_destroy.sh
#
# Uklanja brd RAM disk. Sme se zvati tek kad ga nista ne koristi
# (posle destroy_cache.sh).

source "$(dirname "$0")/common.sh"

require_root

[ -b /dev/ram0 ] || exit $STATUS_OK   # nema sta da se uklanja

rmmod brd \
    || fail $STATUS_INTERNAL_ERROR "rmmod brd failed (device still in use?)."

exit $STATUS_OK
