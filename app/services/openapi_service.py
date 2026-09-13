# -*- coding: utf-8 -*-
from __future__ import annotations

import copy
import re
from typing import Any, Optional

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

# In-memory cache for OpenAPI schemas
_CACHED_SCHEMAS: dict[str, dict[str, Any]] = {}

TAGS_METADATA_RU = [
    {
        "name": "shows",
        "description": "Управление библиотекой: фильмы, сериалы, аниме, сезоны, эпизоды, мультиязычные алиасы и правила смещения (+Offset).",
    },
    {
        "name": "settings",
        "description": "Конфигурация системы: корневые папки библиотеки, профили качества, резервные копии, SSL и уведомления.",
    },
    {
        "name": "indexers",
        "description": "Управление торрент-индексаторами, протоколы Torznab/Newznab, профили поиска и интеллектуальный Rate Limiter.",
    },
    {
        "name": "download-clients",
        "description": "Подключение торрент-клиентов (qBittorrent, Transmission, Deluge, rTorrent) и персональные лимиты сидирования.",
    },
    {
        "name": "operations",
        "description": "Фоновые сервисные задачи: полное сканирование диска, автопоиск разыскиваемых серий (WANTED) и очистка мусора.",
    },
    {
        "name": "blocklist",
        "description": "Черный список нежелательных релизов, защита от даунгрейда качества и MediaProbe-проверки файлов.",
    },
    {
        "name": "collections",
        "description": "Саги и коллекции фильмов TMDb: пакетный мониторинг, автоматическое связывание и поиск частей саги.",
    },
    {
        "name": "custom_formats",
        "description": "Кастомные форматы (CF): правила скоринга релизов, ранжирование студий озвучки, видеокодеков и аудиодорожек.",
    },
    {
        "name": "audit",
        "description": "Журнал аудита безопасности: фиксация действий пользователей, изменений конфигурации и авторизаций.",
    },
    {
        "name": "release-logs",
        "description": "История парсинга и захвата релизов: детальные логи решений интеллектуального Decision Engine.",
    },
    {
        "name": "dataset",
        "description": "Импорт и экспорт эталонных наборов данных для валидации алгоритмов парсера названий и студий.",
    },
    {
        "name": "metadata",
        "description": "Внешние провайдеры метаданных: Kinopoisk, TMDb, TheTVDb, AniList, Shikimori и TVMaze.",
    },
    {
        "name": "users",
        "description": "Управление учётными записями, ролевой моделью доступа (RBAC), правами и персональными API-ключами.",
    },
    {
        "name": "auth",
        "description": "Аутентификация пользователей, управление активными сессиями, Cookie и двухфакторная защита (2FA TOTP).",
    },
    {
        "name": "system",
        "description": "Системные метрики, статус служб, перезагрузка сервиса Aliasarr, просмотр журналов логов и управление SSL.",
    },
]

TAGS_METADATA_EN = [
    {
        "name": "shows",
        "description": "Library management: movies, series, anime, seasons, episodes, multi-language aliases, and episode offset rules.",
    },
    {
        "name": "settings",
        "description": "System configuration: root library paths, quality profiles, automated backups, SSL, and notification channels.",
    },
    {
        "name": "indexers",
        "description": "Torrent indexers management, Torznab/Newznab protocols, search categories, and host rate limiting.",
    },
    {
        "name": "download-clients",
        "description": "Download client integration (qBittorrent, Transmission, Deluge, rTorrent) and seeding ratio/time limits.",
    },
    {
        "name": "operations",
        "description": "Background service jobs: disk library scan, WANTED episode auto-search, and debris directory cleanup.",
    },
    {
        "name": "blocklist",
        "description": "Release blocklist, quality downgrade protection, and automated MediaProbe stream verification.",
    },
    {
        "name": "collections",
        "description": "TMDb movie sagas and franchises: batch monitoring, automated linking, and missing installment searches.",
    },
    {
        "name": "custom_formats",
        "description": "Custom Formats (CF): release scoring rules, ranking preferred dubbing groups, video codecs, and audio formats.",
    },
    {
        "name": "audit",
        "description": "Security audit logs: tracking administrative changes, authentication events, and user actions.",
    },
    {
        "name": "release-logs",
        "description": "Release grab and parsing history: granular trace logs of Decision Engine candidate evaluations.",
    },
    {
        "name": "dataset",
        "description": "Import and export benchmark datasets for validating title parser expressions and dubbing rules.",
    },
    {
        "name": "metadata",
        "description": "External metadata providers: Kinopoisk, TMDb, TheTVDb, AniList, Shikimori, and TVMaze.",
    },
    {
        "name": "users",
        "description": "User accounts, role-based access control (RBAC), granular permissions, and personal API keys.",
    },
    {
        "name": "auth",
        "description": "User authentication, session tokens, secure cookies, and two-factor authentication (2FA TOTP).",
    },
    {
        "name": "system",
        "description": "System health metrics, service status, Aliasarr restart trigger, live logs viewer, and SSL management.",
    },
]

