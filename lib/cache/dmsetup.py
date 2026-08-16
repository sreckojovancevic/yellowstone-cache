#!/usr/bin/env python3

"""
Yellowstone Cache

DMSETUP Cache Engine — adapter između Python aplikacije i shell skripti.
"""

from lib.cache.interface import CacheEngine
from lib import shell


class DmsetupEngine(CacheEngine):

    def create(self, name, origin, cache_device, mode, migration_threshold=None):
        args = [name, origin, cache_device, mode]

        if migration_threshold is not None:
            args.append(migration_threshold)

        return shell.run("create_cache.sh", args)

    def destroy(self, name):
        return shell.run("destroy_cache.sh", [name])

    def enable(self, name):
        return shell.run("attach.sh", [name])

    def disable(self, name):
        return shell.run("detach.sh", [name])

    def status(self, name):
        return shell.run("status.sh", [name])

    def verify(self, device):
        return shell.run("check.sh", [device])


engine = DmsetupEngine()
