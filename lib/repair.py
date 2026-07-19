#!/usr/bin/env python3

"""
Yellowstone Cache

Repair — razrešavanje prekinutih procedura posle pada/reboot-a.
Implementira tabelu tumačenja iz docs/state.md.

Principi:

- DRY-RUN JE DEFAULT: repair() bez apply=True samo vraća plan.
- Origin za svaku akciju dolazi IZ STATE-a (saveconfig posle attach-a
  pokazuje na mapper, pa je neupotrebljiv kao izvor origin-a).
- Čiste se ISKLJUČIVO dm imena izvedena iz state zapisa (dm_name,
  -cmeta, -cdata) — nikad pattern matching po dmsetup ls.
- Ako backup ne postoji, repoint se radi direktno: set_device(origin
  iz state-a) — state.origin je stabilna by-id putanja upravo za ovo.
"""

from lib import lio
from lib import shell
from lib import state
from lib import status
from lib import logger
from lib.config import load_config, ConfigError
from lib.cache import manager


# Akcije (decide_action -> execute)
FINISH_ATTACH = "finish_attach"        # samo start LIO + phase=active
ROLLBACK_ATTACH = "rollback_attach"    # vrati na origin, očisti slojeve
FINISH_DETACH = "finish_detach"        # dovrši down
CLEANUP = "cleanup"                    # očisti dm/ram ostatke + unregister
RECREATE = "recreate"                  # sastavi keš iznova (reboot RAM keša)
HEALTHY = "healthy"                    # sve u redu, bez akcije
FORGET = "forget"                      # samo unregister (nema ničeg na sistemu)


def decide_action(phase, dev_on_mapper, dm_exists):
    """
    Čista funkcija odlučivanja — tabela iz docs/state.md.

    phase:         attaching | active | detaching (iz state-a)
    dev_on_mapper: saveconfig "dev" pokazuje na /dev/mapper/<dm_name>
    dm_exists:     dm target stvarno postoji u kernelu
    """

    if phase == state.PHASE_ATTACHING:
        if dev_on_mapper:
            return FINISH_ATTACH if dm_exists else ROLLBACK_ATTACH
        return CLEANUP if dm_exists else FORGET

    if phase == state.PHASE_DETACHING:
        if dev_on_mapper:
            # pad pre repoint-a: dovrši down uz repoint
            return FINISH_DETACH
        return FINISH_DETACH if dm_exists else FORGET

    if phase == state.PHASE_ACTIVE:
        if dev_on_mapper:
            return HEALTHY if dm_exists else RECREATE
        return CLEANUP if dm_exists else FORGET

    return FORGET


def inspect(name):
    """
    Prikupi tri izvora istine za backstore `name`.
    Vraća (info, decision, detail) ili (None, None, poruka o grešci).
    """

    info = state.get(name)

    if not info:
        return None, None, f"'{name}' is not registered in state."

    try:
        engine, _ = _engine()
    except ConfigError as e:
        return None, None, str(e)

    # Izvor istine #1: saveconfig.json
    try:
        obj = lio.get_storage_object(name)
    except lio.LioError as e:
        return None, None, str(e)

    current_dev = obj["dev"] if obj else None
    dev_on_mapper = current_dev == f'/dev/mapper/{info["dm_name"]}'

    # Izvor istine #3: kernel dm
    dm_exists = engine.status(info["dm_name"])["code"] == status.STATUS_OK

    decision = decide_action(info["phase"], dev_on_mapper, dm_exists)

    detail = (f'phase={info["phase"]}, saveconfig.dev={current_dev}, '
              f'dm_target={"present" if dm_exists else "missing"}')

    return info, decision, detail


def repair(name, apply=False):
    """
    Razreši stanje backstore-a `name`.
    apply=False (default): samo plan, bez ikakvih izmena.
    """

    info, decision, detail = inspect(name)

    if info is None:
        return {"code": status.STATUS_CACHE_MISSING, "message": detail,
                "name": name, "action": None, "applied": False}

    plan = {
        "code": status.STATUS_OK,
        "name": name,
        "action": decision,
        "detail": detail,
        "applied": False,
        "message": _describe(decision, name),
    }

    if not apply or decision == HEALTHY:
        return plan

    logger.info(f"repair '{name}': executing {decision} ({detail})")

    result = _execute(decision, name, info)
    result.update({"name": name, "action": decision,
                   "detail": detail, "applied": True})

    return result


def repair_all(apply=False):
    """Razreši sve registrovane keševe. Vraća listu rezultata."""

    return [repair(name, apply=apply) for name in state.list_all()]


