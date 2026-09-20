"""Protocol adapters for normalizing Torznab and Newznab RSS items.

The rest of Aliasarr consumes :class:`~app.services.torznab.TorznabRelease`
objects regardless of the indexer protocol.  This module keeps the XML quirks
at that boundary: namespace aliases, nested title markup, enclosure fallbacks,
and malformed numeric attributes are handled once instead of in each client.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Callable, Literal, Optional
from xml.etree import ElementTree


ProtocolName = Literal["torznab", "newznab"]

_METADATA_LED_TITLE = re.compile(
    r"^(?:s\d|e\d|\d{1,2}x\d|season\s+\d|сезон\s+\d|"
    r"web(?:-?dl|rip)\b|hdtv\b|bd(?:remux|rip)\b|blu-?ray\b|"
    r"(?:720|1080|2160)p\b)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class AdapterWarning:
    """A non-fatal normalization problem tied to a feed item or attribute."""

    code: str
    message: str
    item_index: Optional[int] = None
    field: Optional[str] = None
    value: Optional[str] = None

    def as_dict(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in {
                "code": self.code,
                "message": self.message,
                "item_index": self.item_index,
                "field": self.field,
                "value": self.value,
            }.items()
            if value is not None
        }


@dataclass
class AdapterResult:
    releases: list[Any] = field(default_factory=list)
    warnings: list[AdapterWarning] = field(default_factory=list)
    item_count: int = 0


def element_text(element: Any) -> str:
    """Return the complete text of an element, including nested markup."""

    if element is None:
        return ""
    return "".join(element.itertext()).strip()


def normalize_release_title(title: str, query: str = "") -> str:
    """Normalize a title without any tracker-name-specific assumptions.

    Some protocol bridges return only an episode/quality suffix.  If the title
    is clearly metadata-led, the requested search term supplies the omitted
    subject.  Complete titles pass through unchanged.
    """

    clean_title = (title or "").strip()
    clean_query = (query or "").strip()
    if clean_title and clean_query and _METADATA_LED_TITLE.match(clean_title):
        return f"{clean_query} {clean_title}"
    return clean_title


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _first_text(item: ElementTree.Element, names: tuple[str, ...]) -> str:
    wanted = {name.lower() for name in names}
    for child in item:
        if _local_name(child.tag) in wanted:
            text = element_text(child)
            if text:
                return text
    return ""


def _attribute_map(item: ElementTree.Element) -> dict[str, list[str]]:
    values: dict[str, list[str]] = {}
    for child in item:
        if _local_name(child.tag) != "attr":
            continue
        name = (child.get("name") or "").strip().lower()
        value = (child.get("value") or element_text(child)).strip()
        if name and value:
            values.setdefault(name, []).append(value)
    return values


def _first_attr(attributes: dict[str, list[str]], names: tuple[str, ...]) -> str:
    for name in names:
        values = attributes.get(name)
        if values:
            return values[0]
    return ""


def _integer(
    raw: str,
    *,
    field_name: str,
    item_index: int,
    warnings: list[AdapterWarning],
) -> int:
    if not raw:
        return 0
    try:
        return max(0, int(float(raw.replace(",", "").strip())))
    except (TypeError, ValueError):
        warnings.append(
            AdapterWarning(
                code="invalid_numeric_attribute",
                message=f"Attribute '{field_name}' is not a valid number",
                item_index=item_index,
                field=field_name,
                value=raw,
            )
        )
        return 0


def _categories(
    item: ElementTree.Element,
    attributes: dict[str, list[str]],
    *,
    item_index: int,
    warnings: list[AdapterWarning],
) -> list[int]:
    raw_values = list(attributes.get("category", [])) + list(
        attributes.get("cat", [])
    )
    for child in item:
        if _local_name(child.tag) == "category":
            value = element_text(child)
            if value:
                raw_values.append(value)

    result: list[int] = []
    for raw in raw_values:
        for part in raw.split(","):
            value = _integer(
                part,
                field_name="category",
                item_index=item_index,
                warnings=warnings,
            )
            if value and value not in result:
                result.append(value)
    return result


def parse_xml_releases(
    xml_text: str,
    *,
    protocol: ProtocolName,
    release_factory: Callable[..., Any],
) -> AdapterResult:
    """Normalize a Torznab/Newznab feed into the common release shape.

    ``release_factory`` is injected to keep the adapter independent from the
    concrete model and to make fixture-level tests inexpensive.
    """

    result = AdapterResult()
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError as exc:
        result.warnings.append(
            AdapterWarning(code="invalid_xml", message=f"Invalid XML: {exc}")
        )
        return result

    items = [element for element in root.iter() if _local_name(element.tag) == "item"]
    result.item_count = len(items)

    for item_index, item in enumerate(items):
        attributes = _attribute_map(item)
        title = _first_text(item, ("title",)) or _first_attr(
            attributes, ("releasetitle", "title")
        )
        if not title:
            result.warnings.append(
                AdapterWarning(
                    code="missing_title",
                    message="Feed item has no usable release title",
                    item_index=item_index,
                    field="title",
                )
            )
            continue

        guid = _first_text(item, ("guid", "id"))
        link = _first_text(item, ("link",))
        comments = _first_text(item, ("comments",))
        pub_date = _first_text(item, ("pubdate", "published", "updated")) or None
        enclosure = next(
            (child for child in item if _local_name(child.tag) == "enclosure"), None
        )
        enclosure_url = enclosure.get("url") if enclosure is not None else None
        enclosure_size = enclosure.get("length") if enclosure is not None else ""

        size_raw = _first_attr(attributes, ("size", "filesize")) or enclosure_size
        seeders_raw = _first_attr(
            attributes, ("seeders", "seed", "seed_count", "seedcount")
        )
        peers_raw = _first_attr(
            attributes, ("peers", "leechers", "leeches", "peer_count")
        )
        default_seeders = 100 if protocol == "newznab" else 0
        seeders = (
            _integer(
                seeders_raw,
                field_name="seeders",
                item_index=item_index,
                warnings=result.warnings,
            )
            if seeders_raw
            else default_seeders
        )
        download_url = link or enclosure_url
        page_url = comments or (guid if guid.startswith(("http://", "https://")) else None)

        result.releases.append(
            release_factory(
                title=title,
                guid=guid or download_url or "",
                download_url=download_url,
                page_url=page_url,
                size_bytes=_integer(
                    size_raw,
                    field_name="size",
                    item_index=item_index,
                    warnings=result.warnings,
                ),
                seeders=seeders,
                peers=_integer(
                    peers_raw,
                    field_name="peers",
                    item_index=item_index,
                    warnings=result.warnings,
                ),
                pub_date=pub_date,
                infohash=_first_attr(attributes, ("infohash", "info_hash")) or None,
                categories=_categories(
                    item,
                    attributes,
                    item_index=item_index,
                    warnings=result.warnings,
                ),
            )
        )

    return result
