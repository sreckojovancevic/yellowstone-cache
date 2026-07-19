#!/usr/bin/env python3

"""
Yellowstone Cache

Sistemske informacije (čitanje /proc — bez izvršavanja komandi).
"""


def mem_available_bytes():
    """MemAvailable iz /proc/meminfo, u bajtovima."""

    with open("/proc/meminfo", "r") as f:
        for line in f:
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) * 1024

    raise RuntimeError("MemAvailable not found in /proc/meminfo")


def check_memory(required, headroom):
    """
    Proveri da li sistem ima dovoljno memorije za RAM cache.

    Vraća (ok: bool, available: int, needed: int).
    """

    available = mem_available_bytes()
    needed = required + headroom

    return available >= needed, available, needed
