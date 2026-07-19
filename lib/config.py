#!/usr/bin/env python3

"""
Yellowstone Cache

Učitavanje konfiguracije iz etc/yellowstone.cache.

Vraća ugnježdenu strukturu {"cache": {...}}.
Bezbednosno pravilo ugrađeno u kod: cache_type=ram dozvoljava
ISKLJUČIVO writethrough (RAM + writeback = gubitak podataka
pri nestanku struje).
"""

import configparser

from lib import paths
from lib import status


DEFAULTS = {
    "enable": True,
    "engine": "dmsetup",
    "cache_type": "ram",
    "cache_ram": "12G",
    "ram_prealloc": True,
    "memory_headroom": "4G",
    "cache_device": "",
    "cache_mode": "writethrough",
}

VALID_MODES = ("writethrough", "writeback")
VALID_TYPES = ("ram", "device")


def parse_size(text):
    """'12G' / '512M' / '4096K' / '123' (bajtovi) -> int bajtova."""

    text = str(text).strip().upper()

    units = {"K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4}

    if text and text[-1] in units:
        return int(float(text[:-1]) * units[text[-1]])

    return int(text)


def load_config():
    """Učitaj i validiraj konfiguraciju."""

    parser = configparser.ConfigParser()
    read = parser.read(paths.CONFIG_FILE)

    if not read:
        raise ConfigError(f"Config file not found: {paths.CONFIG_FILE}")

    if not parser.has_section("cache"):
        raise ConfigError("Missing [cache] section")

    def get(key):
        return parser.get("cache", key, fallback=DEFAULTS[key])

    try:
        cache = {
            "enable": parser.getboolean(
                "cache", "enable", fallback=DEFAULTS["enable"]),
            "engine": get("engine"),
            "cache_type": get("cache_type"),
            "cache_ram": parse_size(get("cache_ram")),
            "ram_prealloc": parser.getboolean(
                "cache", "ram_prealloc", fallback=DEFAULTS["ram_prealloc"]),
            "memory_headroom": parse_size(get("memory_headroom")),
            "cache_device": get("cache_device"),
            "cache_mode": get("cache_mode"),
        }
    except ValueError as e:
        raise ConfigError(f"Invalid value in config: {e}")

    if cache["cache_type"] not in VALID_TYPES:
        raise ConfigError(
            f"Invalid cache_type '{cache['cache_type']}' "
            f"(expected: {', '.join(VALID_TYPES)})")

    if cache["cache_mode"] not in VALID_MODES:
        raise ConfigError(
            f"Invalid cache_mode '{cache['cache_mode']}' "
            f"(expected: {', '.join(VALID_MODES)})")

    # Tvrdo bezbednosno pravilo — bez mogucnosti override-a.
    if cache["cache_type"] == "ram" and cache["cache_mode"] == "writeback":
        raise ConfigError(
            "cache_type=ram allows only writethrough. "
            "RAM + writeback means data loss on power failure.")

    if cache["cache_type"] == "device" and not cache["cache_device"]:
        raise ConfigError("cache_type=device requires cache_device.")

    if cache["cache_type"] == "ram" and cache["cache_ram"] < 64 * 1024**2:
        raise ConfigError("cache_ram must be at least 64M.")

    return {"cache": cache}


class ConfigError(Exception):
    """Greška konfiguracije. Nosilac je status.STATUS_CONFIG_ERROR."""

    code = status.STATUS_CONFIG_ERROR


if __name__ == "__main__":

    cfg = load_config()["cache"]

    for key, value in cfg.items():
        print(f"{key:<16}: {value}")
