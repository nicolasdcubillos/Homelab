"""Variant/size normalization.

The watcher is deliberately generic: a "variant" is any axis a product varies on
(shoe size, storage capacity, ticket tier...).  For footwear we additionally
normalize the label into a numeric :class:`Size` with a gender, because stores
label the same physical shoe in wildly different ways::

    "9.5"            -> 9.5   (gender inherited from the listing)
    "09.0"           -> 9.0   (Foot Locker zero padding)
    "9.5W"           -> 9.5   womens (Stadium Goods)
    "W 9.5"          -> 9.5   womens
    "M 9 / W 10.5"   -> 9.0   mens (Nike / Foot Locker dual labels)
    "US 10"          -> 10.0
    "10.5Y"          -> None  (kids, must never match a mens watch)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class Gender(str, Enum):
    """Gender axis of a size.

    ``UNISEX`` doubles as "unspecified" and matches any requested gender.
    """

    MENS = "mens"
    WOMENS = "womens"
    UNISEX = "unisex"


_WOMENS_MARKERS = (
    "wmns",
    "women's",
    "womens",
    "women",
    "w's",
    "ws ",
    "feminine",
)
_MENS_MARKERS = ("men's", "mens", " men ", "male")
_KIDS_MARKERS = (
    "toddler",
    "infant",
    "little kid",
    "big kid",
    "grade school",
    "preschool",
    "kids",
    "kid's",
    "youth",
    " gs",
    "(gs)",
    "(ps)",
    "(td)",
)

# "M 9 / W 10.5" or "M9/W10.5" or "9 / W 10.5"
_DUAL_RE = re.compile(
    r"^(?:M\s*)?(?P<mens>\d{1,2}(?:\.\d)?)\s*/\s*W\s*(?P<womens>\d{1,2}(?:\.\d)?)$",
    re.IGNORECASE,
)
# "9.5W", "9.5 W", "W 9.5", "M 9.5", "MENS 9.5", "US 9.5", "US M 9.5"
_SIZE_RE = re.compile(
    r"^(?:US\s*)?"
    r"(?P<pre>M|MEN|MENS|MEN'S|W|WM|WMNS|WOMEN|WOMENS|WOMEN'S)?\s*"
    r"(?P<value>\d{1,2}(?:\.\d)?|\d{1,2}\s?1/2)\s*"
    r"(?P<post>M|MEN|MENS|W|WM|WMNS|WOMENS)?$",
    re.IGNORECASE,
)
_KIDS_SUFFIX_RE = re.compile(r"^\d{1,2}(?:\.\d)?\s*(Y|C|K|GS|PS|TD|BG|BP)$", re.IGNORECASE)
_NON_US_SCALE_RE = re.compile(r"\b(EU|EUR|UK|CM|JP|FR|MX)\b", re.IGNORECASE)


@dataclass(frozen=True, order=True)
class Size:
    """A normalized numeric size."""

    value: float
    gender: Gender = Gender.UNISEX

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        label = f"{self.value:g}"
        if self.gender is Gender.WOMENS:
            return f"W {label}"
        if self.gender is Gender.MENS:
            return f"M {label}"
        return label

    def matches(self, other: Size) -> bool:
        """True when two sizes refer to the same physical item."""
        if abs(self.value - other.value) > 1e-6:
            return False
        return genders_compatible(self.gender, other.gender)


def genders_compatible(a: Gender, b: Gender) -> bool:
    """``UNISEX`` acts as a wildcard; otherwise genders must be equal."""
    return a is Gender.UNISEX or b is Gender.UNISEX or a is b


def normalize_text(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip().lower()


def infer_gender(text: str | None) -> Gender:
    """Infer the gender of a *listing* from its title / colorway text."""
    haystack = f" {normalize_text(text)} "
    for marker in _WOMENS_MARKERS:
        if marker in haystack:
            return Gender.WOMENS
    for marker in _MENS_MARKERS:
        if marker in haystack:
            return Gender.MENS
    return Gender.UNISEX


def is_kids(text: str | None) -> bool:
    haystack = f" {normalize_text(text)} "
    return any(marker in haystack for marker in _KIDS_MARKERS)


def parse_size(label: str | None, default_gender: Gender = Gender.UNISEX) -> Size | None:
    """Parse a store's variant label into a :class:`Size`.

    Returns ``None`` when the label is not a US adult numeric size (kids sizes,
    EU/UK scales, "One Size", colour names, ...).  Callers fall back to plain
    string comparison in that case, which keeps the engine generic.
    """
    if not label:
        return None
    raw = re.sub(r"\s+", " ", str(label)).strip()
    if not raw:
        return None

    # Some stores encode "colour / size" in a compound variant title, e.g.
    # "Orange / 9" or "PINK SMOKE/METALLIC SILVER-MYSTIC DATES / 9.5".  The
    # size is the LAST segment; earlier segments are colour names that would
    # otherwise be misread (or contain their own slashes).
    if "/" in raw and not _DUAL_RE.match(raw):
        segments = [seg.strip() for seg in raw.split("/") if seg.strip()]
        chosen = next((seg for seg in reversed(segments) if _SIZE_RE.match(seg)), None)
        if chosen is None:
            return None
        raw = chosen

    if _NON_US_SCALE_RE.search(raw) and not re.match(r"^US\b", raw, re.IGNORECASE):
        return None
    if _KIDS_SUFFIX_RE.match(raw) or is_kids(raw):
        return None

    dual = _DUAL_RE.match(raw)
    if dual:
        return Size(float(dual.group("mens")), Gender.MENS)

    match = _SIZE_RE.match(raw)
    if not match:
        return None

    value_text = match.group("value").replace(" 1/2", ".5").replace("1/2", ".5")
    try:
        value = float(value_text)
    except ValueError:  # pragma: no cover - guarded by the regex
        return None
    if not 0 < value <= 25:
        return None

    marker = (match.group("pre") or match.group("post") or "").upper()
    if marker.startswith("W"):
        gender = Gender.WOMENS
    elif marker.startswith("M"):
        gender = Gender.MENS
    else:
        gender = default_gender
    return Size(value, gender)


def parse_requested_size(label: str, default_gender: Gender = Gender.UNISEX) -> Size | None:
    """Parse a size the *user* asked for in ``watches.yaml``."""
    return parse_size(label, default_gender)


def variants_match(
    store_label: str,
    requested_label: str,
    *,
    store_gender: Gender = Gender.UNISEX,
    requested_gender: Gender = Gender.UNISEX,
) -> bool:
    """Compare a store variant label against a requested variant label.

    Numeric size comparison first (so ``09.0`` matches ``9``), then a
    normalized string comparison so non-footwear categories work unchanged.
    """
    store_size = parse_size(store_label, store_gender)
    requested_size = parse_requested_size(requested_label, requested_gender)
    if store_size and requested_size:
        return store_size.matches(requested_size)
    if store_size or requested_size:
        # One side is a numeric size and the other is not -> not the same axis
        # value unless the raw strings agree.
        return normalize_text(store_label) == normalize_text(requested_label)
    return normalize_text(store_label) == normalize_text(requested_label)
