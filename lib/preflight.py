#!/usr/bin/env python3

"""
Yellowstone Cache

Preflight provere pre destruktivnih operacija (up/down/reset).

Motiv iz prakse: `targetctl clear` visi u D stanju kada initiator
(ESXi) ima komande u letu nad LUN-om. Proces se ne može ubiti i jedini
izlaz je reboot. Zato pre gašenja LIO-a proveravamo da li neko aktivno
koristi uređaj — i odbijamo operaciju uz jasno objašnjenje.

Detekcija je namerno jednostavna i portabilna: uzorkuje se
/proc/diskstats nad uređajem koji LIO trenutno eksportuje. Ako u
uzorku ima završenih I/O operacija, neko ga koristi.
"""

import time
from pathlib import Path

# Prag: ispod ovoliko operacija u uzorku smatramo da je uređaj miran
# (ESXi VMFS heartbeat je nizak ali nije nula).
IDLE_THRESHOLD = 8


def _dm_device_node(dm_name):
    """Za dm ime (npr. TestDiskCached) vrati 'dm-N' ili None."""

    for entry in Path("/sys/block").glob("dm-*"):
        name_file = entry / "dm" / "name"
        try:
            if name_file.read_text().strip() == dm_name:
                return entry.name
        except OSError:
            continue

    return None


def _kernel_name(device_path):
    """
    Za putanju uređaja (/dev/sdb, /dev/disk/by-id/..., /dev/mapper/X)
    vrati kernel ime kakvo stoji u /proc/diskstats (sdb, dm-3...).
    """

    path = Path(device_path)

    if not path.exists():
        return None

    if str(path).startswith("/dev/mapper/"):
        return _dm_device_node(path.name)

    return path.resolve().name


def _read_io_count(kernel_name):
    """Ukupan broj završenih čitanja i upisa za uređaj."""

    try:
        with open("/proc/diskstats", "r") as f:
            for line in f:
                fields = line.split()
                if len(fields) > 7 and fields[2] == kernel_name:
                    # polje 3 = završena čitanja, polje 7 = završeni upisi
                    return int(fields[3]) + int(fields[7])
    except OSError:
        pass

    return None


def device_activity(device_path, seconds=2.0):
    """
    Izmeri I/O aktivnost nad uređajem tokom `seconds`.

    Vraća (ops, kernel_name) ili (None, None) ako se ne može izmeriti
    (nepoznat uređaj — tada ne blokiramo operaciju).
    """

    kernel_name = _kernel_name(device_path)

    if not kernel_name:
        return None, None

    first = _read_io_count(kernel_name)

    if first is None:
        return None, kernel_name

    time.sleep(seconds)

    second = _read_io_count(kernel_name)

    if second is None:
        return None, kernel_name

    return second - first, kernel_name


def check_idle(device_path, seconds=2.0):
    """
    Vrati (ok, poruka).

    ok=False znači da uređaj aktivno koristi neki initiator i da
    gašenje LIO-a verovatno neće proći (visi u D stanju).
    """

    ops, kernel_name = device_activity(device_path, seconds)

    if ops is None:
        return True, (f"Activity check skipped (cannot sample "
                      f"{device_path}).")

    if ops > IDLE_THRESHOLD:
        return False, (
            f"Device {device_path} ({kernel_name}) is in active use: "
            f"{ops} I/O operations in {seconds:g}s.\n"
            "       An initiator (e.g. ESXi) is still using this LUN. "
            "Stopping LIO now would most likely hang in D state and "
            "require a reboot.\n"
            "       Power off / unregister the VMs and unmount the "
            "datastore first, or re-run with --force if you accept "
            "the risk.")

    return True, f"Device idle ({ops} ops in {seconds:g}s)."
