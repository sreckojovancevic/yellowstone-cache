#!/usr/bin/env python3

"""
Yellowstone Cache

Jedini modul koji čita i menja LIO konfiguraciju.
Source of Truth: /etc/rtslib-fb-target/saveconfig.json
(bez parsiranja `targetcli ls`)

KLJUČNI PRINCIP (attach/detach):
Backstore se NIKAD ne briše i ne rekreira — menja se ISKLJUČIVO
"dev" polje storage objekta u saveconfig.json dok je LIO zaustavljen.
WWN, LUN brojevi, ACL-ovi i atributi ostaju netaknuti, pa initiator
(ESXi) vidi identičan NAA ID — isti disk, ista putanja, isti datastore.
"""

import json
import os
import shutil
from datetime import datetime

from lib import paths
from lib import status
from lib import logger


def get_config():
    """Učitaj kompletan saveconfig.json."""

    try:
        with open(paths.LIO_SAVECONFIG, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error(f"LIO saveconfig not found: {paths.LIO_SAVECONFIG}")
        raise LioError(f"LIO saveconfig not found: {paths.LIO_SAVECONFIG}")
    except json.JSONDecodeError as e:
        logger.error(f"LIO saveconfig invalid JSON: {e}")
        raise LioError(f"LIO saveconfig is not valid JSON: {e}")


def get_storage_objects():
    """
    Vrati listu block storage objekata:

        [{"name": ..., "dev": ...}, ...]
    """

    config = get_config()

    storage = []

    for obj in config.get("storage_objects", []):

        if obj.get("plugin") != "block":
            continue

        storage.append({
            "name": obj.get("name"),
            "dev": obj.get("dev"),
        })

    return storage


def get_storage_object(name):
    """Vrati ceo storage objekat po imenu, ili None."""

    config = get_config()

    for obj in config.get("storage_objects", []):
        if obj.get("plugin") == "block" and obj.get("name") == name:
            return obj

    return None


def backup_config():
    """
    Sačuvaj kopiju saveconfig.json u state/backups/.
    Vraća putanju backup fajla.
    """

    backups = paths.STATE / "backups"
    backups.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = backups / f"saveconfig-{stamp}.json"

    shutil.copy2(paths.LIO_SAVECONFIG, target)
    logger.info(f"LIO config backed up to {target}")

    return target


def set_device(name, dev):
    """
    Promeni SAMO "dev" polje storage objekta `name`.
    Sve ostalo (wwn, atributi, LUN/ACL struktura) ostaje bajt-za-bajt isto.

    Upis je atomičan (temp fajl + os.replace) — nestanak struje ne može
    ostaviti polu-upisan saveconfig.json.

    Poziva se ISKLJUČIVO dok je LIO zaustavljen.
    Vraća staru vrednost "dev" polja.
    """

    config = get_config()

    found = None

    for obj in config.get("storage_objects", []):
        if obj.get("plugin") == "block" and obj.get("name") == name:
            found = obj
            break

    if found is None:
        raise LioError(f"Storage object '{name}' not found in saveconfig.")

    old_dev = found["dev"]
    found["dev"] = dev

    tmp = str(paths.LIO_SAVECONFIG) + ".yellowstone.tmp"

    with open(tmp, "w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())

    os.replace(tmp, paths.LIO_SAVECONFIG)

    logger.info(f"LIO backstore '{name}': dev {old_dev} -> {dev} (wwn untouched)")

    return old_dev


def restore_backup(backup_path):
    """Vrati saveconfig.json iz backup-a (rollback)."""

    shutil.copy2(backup_path, paths.LIO_SAVECONFIG)
    logger.warning(f"LIO config restored from backup {backup_path}")


class LioError(Exception):
    """Greška LIO konfiguracije. Nosilac je status.STATUS_LIO_ERROR."""

    code = status.STATUS_LIO_ERROR


if __name__ == "__main__":

    for disk in get_storage_objects():
        print(f'{disk["name"]} -> {disk["dev"]}')