DESCRIPTION_RU = """
# Aliasarr REST API — Интерактивный справочник

Добро пожаловать в официальную документацию REST API системы **Aliasarr** (версия 2.9.0).

API предоставляет полный программный доступ ко всем функциям системы: управлению медиатекой, мониторингу торрент-клиентов, настройке индексаторов, планировщику автоматического поиска и проверке качества релизов.

---

### Аутентификация

Для выполнения запросов к защищенным эндпоинтам поддерживаются два способа:
1. **API-ключ (Header или Query)**:
   - Заголовок: `X-Api-Key: <ВАШ_API_КЛЮЧ>`
   - Параметр URL: `?apikey=<ВАШ_API_КЛЮЧ>`
2. **Сессионный Cookie**:
   - Cookie `aliasarr_session`, устанавливаемый автоматически при входе через веб-интерфейс или эндпоинт `/api/v1/auth/login`.

---

### Формат ответов и коды состояния
- `200 OK` / `201 Created` — успешное выполнение запроса.
- `400 Bad Request` — ошибка валидации переданных параметров.
- `401 Unauthorized` — не передан или недействителен API-ключ / сессия.
- `403 Forbidden` — у пользователя недостаточно прав (RBAC) для выполнения операции.
- `404 Not Found` — запрашиваемый ресурс (тайтл, серия, индексатор) не найден.
- `409 Conflict` — конфликт состояния (например, дубликат тайтла в библиотеке).
- `429 Too Many Requests` — превышение лимита запросов (Rate Limiter).
"""

DESCRIPTION_EN = """
# Aliasarr REST API — Interactive Reference

Welcome to the official REST API documentation for **Aliasarr** (version 2.9.0).

The API grants complete programmatic control over every system capability: media library indexing, download client lifecycle, indexer proxies, scheduled WANTED auto-search, and release quality verification.

---

### Authentication

Two authentication methods are supported for secure endpoints:
1. **API Key (Header or Query)**:
   - Header: `X-Api-Key: <YOUR_API_KEY>`
   - Query parameter: `?apikey=<YOUR_API_KEY>`
2. **Session Cookie**:
   - The `aliasarr_session` cookie created automatically upon login via the web UI or the `/api/v1/auth/login` endpoint.

---

### Response Codes & Formats
- `200 OK` / `201 Created` — Request completed successfully.
- `400 Bad Request` — Payload or parameter validation error.
- `401 Unauthorized` — Missing or invalid API key / session token.
- `403 Forbidden` — Insufficient role permissions (RBAC) to execute this operation.
- `404 Not Found` — Requested entity (show, episode, indexer) was not found.
- `409 Conflict` — State conflict (e.g. show already exists in the library).
- `429 Too Many Requests` — Rate limit exceeded.
"""

