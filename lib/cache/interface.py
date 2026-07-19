#!/usr/bin/env python3

"""
Yellowstone Cache

Cache Engine interfejs.
Svaki engine mora implementirati sve metode.

Metode primaju eksplicitne parametre (name, origin, ...) jer engine
mora znati NAD ČIME radi — raniji interfejs bez argumenata to nije
omogućavao.
"""

from abc import ABC, abstractmethod


class CacheEngine(ABC):

    @abstractmethod
    def create(self, name, origin, cache_device, mode):
        """Kreiraj cache mapiranje iznad origin uređaja."""

    @abstractmethod
    def destroy(self, name):
        """Ukloni cache mapiranje (uz flush dirty blokova)."""

    @abstractmethod
    def enable(self, name):
        """Aktiviraj (resume) postojeći cache."""

    @abstractmethod
    def disable(self, name):
        """Deaktiviraj (flush + suspend) postojeći cache."""

    @abstractmethod
    def status(self, name):
        """Vrati sirovi status cache uređaja."""

    @abstractmethod
    def verify(self, device):
        """Proveri da li je uređaj validan block device."""
