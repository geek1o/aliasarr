"""Structured diagnostics for Torznab/Newznab-compatible indexers."""

from __future__ import annotations

import inspect
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional
from urllib.parse import urlsplit, urlunsplit
from xml.etree import ElementTree

from app.services.indexer_adapters import parse_xml_releases
from app.services.log_safety import redact_sensitive_data
from app.services.parser import ReleaseKind, parse_episode
from app.services.torznab import TorznabRelease


Fetcher = Callable[..., Awaitable[str] | str]


@dataclass(frozen=True)
class DiagnosticWarning:
    severity: str
    code: str
    message: str
    context: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "context": self.context,
        }


def _indexer_type(indexer: Any) -> str:
    value = getattr(indexer, "type", "torznab")
    return str(getattr(value, "value", value)).lower()


def _api_url(indexer: Any) -> str:
    base_url = str(getattr(indexer, "base_url", "") or "").rstrip("/")
    return base_url if base_url.endswith("/api") else f"{base_url}/api"


def _safe_error(exc: Exception) -> str:
    message = str(exc) or exc.__class__.__name__
    return redact_sensitive_data(message, limit=500)


def _safe_endpoint(url: str) -> str:
    """Return a diagnostic endpoint without query secrets or URL userinfo."""
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    try:
        port = parsed.port
    except ValueError:
        port = None
    netloc = f"{host}:{port}" if port is not None else host
    return urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))


def parse_capabilities(xml_text: str) -> dict[str, Any]:
    """Parse a Torznab/Newznab ``t=caps`` response without fixed prefixes."""

    root = ElementTree.fromstring(xml_text)
    search_types: dict[str, dict[str, Any]] = {}
    categories: list[dict[str, Any]] = []

    searching = next(
        (child for child in root.iter() if child.tag.rsplit("}", 1)[-1].lower() == "searching"),
        None,
    )
    if searching is not None:
        for child in searching:
            name = child.tag.rsplit("}", 1)[-1].lower()
            supported = [
                value.strip()
                for value in (child.get("supportedParams") or "").split(",")
                if value.strip()
            ]
            search_types[name] = {
                "available": (child.get("available") or "yes").lower() in ("yes", "true", "1"),
                "supported_params": supported,
            }

    categories_root = next(
        (child for child in root.iter() if child.tag.rsplit("}", 1)[-1].lower() == "categories"),
        None,
    )
    if categories_root is not None:
        for category in categories_root:
            if category.tag.rsplit("}", 1)[-1].lower() != "category":
                continue
            try:
                category_id = int(category.get("id") or "")
            except ValueError:
                continue
            entry = {
                "id": category_id,
                "name": category.get("name") or str(category_id),
                "subcategories": [],
            }
            for subcategory in category:
                if subcategory.tag.rsplit("}", 1)[-1].lower() != "subcat":
                    continue
                try:
                    subcategory_id = int(subcategory.get("id") or "")
                except ValueError:
                    continue
                entry["subcategories"].append(
                    {
                        "id": subcategory_id,
                        "name": subcategory.get("name") or str(subcategory_id),
                    }
                )
            categories.append(entry)

    return {"search_types": search_types, "categories": categories}


async def _default_capabilities_fetcher(indexer: Any) -> str:
    from app.services.indexer_service import _fetch_text_async

    params: dict[str, Any] = {"t": "caps"}
    api_key = getattr(indexer, "api_key", None)
    if api_key:
        params["apikey"] = api_key
    return await _fetch_text_async(
        _api_url(indexer),
        params=params,
        timeout=int(getattr(indexer, "timeout_seconds", 30) or 30),
        min_interval_seconds=0.0,
        is_probe=True,
    )


async def _call_fetcher(fetcher: Fetcher, indexer: Any) -> str:
    """Support both ``fetcher(indexer)`` and URL/params test adapters."""

    try:
        value = fetcher(indexer)
    except TypeError:
        params = {"t": "caps"}
        api_key = getattr(indexer, "api_key", None)
        if api_key:
            params["apikey"] = api_key
        value = fetcher(_api_url(indexer), params=params)
    if inspect.isawaitable(value):
        value = await value
    return str(value)