# Explicit overrides for common endpoint summaries: (path, method) -> (ru_summary, en_summary)
ENDPOINT_SUMMARIES: dict[tuple[str, str], tuple[str, str]] = {
    # Shows & Episodes
    ("/api/v1/shows", "GET"): ("Получить список всех тайтлов медиатеки", "List all library shows"),
    ("/api/v1/shows", "POST"): ("Добавить новый тайтл в медиатеку", "Add new show to library"),
    ("/api/v1/shows/{show_id}", "GET"): ("Получить подробные данные тайтла по ID", "Get show details by ID"),
    ("/api/v1/shows/{show_id}", "PUT"): ("Обновить метаданные и настройки тайтла", "Update show metadata and settings"),
    ("/api/v1/shows/{show_id}", "DELETE"): ("Удалить тайтл из медиатеки", "Delete show from library"),
    ("/api/v1/shows/{show_id}/aliases", "POST"): ("Добавить поисковый алиас к тайтлу", "Add search alias to show"),
    ("/api/v1/shows/{show_id}/aliases/{alias_id}", "DELETE"): ("Удалить поисковый алиас", "Delete search alias"),
    ("/api/v1/shows/{show_id}/search", "POST"): ("Запустить поиск релизов для тайтла", "Search releases for show"),
    ("/api/v1/shows/{show_id}/episodes", "GET"): ("Получить список эпизодов тайтла", "List show episodes"),
    ("/api/v1/shows/{show_id}/episodes/{episode_id}", "PUT"): ("Обновить статус и параметры эпизода", "Update episode status"),
    ("/api/v1/shows/{show_id}/refresh-metadata", "POST"): ("Обновить метаданные тайтла из базы", "Refresh show metadata"),

    # Settings
    ("/api/v1/settings", "GET"): ("Получить текущие конфигурационные настройки", "Get system configuration settings"),
    ("/api/v1/settings", "PUT"): ("Сохранить конфигурационные настройки системы", "Save system configuration settings"),
    ("/api/v1/settings/quality-profiles", "GET"): ("Список настроенных профилей качества", "List configured quality profiles"),
    ("/api/v1/settings/quality-profiles", "POST"): ("Создать новый профиль качества", "Create new quality profile"),
    ("/api/v1/settings/backup/create", "POST"): ("Создать резервную копию системы (ZIP)", "Create system backup archive (ZIP)"),
    ("/api/v1/settings/backup/list", "GET"): ("Список доступных резервных копий", "List available system backups"),

    # Indexers
    ("/api/v1/indexers", "GET"): ("Список настроенных торрент-индексаторов", "List configured torrent indexers"),
    ("/api/v1/indexers", "POST"): ("Добавить новый торрент-индексатор", "Add new torrent indexer"),
    ("/api/v1/indexers/{indexer_id}", "GET"): ("Получить параметры индексатора по ID", "Get indexer details by ID"),
    ("/api/v1/indexers/{indexer_id}", "PUT"): ("Обновить параметры торрент-индексатора", "Update torrent indexer settings"),
    ("/api/v1/indexers/{indexer_id}", "DELETE"): ("Удалить торрент-индексатор", "Delete torrent indexer"),
    ("/api/v1/indexers/{indexer_id}/test", "POST"): ("Проверить связь с торрент-индексатором", "Test indexer connection"),

    # Download Clients
    ("/api/v1/download-clients", "GET"): ("Список подключенных торрент-клиентов", "List connected download clients"),
    ("/api/v1/download-clients", "POST"): ("Подключить новый торрент-клиент", "Connect new download client"),
    ("/api/v1/download-clients/{client_id}", "GET"): ("Параметры торрент-клиента по ID", "Get download client by ID"),
    ("/api/v1/download-clients/{client_id}", "PUT"): ("Обновить параметры торрент-клиента", "Update download client settings"),
    ("/api/v1/download-clients/{client_id}", "DELETE"): ("Отключить торрент-клиент", "Remove download client"),
    ("/api/v1/download-clients/{client_id}/test", "POST"): ("Проверить соединение с клиентом", "Test download client connection"),

    # Operations
    ("/api/v1/operations/scan", "POST"): ("Запустить полное сканирование диска", "Trigger full disk library scan"),
    ("/api/v1/operations/search-wanted", "POST"): ("Запустить автопоиск недостающих серий", "Trigger search for wanted episodes"),
    ("/api/v1/operations/cleanup-debris", "POST"): ("Очистить остаточные файлы и папки", "Clean up debris files and directories"),
    ("/api/v1/operations/tasks", "GET"): ("Список и статус активных фоновых задач", "List status of active background tasks"),

    # Blocklist
    ("/api/v1/blocklist", "GET"): ("Список заблокированных релизов и инфохэшей", "List blocklisted releases and infohashes"),
    ("/api/v1/blocklist", "POST"): ("Добавить раздачу в черный список вручную", "Add release to blocklist manually"),
    ("/api/v1/blocklist/clear-all", "DELETE"): ("Полностью очистить черный список", "Clear entire blocklist"),

    # Collections
    ("/api/v1/collections", "GET"): ("Список коллекций и саг фильмов TMDb", "List TMDb movie collections and sagas"),
    ("/api/v1/collections/{collection_id}", "GET"): ("Детальная карточка коллекции фильмов", "Get movie collection details"),
    ("/api/v1/collections/refresh-all", "POST"): ("Синхронизировать все коллекции с TMDb", "Sync all collections with TMDb"),

    # Custom Formats
    ("/api/v1/custom-formats", "GET"): ("Список кастомных форматов ранжирования", "List custom formats for release scoring"),
    ("/api/v1/custom-formats", "POST"): ("Создать новый кастомный формат", "Create new custom format"),

    # Audit & Release Logs
    ("/api/v1/audit", "GET"): ("Получить журнал аудита действий", "Get security audit logs"),
    ("/api/v1/audit/clear", "POST"): ("Очистить журнал аудита", "Clear security audit logs"),
    ("/api/v1/release-logs", "GET"): ("История решений парсера по релизам", "Get release grab and decision logs"),

    # Auth & Users
    ("/api/v1/auth/status", "GET"): ("Проверить статус текущей сессии", "Check current session status"),
    ("/api/v1/auth/login", "POST"): ("Авторизация по логину и паролю", "Login with username and password"),
    ("/api/v1/auth/logout", "POST"): ("Завершить сессию пользователя", "Logout current user session"),
    ("/api/v1/auth/me", "GET"): ("Данные текущего авторизованного пользователя", "Get current user profile"),
    ("/api/v1/auth/my-api-key", "GET"): ("Получить персональный API-ключ", "Get personal API key"),
    ("/api/v1/auth/regenerate-my-api-key", "POST"): ("Перевыпустить персональный API-ключ", "Regenerate personal API key"),
    ("/api/v1/users", "GET"): ("Список пользователей системы", "List system user accounts"),
    ("/api/v1/users", "POST"): ("Создать нового пользователя", "Create new user account"),

    # System
    ("/api/v1/system/status", "GET"): ("Диагностика состояния служб системы", "System and service health status"),
    ("/api/v1/system/restart", "POST"): ("Перезапустить сервис Aliasarr", "Restart Aliasarr service"),
    ("/api/v1/system/logs", "GET"): ("Получить последние системные логи", "Get recent application logs"),
}


