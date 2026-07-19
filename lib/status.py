"""
Yellowstone Cache

Status kodovi. Bez poslovne logike i bez prikaza.
"""

STATUS_OK               = 0

STATUS_DEVICE_MISSING   = 10
STATUS_NOT_BLOCK        = 11

STATUS_CONFIG_ERROR     = 20

STATUS_LIO_ERROR        = 30

STATUS_CACHE_EXISTS     = 40
STATUS_CACHE_DISABLED   = 41
STATUS_CACHE_MISSING    = 42

STATUS_INTERNAL_ERROR   = 99


MESSAGES = {
    STATUS_OK:              "OK",
    STATUS_DEVICE_MISSING:  "Device does not exist",
    STATUS_NOT_BLOCK:       "Not a block device",
    STATUS_CONFIG_ERROR:    "Configuration error",
    STATUS_LIO_ERROR:       "LIO configuration error",
    STATUS_CACHE_EXISTS:    "Cache already exists",
    STATUS_CACHE_DISABLED:  "Cache is disabled",
    STATUS_CACHE_MISSING:   "Cache does not exist",
    STATUS_INTERNAL_ERROR:  "Internal error",
}


def message(code):
    """Vrati podrazumevanu poruku za status kod."""
    return MESSAGES.get(code, "Unknown status")
