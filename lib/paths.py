#!/usr/bin/env python3

"""
Yellowstone Cache

Centralne putanje projekta.
Jedini modul koji definiše lokacije na disku ("jedan izvor istine").

BASE se izvodi iz lokacije ovog fajla, pa projekat radi i van
/opt/yellowstone (razvoj, testiranje), a u produkciji je to /opt/yellowstone.
"""

from pathlib import Path

BASE = Path(__file__).resolve().parent.parent

ETC = BASE / "etc"
SCRIPTS = BASE / "scripts"
LOGS = BASE / "logs"
STATE = BASE / "state"

CONFIG_FILE = ETC / "yellowstone.cache"
LOG_FILE = LOGS / "yellowstone.log"
STATE_FILE = STATE / "caches.json"

LIO_SAVECONFIG = Path("/etc/rtslib-fb-target/saveconfig.json")
