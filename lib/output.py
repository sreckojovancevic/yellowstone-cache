#!/usr/bin/env python3

"""
Yellowstone Cache

Output modul — isključivo prikaz informacija korisniku.
Bez poslovne logike.

FIX: poređenja koriste status.STATUS_OK umesto literala 0.
Dodato: emit_json() za automatizaciju i print_status() za cache statistiku.
"""

import json

from lib.version import NAME, VERSION
from lib import status


def header():
    """Print application header."""

    print(f"{NAME} {VERSION}")
    print("=" * (len(NAME) + len(VERSION) + 1))
    print()


def section(title):
    """Print section title."""

    print(title)
    print("-" * len(title))


def line(label, value):
    """Print one labeled line."""

    print(f"{label:<22}: {value}")


def success(message):
    print(f"[ OK ] {message}")


def warning(message):
    print(f"[WARN] {message}")


def error(message):
    print(f"[FAIL] {message}")


def emit_json(data):
    """JSON izlaz za automatizaciju (bez zaglavlja i dekoracija)."""

    print(json.dumps(data, indent=2))


def print_validation(result):
    """Display validation result."""

    header()

    section("Validation")
    print()

    storage = result.get("storage", [])

    if not storage:
        warning("No storage objects found.")
        print()
    else:
        section("Storage Objects")

        for item in storage:
            line("Name", item["name"])
            line("Device", item["device"])
            line("Status", item["message"])
            print()

    section("Overall")

    if result["code"] == status.STATUS_OK:
        success(result["message"])
    else:
        error(result["message"])


def print_status(name, info, stats):
    """Display cache status and statistics."""

    header()

    section(f"Cache: {name}")
    print()

    if info:
        line("Origin", info["origin"])
        line("Cache device", info["cache_device"])
        line("Configured mode", info["mode"])
        print()

    if not stats:
        warning("Cache target not active or not a dm-cache device.")
        return

    section("Statistics")

    line("Mode", stats["mode"])
    line("Cache usage", f'{stats["cache_used"]}/{stats["cache_total"]} '
                        f'blocks ({stats["cache_usage_percent"]}%)')
    line("Metadata usage", f'{stats["metadata_used"]}/{stats["metadata_total"]}')
    line("Read hits/misses", f'{stats["read_hits"]}/{stats["read_misses"]} '
                             f'(ratio {stats["read_hit_ratio"]})')
    line("Write hits/misses", f'{stats["write_hits"]}/{stats["write_misses"]} '
                              f'(ratio {stats["write_hit_ratio"]})')
    line("Dirty blocks", stats["dirty"])
    line("Promotions", stats["promotions"])
    line("Demotions", stats["demotions"])