def _humanize_func_name(func_name: str, lang: str) -> str:
    """Fallback generator for summaries based on function name."""
    clean = re.sub(r"^([a-z]+)_route$", r"\1", func_name)
    parts = clean.split("_")
    verb = parts[0] if parts else ""
    rest = " ".join(parts[1:]) if len(parts) > 1 else ""

    verbs_ru = {
        "list": "Список",
        "get": "Получить",
        "create": "Создать",
        "add": "Добавить",
        "update": "Обновить",
        "delete": "Удалить",
        "remove": "Удалить",
        "clear": "Очистить",
        "refresh": "Обновить",
        "search": "Поиск",
        "test": "Проверить",
        "scan": "Сканировать",
        "download": "Скачать",
        "export": "Экспортировать",
        "import": "Импортировать",
        "trigger": "Запустить",
        "check": "Проверить",
        "setup": "Настроить",
        "confirm": "Подтвердить",
        "disable": "Отключить",
    }

    if lang == "en":
        return " ".join(word.capitalize() for word in parts)
    else:
        ru_verb = verbs_ru.get(verb, verb.capitalize())
        return f"{ru_verb} {rest}".strip()


def get_localized_openapi(app: FastAPI, lang: str = "ru") -> dict[str, Any]:
    """Generates and returns a fully localized OpenAPI 3.1 schema for the requested language."""
    target_lang = "en" if str(lang).lower().startswith("en") else "ru"

    if target_lang in _CACHED_SCHEMAS:
        return copy.deepcopy(_CACHED_SCHEMAS[target_lang])

    title = "Aliasarr — Справочник API" if target_lang == "ru" else "Aliasarr — API Documentation"
    description = DESCRIPTION_RU if target_lang == "ru" else DESCRIPTION_EN
    tags_metadata = TAGS_METADATA_RU if target_lang == "ru" else TAGS_METADATA_EN

    # Generate base schema via FastAPI get_openapi
    schema = get_openapi(
        title=title,
        version="2.9.0",
        description=description,
        routes=app.routes,
        tags=tags_metadata,
    )

    # Localize security schemes
    schema["components"] = schema.get("components", {})
    if target_lang == "ru":
        api_key_desc = "Системный или персональный API-ключ Aliasarr (в заголовке X-Api-Key или параметре ?apikey=)"
        cookie_desc = "Сессионный Cookie (aliasarr_session), устанавливаемый после успешного входа в систему"
    else:
        api_key_desc = "System or personal Aliasarr API key (via X-Api-Key header or ?apikey= query param)"
        cookie_desc = "Session Cookie (aliasarr_session) issued after successful authentication"

    schema["components"]["securitySchemes"] = {
        "ApiKeyAuth": {
            "type": "apiKey",
            "in": "header",
            "name": "X-Api-Key",
            "description": api_key_desc,
        },
        "CookieAuth": {
            "type": "apiKey",
            "in": "cookie",
            "name": "aliasarr_session",
            "description": cookie_desc,
        },
    }
    schema["security"] = [{"ApiKeyAuth": []}, {"CookieAuth": []}]

    # Enhance and localize path operation summaries
    paths = schema.get("paths", {})
    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method.lower() not in ("get", "post", "put", "delete", "patch"):
                continue
            if not isinstance(operation, dict):
                continue

            method_upper = method.upper()
            lookup_key = (path, method_upper)

            # 1. Exact match in explicit dictionary
            if lookup_key in ENDPOINT_SUMMARIES:
                ru_summary, en_summary = ENDPOINT_SUMMARIES[lookup_key]
                operation["summary"] = ru_summary if target_lang == "ru" else en_summary
            else:
                # 2. Derive from operation_id or existing summary
                op_id = operation.get("operation_id", "")
                existing_summary = operation.get("summary", "")
                if existing_summary and not target_lang == "ru":
                    # English can keep the existing summary if present
                    pass
                elif op_id:
                    operation["summary"] = _humanize_func_name(op_id, target_lang)

            # Localize common responses
            responses = operation.get("responses", {})
            if isinstance(responses, dict):
                for code, resp in responses.items():
                    if not isinstance(resp, dict):
                        continue
                    if code == "200" and target_lang == "ru":
                        resp["description"] = "Успешный ответ"
                    elif code == "201" and target_lang == "ru":
                        resp["description"] = "Успешно создано"
                    elif code == "400" and target_lang == "ru":
                        resp["description"] = "Ошибка валидации параметров"
                    elif code == "401" and target_lang == "ru":
                        resp["description"] = "Требуется авторизация (неверный API-ключ или сессия)"
                    elif code == "403" and target_lang == "ru":
                        resp["description"] = "Доступ запрещен (недостаточно прав RBAC)"
                    elif code == "404" and target_lang == "ru":
                        resp["description"] = "Ресурс не найден"
                    elif code == "422" and target_lang == "ru":
                        resp["description"] = "Некорректные данные запроса (Unprocessable Entity)"

    _CACHED_SCHEMAS[target_lang] = schema
    return copy.deepcopy(schema)


def clear_openapi_cache() -> None:
    """Clears the cached schemas when routes or settings change."""
    _CACHED_SCHEMAS.clear()
