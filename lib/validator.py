#!/usr/bin/env python3

"""
Yellowstone Cache

Validacija storage objekata.
Vraća strukturirane podatke — ne prikazuje ništa.
"""

from lib import lio
from lib import shell
from lib import status


def validate():

    result = {
        "code": status.STATUS_OK,
        "message": "System ready.",
        "storage": [],
    }

    try:
        objects = lio.get_storage_objects()
    except lio.LioError as e:
        result["code"] = status.STATUS_LIO_ERROR
        result["message"] = str(e)
        return result

    for obj in objects:

        device = obj["dev"]

        check = shell.run("check.sh", [device])

        if check["code"] == status.STATUS_OK:

            result["storage"].append({
                "name": obj["name"],
                "device": device,
                "code": status.STATUS_OK,
                "message": "OK",
            })

        else:

            result["storage"].append({
                "name": obj["name"],
                "device": device,
                "code": check["code"],
                "message": status.message(check["code"]),
            })

            result["code"] = check["code"]
            result["message"] = "Validation failed."

    return result


if __name__ == "__main__":

    from pprint import pprint

    pprint(validate())
