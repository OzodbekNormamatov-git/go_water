"""GeocodeService — manzil qidiruv + teskari geocoding (bepul, OSM).

  * search  — Photon (OSM): avtocomplete, struktura (ko'cha/uy/tuman/mahalla)
  * reverse — Nominatim (OSM): x,y -> o'qiladigan manzil matni

Kalit kerak emas. Natijalar O'zbekistonga moyil qilinadi (lat/lon bias +
countrycode filtri). TTL kesh tashqi chaqiruvlarni kamaytiradi. Tashqi xizmat
ishlamasa — bo'sh natija qaytaradi (xarita o'zicha ishlashda davom etadi).
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import List, Optional

import aiohttp

log = logging.getLogger(__name__)

_TIMEOUT = aiohttp.ClientTimeout(total=6)


def _compose(parts: List[Optional[str]]) -> str:
    """Bo'sh va takror qismlarni tashlab, ', ' bilan birlashtiradi."""
    out: List[str] = []
    for p in parts:
        s = (p or "").strip()
        if s and s not in out:
            out.append(s)
    return ", ".join(out)


class GeocodeService:
    def __init__(
        self,
        *,
        search_url: str,
        reverse_url: str,
        user_agent: str,
        bias_lat: Optional[float] = None,
        bias_lon: Optional[float] = None,
        ttl_seconds: int = 600,
    ) -> None:
        self._search_url = search_url
        self._reverse_url = reverse_url
        self._ua = user_agent
        self._bias_lat = bias_lat
        self._bias_lon = bias_lon
        self._ttl = ttl_seconds
        self._cache: dict[str, tuple[float, object]] = {}

    # ---------------------- TTL cache ----------------------

    def _cache_get(self, key: str):
        e = self._cache.get(key)
        if not e:
            return None
        exp, val = e
        if exp < time.monotonic():
            self._cache.pop(key, None)
            return None
        return val

    def _cache_put(self, key: str, val) -> None:
        # Oddiy cheklov — cache cheksiz o'smasin.
        if len(self._cache) > 2000:
            self._cache.clear()
        self._cache[key] = (time.monotonic() + self._ttl, val)

    # ---------------------- Forward search (Photon) ----------------------

    async def search(self, q: str, *, lat: Optional[float] = None,
                     lon: Optional[float] = None, limit: int = 6) -> list[dict]:
        q = (q or "").strip()
        if len(q) < 2:
            return []
        blat = lat if lat is not None else self._bias_lat
        blon = lon if lon is not None else self._bias_lon
        key = f"s:{q.lower()}:{round(blat, 2) if blat else ''}:{round(blon, 2) if blon else ''}"
        cached = self._cache_get(key)
        if cached is not None:
            return cached  # type: ignore[return-value]

        params = {"q": q, "limit": str(limit), "lang": "default"}
        if blat is not None and blon is not None:
            params["lat"] = str(blat)
            params["lon"] = str(blon)
            # Yaqinlikni kuchli ustun qilamiz — bir xil nomli viloyat qishloqlari
            # emas, hudud (Toshkent) ichidagi ko'cha/uy birinchi chiqsin.
            params["location_bias_scale"] = "0.6"
            params["zoom"] = "14"
        data = await self._get_json(self._search_url, params)
        out: list[dict] = []
        for f in (data.get("features") or []) if data else []:
            item = self._norm_photon(f)
            if item:
                out.append(item)
        self._cache_put(key, out)
        return out

    @staticmethod
    def _norm_photon(feature: dict) -> Optional[dict]:
        try:
            coords = feature["geometry"]["coordinates"]  # [lon, lat]
            lon, lat = float(coords[0]), float(coords[1])
        except (KeyError, TypeError, ValueError, IndexError):
            return None
        p = feature.get("properties", {}) or {}
        # O'zbekistondan tashqarini chiqarib tashlaymiz (countrycode bor bo'lsa).
        cc = (p.get("countrycode") or "").upper()
        if cc and cc != "UZ":
            return None
        name = p.get("name")
        street = p.get("street")
        house = p.get("housenumber")
        district = p.get("district") or p.get("county")
        city = p.get("city") or p.get("town") or p.get("state")
        street_line = " ".join(x for x in [street, house] if x)
        title = name or street_line or city or "Manzil"
        subtitle = _compose([district, city]) or (street_line if name else "")
        address = _compose([name or street_line, district, city])
        return {
            "title": title, "subtitle": subtitle, "address": address,
            "latitude": lat, "longitude": lon,
        }

    # ---------------------- Reverse (Nominatim) ----------------------

    async def reverse(self, lat: float, lon: float) -> str:
        try:
            lat = float(lat)
            lon = float(lon)
        except (TypeError, ValueError):
            return ""
        key = f"r:{round(lat, 5)}:{round(lon, 5)}"
        cached = self._cache_get(key)
        if cached is not None:
            return cached  # type: ignore[return-value]
        params = {
            "lat": str(lat), "lon": str(lon), "format": "jsonv2",
            "accept-language": "uz,ru,en", "zoom": "18",
        }
        data = await self._get_json(self._reverse_url, params)
        address = ""
        if data:
            a = data.get("address", {}) or {}
            road = a.get("road") or a.get("pedestrian") or a.get("residential")
            house = a.get("house_number")
            mahalla = a.get("neighbourhood") or a.get("suburb") or a.get("quarter")
            district = a.get("city_district") or a.get("county") or a.get("district")
            city = a.get("city") or a.get("town") or a.get("village")
            road_line = " ".join(x for x in [road, house] if x)
            address = _compose([road_line, mahalla, district, city])
            if not address and data.get("display_name"):
                address = ", ".join(s.strip() for s in data["display_name"].split(",")[:3])
        self._cache_put(key, address)
        return address

    # ---------------------- HTTP ----------------------

    async def _get_json(self, url: str, params: dict) -> Optional[dict]:
        try:
            async with aiohttp.ClientSession(timeout=_TIMEOUT) as s:
                async with s.get(url, params=params, headers={"User-Agent": self._ua}) as r:
                    if r.status != 200:
                        log.warning("Geocode %s -> HTTP %s", url, r.status)
                        return None
                    return await r.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
            log.warning("Geocode so'rov xatosi (%s): %s", url, e)
            return None