def _category_mapping(configured: list[int], capabilities: dict[str, Any]) -> dict[str, Any]:
    advertised: set[int] = set()
    for category in capabilities.get("categories", []):
        advertised.add(int(category["id"]))
        advertised.update(int(item["id"]) for item in category.get("subcategories", []))

    supported: list[int] = []
    unsupported: list[int] = []
    for category_id in configured:
        category_id = int(category_id)
        if category_id in advertised or any(
            parent in advertised for parent in (category_id // 1000 * 1000,)
        ):
            supported.append(category_id)
        else:
            unsupported.append(category_id)
    return {
        "configured": configured,
        "advertised": sorted(advertised),
        "supported": supported,
        "unsupported": unsupported,
    }


def _sample_diagnostics(releases: list[TorznabRelease]) -> tuple[dict[str, Any], list[DiagnosticWarning]]:
    warnings: list[DiagnosticWarning] = []
    unknown_titles: list[str] = []
    missing_download = 0
    missing_categories = 0
    zero_size = 0
    duplicate_guids: list[str] = []
    seen_guids: set[str] = set()

    for release in releases:
        parsed = parse_episode(release.title)
        if parsed.kind == ReleaseKind.UNKNOWN:
            unknown_titles.append(release.title)
        if not release.download_url:
            missing_download += 1
        if not release.categories:
            missing_categories += 1
        if release.size_bytes <= 0:
            zero_size += 1
        if release.guid and release.guid in seen_guids:
            duplicate_guids.append(release.guid)
        if release.guid:
            seen_guids.add(release.guid)

    count = len(releases)
    if not count:
        warnings.append(
            DiagnosticWarning("warning", "empty_sample", "The probe returned no releases")
        )
    if unknown_titles:
        warnings.append(
            DiagnosticWarning(
                "warning",
                "unparsed_release_titles",
                "Some sample titles could not be parsed",
                {"count": len(unknown_titles), "examples": unknown_titles[:3]},
            )
        )
    if missing_download:
        warnings.append(
            DiagnosticWarning(
                "error",
                "missing_download_urls",
                "Some sample releases have no download URL",
                {"count": missing_download},
            )
        )
    if missing_categories:
        warnings.append(
            DiagnosticWarning(
                "warning",
                "missing_release_categories",
                "Some sample releases have no category attributes",
                {"count": missing_categories},
            )
        )
    if duplicate_guids:
        warnings.append(
            DiagnosticWarning(
                "warning",
                "duplicate_release_guids",
                "The sample contains duplicate release identifiers",
                {"count": len(set(duplicate_guids)), "examples": list(dict.fromkeys(duplicate_guids))[:3]},
            )
        )

    return {
        "count": count,
        "parsed_count": count - len(unknown_titles),
        "unparsed_count": len(unknown_titles),
        "missing_download_url_count": missing_download,
        "missing_category_count": missing_categories,
        "zero_size_count": zero_size,
    }, warnings


async def diagnose_indexer(
    indexer: Any,
    *,
    client: Optional[Any] = None,
    fetcher: Optional[Fetcher] = None,
    capabilities_xml: Optional[str] = None,
    sample_xml: Optional[str] = None,
    sample_query: str = "test",
) -> dict[str, Any]:
    """Run connectivity, capabilities, mapping, and sample-parse diagnostics.

    ``client``, ``fetcher``, and both XML arguments are injectable so callers
    can run deterministic diagnostics without network access.
    """

    protocol = _indexer_type(indexer)
    xml_protocol = "newznab" if protocol == "newznab" else "torznab"
    warnings: list[DiagnosticWarning] = []

    capabilities: dict[str, Any] = {"search_types": {}, "categories": []}
    try:
        caps_text = capabilities_xml
        if caps_text is None:
            caps_text = await _call_fetcher(fetcher or _default_capabilities_fetcher, indexer)
        capabilities = parse_capabilities(caps_text)
        capabilities_status = {"ok": True, **capabilities}
    except Exception as exc:
        capabilities_status = {
            "ok": False,
            **capabilities,
            "error": _safe_error(exc),
        }
        warnings.append(
            DiagnosticWarning(
                "warning",
                "capabilities_unavailable",
                "Could not read indexer capabilities",
                {"error": _safe_error(exc)},
            )
        )

    started = time.monotonic()
    releases: list[TorznabRelease] = []
    try:
        if sample_xml is not None:
            adapter_result = parse_xml_releases(
                sample_xml,
                protocol=xml_protocol,
                release_factory=TorznabRelease,
            )
            releases = adapter_result.releases
            warnings.extend(
                DiagnosticWarning("warning", warning.code, warning.message, warning.as_dict())
                for warning in adapter_result.warnings
            )
        else:
            if client is None:
                from app.services.indexer_service import get_indexer_client

                client = get_indexer_client(indexer)
            releases = await client.search(sample_query, is_probe=True)
        connectivity = {
            "ok": True,
            "latency_ms": round((time.monotonic() - started) * 1000, 1),
        }
    except Exception as exc:
        connectivity = {
            "ok": False,
            "latency_ms": round((time.monotonic() - started) * 1000, 1),
            "error": _safe_error(exc),
        }
        warnings.append(
            DiagnosticWarning(
                "error",
                "connectivity_failed",
                "The indexer search probe failed",
                {"error": _safe_error(exc)},
            )
        )

    configured_categories = [
        int(value) for value in (getattr(indexer, "categories", None) or [])
    ]
    mapping = _category_mapping(configured_categories, capabilities)
    if capabilities_status["ok"] and mapping["unsupported"]:
        warnings.append(
            DiagnosticWarning(
                "warning",
                "unsupported_configured_categories",
                "Some configured categories are not advertised by the indexer",
                {"categories": mapping["unsupported"]},
            )
        )

    sample, sample_warnings = _sample_diagnostics(releases)
    warnings.extend(sample_warnings)
    status = "error" if any(item.severity == "error" for item in warnings) else (
        "warning" if warnings else "healthy"
    )

    endpoint = _safe_endpoint(_api_url(indexer))
    return {
        "status": status,
        "indexer": {
            "id": getattr(indexer, "id", None),
            "name": getattr(indexer, "name", None),
            "protocol": protocol,
            "endpoint": endpoint,
        },
        "connectivity": connectivity,
        "capabilities": capabilities_status,
        "category_mapping": mapping,
        "sample": sample,
        "warnings": [warning.as_dict() for warning in warnings],
    }
