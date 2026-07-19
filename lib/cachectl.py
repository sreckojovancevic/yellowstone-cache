#!/usr/bin/env python3

"""
Yellowstone Cache

Visokonivovska administracija — orkestracija cele procedure.

Glavne operacije (QNAP-stil "cache block device" iznad postojećeg LIO-a):

  up(name)   - stop LIO -> RAM disk / cache uređaj -> dm-cache ->
               repoint "dev" u saveconfig.json (WWN NETAKNUT) ->
               start LIO. Uz automatski rollback ako bilo šta pukne.

  down(name) - stop LIO -> vrati "dev" na origin -> ukloni dm-cache
               i RAM disk -> start LIO.

Sve funkcije vraćaju: {"code": <status kod>, "message": <poruka>, ...}
"""

import time

from lib import validator
from lib import status
from lib import state
from lib import shell
from lib import lio
from lib import sysinfo
from lib import stats as statsmod
from lib import logger
from lib.config import load_config, ConfigError
from lib.cache import manager


def _engine_and_config():
    config = load_config()
    return manager.load(config), config


def _err(code, message):
    return {"code": code, "message": message}


def up(name):
    """
    Zakači cache na LIO backstore `name` (ime iz saveconfig.json).
    """

    try:
        engine, config = _engine_and_config()
    except ConfigError as e:
        return _err(status.STATUS_CONFIG_ERROR, str(e))

    cfg = config["cache"]

    if not cfg["enable"]:
        return _err(status.STATUS_CACHE_DISABLED,
                    "Cache is disabled in configuration.")

    if state.get(name):
        return _err(status.STATUS_CACHE_EXISTS,
                    f"Cache for '{name}' already exists.")

    # 1. Backstore mora postojati u saveconfig.json
    try:
        obj = lio.get_storage_object(name)
    except lio.LioError as e:
        return _err(status.STATUS_LIO_ERROR, str(e))

    if obj is None:
        return _err(status.STATUS_LIO_ERROR,
                    f"Backstore '{name}' not found in saveconfig.json.")

    origin = obj["dev"]

    # 2. Origin -> stabilna by-id putanja (sdX nije stabilno posle reboot-a)
    resolved = shell.run("resolve_device.sh", [origin])

    if resolved["code"] != status.STATUS_OK:
        return _err(resolved["code"],
                    f"Origin device check failed: {origin}")

    origin_stable = resolved["stdout"]

    # 3. RAM provera (fail-fast, PRE gašenja LIO-a)
    if cfg["cache_type"] == "ram":
        ok, available, needed = sysinfo.check_memory(
            cfg["cache_ram"], cfg["memory_headroom"])

        if not ok:
            return _err(
                status.STATUS_CONFIG_ERROR,
                f"Not enough memory: need {needed // 1024**2} MB "
                f"(cache + headroom), available {available // 1024**2} MB.")

    dm_name = f"{name}Cached"

    # ---- Od ove tačke LIO ide dole: sve mora imati rollback ----

    t0 = time.monotonic()

    stopped = shell.run("lio_stop.sh")

    if stopped["code"] != status.STATUS_OK:
        return _err(status.STATUS_LIO_ERROR,
                    stopped["stderr"] or "Failed to stop LIO.")

    backup = None
    ram_created = False
    dm_created = False

    try:
        # 4. Cache uređaj
        if cfg["cache_type"] == "ram":
            ram = shell.run("ram_create.sh",
                            [cfg["cache_ram"] // 1024**2,
                             1 if cfg["ram_prealloc"] else 0])

            if ram["code"] != status.STATUS_OK:
                raise _Rollback(ram["code"],
                                ram["stderr"] or "RAM disk creation failed.")

            cache_dev = ram["stdout"]
            ram_created = True
        else:
            cache_dev = cfg["cache_device"]

            check = engine.verify(cache_dev)

            if check["code"] != status.STATUS_OK:
                raise _Rollback(check["code"],
                                f"Cache device check failed: {cache_dev}")

        # 5. dm-cache
        created = engine.create(dm_name, origin, cache_dev, cfg["cache_mode"])

        if created["code"] != status.STATUS_OK:
            raise _Rollback(created["code"],
                            created["stderr"] or "dm-cache creation failed.")

        dm_created = True

        # 6. Backup pa state zapis (phase=attaching) PRE repoint-a:
        #    ako padnemo izmedju repoint-a i starta, state zna za
        #    proceduru i down/repair mogu da je razrese (docs/state.md).
        backup = lio.backup_config()

        state.register(name, {
            "phase": state.PHASE_ATTACHING,
            "origin": origin_stable,
            "origin_at_attach": origin,
            "cache_type": cfg["cache_type"],
            "cache_device": cache_dev,
            "mode": cfg["cache_mode"],
            "dm_name": dm_name,
            "backup": str(backup),
        })

        # 7. Repoint u saveconfig.json — SAMO "dev" polje, WWN netaknut
        lio.set_device(name, f"/dev/mapper/{dm_name}")

        # 8. LIO nazad
        started = shell.run("lio_start.sh")

        if started["code"] != status.STATUS_OK:
            raise _Rollback(status.STATUS_LIO_ERROR,
                            started["stderr"] or "Failed to restart LIO.")

    except _Rollback as e:
        state.unregister(name)
        _rollback(engine, dm_name, dm_created, ram_created, backup)
        return _err(e.code, f"{e.message} (rolled back, LIO on origin)")

    duration = round(time.monotonic() - t0, 2)

    state.set_phase(name, state.PHASE_ACTIVE)

    logger.info(f"Cache up for '{name}' in {duration}s (downtime window).")

    return {
        "code": status.STATUS_OK,
        "message": f"Cache attached to '{name}' "
                   f"(downtime {duration}s, wwn untouched).",
        "downtime_seconds": duration,
    }


