#!/usr/bin/env python3

"""
Yellowstone Cache

Cache Engine Manager

- učitava konfiguraciju
- učitava izabrani Cache Engine
- proverava interfejs
- vraća instancu engine-a
"""

import importlib

from lib.config import load_config
from lib.cache.interface import CacheEngine


def load(config=None):
    """
    Učitaj konfigurisani Cache Engine.
    Config se može prosledit spolja (izbegava dvostruko čitanje fajla).
    """

    if config is None:
        config = load_config()

    engine_name = config["cache"]["engine"]

    module = importlib.import_module(f"lib.cache.{engine_name}")

    if not hasattr(module, "engine"):
        raise RuntimeError(
            f"Engine '{engine_name}' does not export 'engine'")

    engine = module.engine

    if not isinstance(engine, CacheEngine):
        raise RuntimeError(
            f"Engine '{engine_name}' does not implement CacheEngine")

    return engine
