"""Сервис генерации внешних ссылок на тайтлы и формирования текста уведомлений."""

from __future__ import annotations

import html
import logging
import re
import urllib.parse
from typing import Optional, Tuple, Any

logger = logging.getLogger("aliasarr.show_links")

PROVIDER_DISPLAY_NAMES = {
    "tmdb": "TMDB",
    "imdb": "IMDb",
    "kinopoisk": "Кинопоиск",
    "trakt": "Trakt",
    "letterboxd": "Letterboxd",
    "mdblist": "MDBList",
    "moviechat": "MovieChat",
    "bluray": "Blu-ray",
    "tvdb": "The TVDB",
    "tvmaze": "TV Maze",
    "shikimori": "Shikimori",
    "anidb": "AniDB",
    "mal": "MyAnimeList",
    "anilist": "AniList",
    "kitsu": "Kitsu",
    "trailer": "Трейлер",
}


def _extract_ids_and_meta(show: Any) -> dict[str, Any]:
    """Извлекает и нормализует идентификаторы тайтла, включая резервный парсинг из metadata_id."""
    meta_src = str(getattr(show, "metadata_source", "") or "").lower()
    meta_id = str(getattr(show, "metadata_id", "") or "").strip()

    tmdb_id = getattr(show, "tmdb_id", None)
    if not tmdb_id and meta_id:
        if "tmdb" in meta_src or "radarr" in meta_src:
            clean = re.sub(r"^(tv|movie|tmdb):", "", meta_id).strip()
            if clean.isdigit():
                tmdb_id = int(clean)

    tvdb_id = getattr(show, "tvdb_id", None)
    if not tvdb_id and meta_id:
        if any(k in meta_src for k in ("tvdb", "skyhook", "sonarr")):
            clean = re.sub(r"^(tvdb|series|sonarr):", "", meta_id).strip()
            if clean.isdigit():
                tvdb_id = int(clean)

    tvmaze_id = getattr(show, "tvmaze_id", None)
    if not tvmaze_id and meta_id and "tvmaze" in meta_src:
        clean = re.sub(r"^tv:", "", meta_id).strip()
        if clean.isdigit():
            tvmaze_id = int(clean)

    imdb_id = getattr(show, "imdb_id", None)
    if not imdb_id and meta_id.startswith("tt"):
        imdb_id = meta_id

    return {
        "tmdb_id": tmdb_id,
        "tvdb_id": tvdb_id,
        "tvmaze_id": tvmaze_id,
        "imdb_id": imdb_id,
        "mal_id": getattr(show, "mal_id", None),
        "anilist_id": getattr(show, "anilist_id", None),
        "anidb_id": getattr(show, "anidb_id", None),
        "shikimori_id": getattr(show, "shikimori_id", None),
        "trailer_url": getattr(show, "trailer_url", None),
    }