def _describe(decision, name):
    return {
        HEALTHY: f"'{name}' is consistent — no action needed.",
        FINISH_ATTACH: f"Finish attach: start LIO, mark '{name}' active.",
        ROLLBACK_ATTACH: f"Rollback attach: repoint '{name}' to origin, "
                         "remove cache layers, start LIO, unregister.",
        FINISH_DETACH: f"Finish detach: repoint '{name}' to origin, "
                       "remove cache layers, start LIO, unregister.",
        CLEANUP: f"Cleanup: remove leftover cache layers of '{name}', "
                 "start LIO, unregister.",
        RECREATE: f"Recreate after reboot: rebuild RAM disk and dm-cache "
                  f"for '{name}' from state (origin from state, NOT "
                  "saveconfig), start LIO.",
        FORGET: f"Forget: nothing on the system for '{name}', unregister.",
    }[decision]


def _execute(decision, name, info):

    if decision == FINISH_ATTACH:
        started = shell.run("lio_start.sh")
        if started["code"] != status.STATUS_OK:
            return _err(status.STATUS_LIO_ERROR,
                        started["stderr"] or "Failed to start LIO.")
        state.set_phase(name, state.PHASE_ACTIVE)
        return _ok(f"'{name}' attach finished, cache active.")

    if decision in (ROLLBACK_ATTACH, FINISH_DETACH):
        return _teardown(name, info, repoint=True)

    if decision == CLEANUP:
        return _teardown(name, info, repoint=False)

    if decision == FORGET:
        if info.get("cache_type") == "ram":
            shell.run("ram_destroy.sh")
        state.unregister(name)
        shell.run("lio_start.sh")
        return _ok(f"'{name}' forgotten (no system remnants).")

    if decision == RECREATE:
        return _recreate(name, info)

    return _ok("No action.")


def _teardown(name, info, repoint):
    """Vrati saveconfig na origin (po potrebi), skini dm/ram, digni LIO.

    LIO se PRVO gasi: ako je živ i drži mapper uređaj,
    dmsetup remove bi pukao sa "device busy". Obrnut redosled
    od podizanja — uvek.
    """

    stopped = shell.run("lio_stop.sh")

    if stopped["code"] != status.STATUS_OK:
        return _err(status.STATUS_LIO_ERROR,
                    stopped["stderr"] or "Failed to stop LIO before teardown.")

    if repoint:
        try:
            obj = lio.get_storage_object(name)
            if obj and obj["dev"] != info["origin"]:
                lio.backup_config()
                # Origin IZ STATE-a — jedini pouzdan izvor posle attach-a
                lio.set_device(name, info["origin"])
        except lio.LioError as e:
            return _err(status.STATUS_LIO_ERROR, str(e))

    try:
        engine, _ = _engine()
    except ConfigError as e:
        return _err(status.STATUS_CONFIG_ERROR, str(e))

    if engine.status(info["dm_name"])["code"] == status.STATUS_OK:
        destroyed = engine.destroy(info["dm_name"])
        if destroyed["code"] != status.STATUS_OK:
            return _err(destroyed["code"],
                        destroyed["stderr"] or "dm-cache removal failed.")

    if info.get("cache_type") == "ram":
        shell.run("ram_destroy.sh")

    started = shell.run("lio_start.sh")
    if started["code"] != status.STATUS_OK:
        return _err(status.STATUS_LIO_ERROR,
                    started["stderr"] or "Failed to start LIO.")

    state.unregister(name)
    return _ok(f"'{name}' cleaned up, LIO on origin.")


def _recreate(name, info):
    """
    Sastavi keš iznova posle reboot-a (RAM je prazan, saveconfig već
    pokazuje na mapper). Origin dolazi IZ STATE-a.
    """

    try:
        engine, config = _engine()
    except ConfigError as e:
        return _err(status.STATUS_CONFIG_ERROR, str(e))

    cfg = config["cache"]

    # Očisti eventualnu delimičnu LIO konfiguraciju pre sastavljanja
    shell.run("lio_stop.sh")

    if info.get("cache_type") == "ram":
        ram = shell.run("ram_create.sh",
                        [cfg["cache_ram"] // 1024**2,
                         1 if cfg["ram_prealloc"] else 0])
        if ram["code"] != status.STATUS_OK:
            return _err(ram["code"],
                        ram["stderr"] or "RAM disk creation failed.")
        cache_dev = ram["stdout"]
    else:
        cache_dev = info["cache_device"]

    created = engine.create(info["dm_name"], info["origin"],
                            cache_dev, info["mode"])
    if created["code"] != status.STATUS_OK:
        return _err(created["code"],
                    created["stderr"] or "dm-cache creation failed.")

    started = shell.run("lio_start.sh")
    if started["code"] != status.STATUS_OK:
        return _err(status.STATUS_LIO_ERROR,
                    started["stderr"] or "Failed to start LIO.")

    return _ok(f"'{name}' cache recreated after reboot, LIO up.")


def _engine():
    config = load_config()
    return manager.load(config), config


def _ok(message):
    return {"code": status.STATUS_OK, "message": message}


def _err(code, message):
    return {"code": code, "message": message}
