#!/usr/bin/env python3

"""
Yellowstone Cache

Evidencija kreiranih cache uređaja (state/caches.json).
Formalna specifikacija formata: docs/state.md + docs/state.schema.json

Ovo NIJE source of truth za dm stanje (to je kernel / dmsetup),
već evidencija onoga što je Yellowstone kreirao — i SIDRO ZA OPORAVAK:
posle pada sistema, poređenje state-a, saveconfig.json i kernel dm
stanja govori dokle je procedura stigla.

Format fajla (version 1):

    {
      "version": 1,
      "caches": {
        "<name>": { ... vidi docs/state.md ... }
      }
    }

Ključno pravilo životnog ciklusa (vidi docs/state.md):
zapis sa phase="attaching"/"detaching" posle reboot-a znači
prekinutu proceduru koju treba razrešiti — NIKAD ga ne ignorisati.
"""

import json

from lib import paths

STATE_VERSION = 1

PHASE_ATTACHING = "attaching"
PHASE_ACTIVE = "active"
PHASE_DETACHING = "detaching"

VALID_PHASES = (PHASE_ATTACHING, PHASE_ACTIVE, PHASE_DETACHING)

REQUIRED_FIELDS = (
    "phase", "origin", "origin_at_attach", "cache_type",
    "cache_device", "mode", "dm_name",
)


class StateError(Exception):
    """Korumpiran ili nečitljiv state fajl. Fajl se NE dira —
    ostaje na disku za ručnu analizu."""


def _load():
    if not paths.STATE_FILE.exists():
        return {"version": STATE_VERSION, "caches": {}}

    try:
        with open(paths.STATE_FILE, "r") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        # Atomičan upis sprečava polu-upisan fajl; ovo je korupcija
        # diska ili ručna izmena. Ne rušimo se sa traceback-om i ne
        # diramo fajl — admin odlučuje (docs/state.md).
        raise StateError(
            f"State file is corrupted ({paths.STATE_FILE}): {e}. "
            "File left untouched for inspection.")
    except OSError as e:
        raise StateError(f"Cannot read state file: {e}")

    if not isinstance(data, dict):
        raise StateError(
            f"State file has invalid structure ({paths.STATE_FILE}).")

    # Migracija sa pred-verzionisanog formata (flat dict imena)
    if "version" not in data:
        data = {"version": STATE_VERSION, "caches": data}

    if not isinstance(data.get("caches"), dict):
        raise StateError(
            f"State file has invalid 'caches' section ({paths.STATE_FILE}).")

    return data


def _save(data):
    paths.STATE.mkdir(parents=True, exist_ok=True)

    tmp = str(paths.STATE_FILE) + ".tmp"

    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")

    import os
    os.replace(tmp, paths.STATE_FILE)


def register(name, info):
    """
    Zabeleži cache. `info` mora sadržati sva polja iz REQUIRED_FIELDS
    (minimalna ručna validacija — bez spoljnih zavisnosti).
    """

    missing = [f for f in REQUIRED_FIELDS if f not in info]

    if missing:
        raise ValueError(f"State record missing fields: {missing}")

    if info["phase"] not in VALID_PHASES:
        raise ValueError(f"Invalid phase: {info['phase']}")

    data = _load()
    data["caches"][name] = info
    _save(data)


def set_phase(name, phase):
    """Promeni fazu postojećeg zapisa."""

    if phase not in VALID_PHASES:
        raise ValueError(f"Invalid phase: {phase}")

    data = _load()

    if name not in data["caches"]:
        raise KeyError(f"No state record for '{name}'")

    data["caches"][name]["phase"] = phase
    _save(data)


def unregister(name):
    """Ukloni cache iz evidencije."""

    data = _load()

    if name in data["caches"]:
        del data["caches"][name]
        _save(data)


def get(name):
    """Vrati zapis o cache-u ili None."""

    return _load()["caches"].get(name)


def list_all():
    """Vrati sve zapise ({name: info})."""

    return _load()["caches"]


def incomplete():
    """Vrati zapise čija procedura nije završena (phase != active)."""

    return {
        name: info
        for name, info in _load()["caches"].items()
        if info.get("phase") != PHASE_ACTIVE
    }