def resolve_show_external_link(show: Any, source: str) -> Tuple[Optional[str], str]:
    """Возвращает (url, display_name) для указанного тайтла и выбранного источника.
    Если источник 'none' или ссылка не может быть построена, возвращает (None, '').
    """
    if not show or not source or source == "none":
        return None, ""

    src = source.strip().lower()
    title = str(getattr(show, "title", "") or "").strip()
    year = getattr(show, "year", None)
    content_type = str(getattr(show, "content_type", "") or "series").strip().lower()

    q_title = urllib.parse.quote(title)
    ids = _extract_ids_and_meta(show)
    tmdb_id = ids["tmdb_id"]
    tvdb_id = ids["tvdb_id"]
    tvmaze_id = ids["tvmaze_id"]
    imdb_id = ids["imdb_id"]
    mal_id = ids["mal_id"]
    anilist_id = ids["anilist_id"]
    anidb_id = ids["anidb_id"]
    shikimori_id = ids["shikimori_id"]
    trailer_url = ids["trailer_url"]

    display_name = PROVIDER_DISPLAY_NAMES.get(src, src.upper())
    url: Optional[str] = None

    if content_type == "movie":
        if src == "tmdb":
            url = f"https://www.themoviedb.org/movie/{tmdb_id}" if tmdb_id else f"https://www.themoviedb.org/search/movie?query={q_title}"
        elif src == "trakt":
            if tmdb_id:
                url = f"https://trakt.tv/search/tmdb/{tmdb_id}?id_type=movie"
            elif imdb_id:
                url = f"https://trakt.tv/movies/{imdb_id}"
            else:
                url = f"https://trakt.tv/search/movies?query={q_title}"
        elif src == "letterboxd":
            url = f"https://letterboxd.com/tmdb/{tmdb_id}" if tmdb_id else f"https://letterboxd.com/search/{q_title}/"
        elif src == "imdb":
            url = f"https://imdb.com/title/{imdb_id}/" if imdb_id else f"https://www.imdb.com/find/?q={q_title}&s=tt&ttype=ft"
        elif src == "mdblist":
            target_id = imdb_id or tmdb_id
            url = f"https://mdblist.com/movie/{target_id}" if target_id else f"https://mdblist.com/search/?q={q_title}"
        elif src == "kinopoisk":
            url = f"https://www.kinopoisk.ru/index.php?kp_query={q_title}"
        elif src == "moviechat":
            url = f"https://moviechat.org/{imdb_id}/" if imdb_id else f"https://moviechat.org/search?q={q_title}"
        elif src == "bluray":
            kw = urllib.parse.quote(str(imdb_id)) if imdb_id else q_title
            url = f"https://www.blu-ray.com/search/?quicksearch=1&quicksearch_keyword={kw}&section=theatrical"
        elif src == "trailer":
            yt_query = urllib.parse.quote(f"{title} {year or ''} trailer".strip())
            url = trailer_url or f"https://www.youtube.com/results?search_query={yt_query}"
    elif content_type == "anime":
        if src == "shikimori":
            url = f"https://shikimori.one/animes/{shikimori_id}" if shikimori_id else f"https://shikimori.one/animes?search={q_title}"
        elif src == "anidb":
            url = f"https://anidb.net/anime/{anidb_id}" if anidb_id else f"https://anidb.net/anime/?adb.search={q_title}&do.search=1"
        elif src == "mal":
            url = f"https://myanimelist.net/anime/{mal_id}" if mal_id else f"https://myanimelist.net/anime.php?q={q_title}"
        elif src == "anilist":
            url = f"https://anilist.co/anime/{anilist_id}" if anilist_id else f"https://anilist.co/search/anime?search={q_title}"
        elif src == "kitsu":
            url = f"https://kitsu.app/anime?text={q_title}"
        elif src == "tvdb":
            url = f"https://thetvdb.com/?tab=series&id={tvdb_id}" if tvdb_id else f"https://thetvdb.com/search?query={q_title}"
        elif src == "tmdb":
            url = f"https://www.themoviedb.org/tv/{tmdb_id}" if tmdb_id else f"https://www.themoviedb.org/search/tv?query={q_title}"
        elif src == "imdb":
            url = f"https://imdb.com/title/{imdb_id}/" if imdb_id else f"https://www.imdb.com/find/?q={q_title}&s=tt"
        elif src == "kinopoisk":
            url = f"https://www.kinopoisk.ru/index.php?kp_query={q_title}"
        elif src == "trailer":
            yt_query = urllib.parse.quote(f"{title} anime trailer".strip())
            url = trailer_url or f"https://www.youtube.com/results?search_query={yt_query}"
    else:
        # series
        if src == "tvdb":
            url = f"https://thetvdb.com/?tab=series&id={tvdb_id}" if tvdb_id else f"https://thetvdb.com/search?query={q_title}"
        elif src == "trakt":
            if imdb_id:
                url = f"https://trakt.tv/shows/{imdb_id}"
            elif tmdb_id:
                url = f"https://trakt.tv/search/tmdb/{tmdb_id}?id_type=show"
            else:
                url = f"https://trakt.tv/search/shows?query={q_title}"
        elif src == "tvmaze":
            url = f"https://www.tvmaze.com/shows/{tvmaze_id}/_" if tvmaze_id else f"https://www.tvmaze.com/search?q={q_title}"
        elif src == "imdb":
            url = f"https://imdb.com/title/{imdb_id}/" if imdb_id else f"https://www.imdb.com/find/?q={q_title}&s=tt&ttype=tv"
        elif src == "mdblist":
            target_id = imdb_id or tmdb_id
            url = f"https://mdblist.com/show/{target_id}" if target_id else f"https://mdblist.com/search/?q={q_title}"
        elif src == "tmdb":
            url = f"https://www.themoviedb.org/tv/{tmdb_id}" if tmdb_id else f"https://www.themoviedb.org/search/tv?query={q_title}"
        elif src == "kinopoisk":
            url = f"https://www.kinopoisk.ru/index.php?kp_query={q_title}"
        elif src == "trailer":
            yt_query = urllib.parse.quote(f"{title} {year or ''} trailer".strip())
            url = trailer_url or f"https://www.youtube.com/results?search_query={yt_query}"

    return url, display_name


def build_series_add_notification_message(db: Any, show: Any) -> str:
    """Формирует текст уведомления о добавлении тайтла с внешней ссылкой на основе глобальных настроек."""
    title = str(getattr(show, "title", "") or "Без названия").strip()
    year = getattr(show, "year", None)
    year_str = f" ({year})" if year else ""

    settings = None
    if db is not None:
        try:
            from app.models.db import AppSettings
            settings = db.query(AppSettings).filter(getattr(AppSettings, "id", None) == 1).first()
        except ImportError:
            try:
                settings = db.query(None).filter(None).first()
            except Exception:
                settings = None
        except Exception as exc:
            logger.debug("Не удалось получить AppSettings: %s", exc)

    content_type = str(getattr(show, "content_type", "") or "series").strip().lower()

    if content_type == "movie":
        configured_source = getattr(settings, "notification_link_source_movie", "tmdb") if settings else "tmdb"
    elif content_type == "anime":
        configured_source = getattr(settings, "notification_link_source_anime", "shikimori") if settings else "shikimori"
    else:
        configured_source = getattr(settings, "notification_link_source_series", "tvdb") if settings else "tvdb"

    configured_source = str(configured_source or "").lower().strip()
    if not configured_source or configured_source == "none":
        return f"🎬 В библиотеку добавлен тайтл: {title}{year_str}"

    url, source_label = resolve_show_external_link(show, configured_source)
    if not url:
        return f"🎬 В библиотеку добавлен тайтл: {title}{year_str}"

    escaped_title = html.escape(title)
    return (
        f'🎬 В библиотеку добавлен тайтл: <a href="{url}">{escaped_title}</a>{year_str}\n'
        f"🔗 {source_label}: {url}"
    )