def down(name):
    """
    Otkači cache sa backstore-a `name` i vrati LIO na origin.
    """

    try:
        engine, config = _engine_and_config()
    except ConfigError as e:
        return _err(status.STATUS_CONFIG_ERROR, str(e))

    info = state.get(name)

    if not info:
        return _err(status.STATUS_CACHE_MISSING,
                    f"Cache for '{name}' is not registered.")

    t0 = time.monotonic()

    # phase=detaching PRE prvog destruktivnog koraka (docs/state.md)
    state.set_phase(name, state.PHASE_DETACHING)

    stopped = shell.run("lio_stop.sh")

    if stopped["code"] != status.STATUS_OK:
        return _err(status.STATUS_LIO_ERROR,
                    stopped["stderr"] or "Failed to stop LIO.")

    # 1. Vrati "dev" na origin (WWN i dalje netaknut)
    try:
        lio.backup_config()
        lio.set_device(name, info["origin"])
    except lio.LioError as e:
        shell.run("lio_start.sh")
        return _err(status.STATUS_LIO_ERROR, str(e))

    # 2. Ukloni dm-cache (destroy_cache.sh radi cleaner flush;
    #    kod writethrough dirty je ionako 0)
    destroyed = engine.destroy(info["dm_name"])

    if destroyed["code"] != status.STATUS_OK:
        shell.run("lio_start.sh")
        return _err(destroyed["code"],
                    destroyed["stderr"] or "dm-cache removal failed "
                    "(LIO restarted on origin).")

    # 3. Ukloni RAM disk
    if info.get("cache_type") == "ram":
        shell.run("ram_destroy.sh")

    # 4. LIO nazad na origin
    started = shell.run("lio_start.sh")

    if started["code"] != status.STATUS_OK:
        return _err(status.STATUS_LIO_ERROR,
                    started["stderr"] or "Failed to restart LIO.")

    state.unregister(name)

    duration = round(time.monotonic() - t0, 2)

    logger.info(f"Cache down for '{name}' in {duration}s.")

    return {
        "code": status.STATUS_OK,
        "message": f"Cache detached from '{name}' "
                   f"(downtime {duration}s, LIO back on origin).",
        "downtime_seconds": duration,
    }


def cache_status(name):
    """Vrati status + parsiranu statistiku cache-a."""

    try:
        engine, _ = _engine_and_config()
    except ConfigError as e:
        return _err(status.STATUS_CONFIG_ERROR, str(e))

    info = state.get(name)

    if not info:
        return _err(status.STATUS_CACHE_MISSING,
                    f"Cache for '{name}' is not registered.")

    result = engine.status(info["dm_name"])

    if result["code"] != status.STATUS_OK:
        return {
            "code": status.STATUS_CACHE_MISSING,
            "message": result["stderr"] or f"Cache '{name}' not active.",
            "info": info,
            "stats": None,
        }

    return {
        "code": status.STATUS_OK,
        "message": "OK",
        "info": info,
        "stats": statsmod.parse_dmsetup_status(result["stdout"]),
    }


def validate():
    """Prosleđena validacija (da CLI ima jednu ulaznu tačku)."""

    return validator.validate()


class _Rollback(Exception):

    def __init__(self, code, message):
        self.code = code
        self.message = message


def _rollback(engine, dm_name, dm_created, ram_created, backup):
    """Vrati sistem u stanje pre up() — LIO na origin, bez cache slojeva."""

    logger.warning(f"Rolling back cache attach for '{dm_name}'.")

    if backup is not None:
        try:
            lio.restore_backup(backup)
        except OSError as e:
            logger.error(f"Rollback: config restore failed: {e}")

    if dm_created:
        engine.destroy(dm_name)

    if ram_created:
        shell.run("ram_destroy.sh")

    shell.run("lio_start.sh")
