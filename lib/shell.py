#!/usr/bin/env python3

"""
Yellowstone Cache

Jedinstveni izvršilac shell skripti.
Nijedan drugi modul ne poziva subprocess direktno.
"""

import subprocess

from lib import paths
from lib import status
from lib import logger


def run(script, args=None):
    """
    Izvrši shell skriptu iz scripts/ direktorijuma.

    Vraća: {"code", "stdout", "stderr"}
    """

    if args is None:
        args = []

    script_path = paths.SCRIPTS / script

    if not script_path.exists():
        logger.error(f"Script not found: {script_path}")
        return {
            "code": status.STATUS_INTERNAL_ERROR,
            "stdout": "",
            "stderr": f"Script not found: {script_path}",
        }

    command = [str(script_path)] + [str(a) for a in args]

    logger.debug(f"Executing: {' '.join(command)}")

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
        )
    except OSError as e:
        logger.error(f"Execution failed: {e}")
        return {
            "code": status.STATUS_INTERNAL_ERROR,
            "stdout": "",
            "stderr": str(e),
        }

    if result.returncode != 0:
        logger.warning(
            f"{script} exited {result.returncode}: {result.stderr.strip()}")

    return {
        "code": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }
