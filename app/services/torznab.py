"""
Простой клиент Torznab (используется Jackett, Prowlarr и напрямую трекерами
с Torznab-совместимым API).

Формирует запрос вида:
  {base_url}/api?apikey={key}&t=search&q={query}&cat={categories}

и парсит RSS/XML ответ в список releases.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional
from xml.etree import ElementTree

try:
    import httpx
except ImportError:
    httpx = None

from app.services.rate_limiter import RateLimitExceededError, get_rate_limiter

TORZNAB_NS = {"torznab": "http://torznab.com/schemas/2015/feed"}

_TITLELESS_RELEASE_PREFIX = re.compile(
    r"^(?:s\d|e\d|\d{1,2}x\d|season\s+\d|сезон\s+\d|"
    r"web(?:-?dl|rip)\b|hdtv\b|bd(?:remux|rip)\b|blu-?ray\b|"
    r"(?:720|1080|2160)p\b)",
    re.IGNORECASE,
)


def xml_element_text(element) -> str:
    """Return all text from an RSS element, including nested markup.

    Some Jackett indexers emit highlighted or otherwise nested title fragments.
    ``element.text`` then contains only the prefix (and can be empty), while the
    season/quality suffixes live in child nodes and tails.
    """
    if element is None:
        return ""
    return "".join(element.itertext()).strip()


def torznab_release_title(item, title_element) -> str:
    title = xml_element_text(title_element)
    if title:
        return title
    for attr in item.findall("torznab:attr", TORZNAB_NS):
        if (attr.get("name") or "").lower() in ("title", "releasetitle"):
            value = (attr.get("value") or "").strip()
            if value:
                return value
    return ""


def restore_query_in_release_title(title: str, query: str) -> str:
    """Restore a title omitted by an indexer's Torznab formatter.

    Some Kinozal results contain only the season/episode and quality suffix,
    for example ``S2E1-9 - 2026 WEBRip``.  Prefix only clearly metadata-led
    titles so ordinary releases from other indexers remain untouched.
    """
    clean_title = (title or "").strip()
    clean_query = (query or "").strip()
    if not clean_title or not clean_query:
        return clean_title
    if not _TITLELESS_RELEASE_PREFIX.match(clean_title):
        return clean_title
    return f"{clean_query} {clean_title}"


@dataclass
class TorznabRelease:
    title: str
    guid: Optional[str] = None
    download_url: Optional[str] = None     # прямая ссылка на .torrent для загрузчика
    page_url: Optional[str] = None  # ссылка на страницу темы/раздачи на трекере
    size_bytes: int = 0
    seeders: int = 0
    peers: int = 0
    pub_date: Optional[str] = None
    infohash: Optional[str] = None
    categories: list[int] = None


class TorznabClient:
    def __init__(self, base_url: str, api_key: Optional[str] = None, timeout: int = 30, rate_limit_seconds: float = 2.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.rate_limit_seconds = rate_limit_seconds

    async def search(self, query: str, categories: Optional[list[int]] = None, is_probe: bool = False) -> list[TorznabRelease]:
        params = {"t": "search", "q": query}
        if self.api_key:
            params["apikey"] = self.api_key
        if categories:
            params["cat"] = ",".join(str(c) for c in categories)

        url = f"{self.base_url}/api"
        rate_limiter = get_rate_limiter()
        host = rate_limiter.extract_host(url)

        await rate_limiter.acquire(host, min_interval_seconds=self.rate_limit_seconds, is_probe=is_probe)

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Aliasarr/2.0",
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
        }

        async with httpx.AsyncClient(timeout=self.timeout, headers=headers) as client:
            resp = await client.get(url, params=params)
            if resp.status_code == 429:
                retry_after_hdr = resp.headers.get("Retry-After") or resp.headers.get("retry-after")
                retry_after = rate_limiter.parse_retry_after(retry_after_hdr)
                actual_backoff = rate_limiter.record_429(host, retry_after)
                raise RateLimitExceededError(host, actual_backoff, f"Индексатор '{host}' вернул HTTP 429. Пауза {actual_backoff}с")
            resp.raise_for_status()
            rate_limiter.record_success(host)
            releases = self._parse_response(resp.text)
            for release in releases:
                release.title = restore_query_in_release_title(release.title, query)
            return releases

    def _parse_response(self, xml_text: str) -> list[TorznabRelease]:
        releases: list[TorznabRelease] = []
        try:
            root = ElementTree.fromstring(xml_text)
        except ElementTree.ParseError:
            return releases

        for item in root.iter("item"):
            title_el = item.find("title")
            guid_el = item.find("guid")
            link_el = item.find("link")
            comments_el = item.find("comments")
            if title_el is None:
                continue

            size = 0
            seeders = 0
            peers = 0
            infohash = None
            categories: list[int] = []
            for attr in item.findall("torznab:attr", TORZNAB_NS):
                name = attr.get("name")
                value = attr.get("value")
                if name == "size" and value:
                    size = int(value)
                elif name == "seeders" and value:
                    seeders = int(value)
                elif name == "peers" and value:
                    peers = int(value)
                elif name == "infohash" and value:
                    infohash = value
                elif name == "category" and value:
                    try:
                        categories.append(int(value))
                    except ValueError:
                        pass

            # Ссылка на страницу раздачи на трекере (тег <comments> или guid)
            guid_text = (guid_el.text if guid_el is not None else "") or ""
            comments_text = comments_el.text if comments_el is not None else None
            page_url = comments_text or (guid_text if guid_text.startswith("http") else None)

            title = torznab_release_title(item, title_el)
            if not title:
                continue

            releases.append(
                TorznabRelease(
                    title=title,
                    guid=guid_text or (link_el.text if link_el is not None else ""),
                    download_url=link_el.text if link_el is not None else None,
                    page_url=page_url,
                    size_bytes=size,
                    seeders=seeders,
                    peers=peers,
                    infohash=infohash,
                    categories=categories,
                )
            )
        return releases
