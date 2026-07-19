"""
Yellowstone Cache

Centralizovano logovanje.

FIX: logs/ direktorijum se sada kreira ako ne postoji,
i greška pisanja loga nikad ne obara aplikaciju.
"""

from datetime import datetime

from lib import paths


def write(level, message):

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    line = f"{timestamp} [{level}] {message}\n"

    try:
        paths.LOGS.mkdir(parents=True, exist_ok=True)

        with open(paths.LOG_FILE, "a") as log:
            log.write(line)

    except OSError:
        # Logovanje ne sme da obori aplikaciju.
        pass


def info(message):
    write("INFO", message)


def warning(message):
    write("WARNING", message)


def error(message):
    write("ERROR", message)


def debug(message):
    write("DEBUG", message)
