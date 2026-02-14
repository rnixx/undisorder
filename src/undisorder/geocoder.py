"""GPS reverse geocoding (offline and online)."""

from __future__ import annotations

import enum
from functools import lru_cache

import reverse_geocode
from geopy.geocoders import Nominatim


class GeocodingMode(enum.Enum):
    """Geocoding mode."""

    OFF = "off"
    OFFLINE = "offline"
    ONLINE = "online"


class Geocoder:
    """Reverse geocoder with offline (reverse_geocode) and online (Nominatim) backends."""

    def __init__(self, mode: GeocodingMode) -> None:
        self.mode = mode
        self._cache: dict[tuple[float, float], str | None] = {}
        if mode is GeocodingMode.ONLINE:
            self._geolocator = Nominatim(user_agent="undisorder")

    def reverse(self, lat: float, lon: float) -> str | None:
        """Reverse geocode coordinates to a place name.

        Returns a city/town/village name, or country as fallback.
        Returns None if geocoding is off or lookup fails.
        """
        if self.mode is GeocodingMode.OFF:
            return None

        key = (lat, lon)
        if key in self._cache:
            return self._cache[key]

        if self.mode is GeocodingMode.OFFLINE:
            result = self._reverse_offline(lat, lon)
        else:
            result = self._reverse_online(lat, lon)

        self._cache[key] = result
        return result

    def _reverse_offline(self, lat: float, lon: float) -> str | None:
        """Reverse geocode using the offline reverse_geocode library."""
        try:
            results = reverse_geocode.search([(lat, lon)])
            if not results:
                return None
            entry = results[0]
            city = entry.get("city", "")
            country = entry.get("country", "")
            if city:
                return city
            if country:
                return country
            return None
        except Exception:
            return None

    def _reverse_online(self, lat: float, lon: float) -> str | None:
        """Reverse geocode using Nominatim (OSM)."""
        try:
            location = self._geolocator.reverse(f"{lat}, {lon}", language="en")
            if location is None:
                return None
            addr = location.raw.get("address", {})
            for key in ("city", "town", "village", "municipality"):
                if addr.get(key):
                    return addr[key]
            if addr.get("country"):
                return addr["country"]
            return None
        except Exception:
            return None
