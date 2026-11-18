"""Shared parsing/normalisation for the batdongsan group platform.

Both ``batdongsan.com.vn`` and ``batdongsan365.vn`` run the same listing markup
(``js__card-full-web`` / ``re__card-*``) and the same detail markup
(``property-content`` + label/value rows + ``Thông tin tin đăng``), so the
extraction rules live here and each site artifact only supplies URL patterns.

Nothing in this module drops a record: missing values become ``""`` and are
recorded as ``Chưa xác định`` evidence downstream.
"""

from __future__ import annotations

import re
from html import unescape
from typing import Iterable
from urllib.parse import urljoin

# --------------------------------------------------------------------------
# text helpers
# --------------------------------------------------------------------------

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_SEP = "·"  # the middleware "·" separator used in re__card-config


def strip_html(value: str) -> str:
    if not value:
        return ""
    return _WS_RE.sub(" ", unescape(_TAG_RE.sub(" ", value))).strip()


def _norm_label(text: str) -> str:
    """Vietnamese label as rendered → ascii-ish comparison key.

    The site renders labels with combining diacritics that differ between pages
    ("Mức giá" vs "Mức giá"), so labels are compared accent-free.
    """
    import unicodedata

    text = text.replace("đ", "d").replace("Đ", "D")
    decomposed = unicodedata.normalize("NFD", text)
    return _WS_RE.sub(" ", "".join(c for c in decomposed if not unicodedata.combining(c))).strip().lower()


# --------------------------------------------------------------------------
# listing page
# --------------------------------------------------------------------------

_CARD_SPLIT_RE = re.compile(r'(?=<div[^>]*class="[^"]*js__card-full-web)')
# The title markup varies: sometimes text sits directly in re__card-title,
# sometimes it is nested under <span class="pr-title">. Capture the whole block
# and strip the tags afterwards, never stopping at the first child tag.
_CARD_TITLE_RE = re.compile(
    r'class="[^"]*re__card-title[^"]*"[^>]*>(.*?)</h3>', re.S
)
_CARD_TITLE_FALLBACK_RE = re.compile(
    r'class="[^"]*re__card-title[^"]*"[^>]*>(.*?)</(?:div|span|p)>', re.S
)
# the card root also carries the title in its own title="" attribute
_CARD_LINK_TITLE_RE = re.compile(
    r'<a[^>]+href="(/[^"]+?)"[^>]*title="([^"]+)"', re.S
)
_CARD_INFO_TITLE_RE = re.compile(
    r'<div class="re__card-info"[^>]*title="([^"]*)"', re.S
)
_CARD_HREF_RE = re.compile(r'<a[^>]+href="(/[^"]+?)"[^>]*class="[^"]*(?:pr-title|js__product-link)', re.S)
_CARD_ANY_HREF_RE = re.compile(r'<a[^>]+href="(https?://[^"]+?|[^"?][^"]*?)"', re.S)
_CARD_CONFIG_RE = re.compile(r'class="[^"]*re__card-config-price[^"]*"[^>]*>(.*?)</div>', re.S)
_CARD_PER_M2_RE = re.compile(r'class="[^"]*re__card-config-price_per_m2[^"]*"[^>]*>(.*?)</span>', re.S)
_CARD_AREA_RE = re.compile(r'class="[^"]*re__card-config-area[^"]*"[^>]*>(.*?)</div>', re.S)
_CARD_LOC_RE = re.compile(r'class="[^"]*re__card-location[^"]*"[^>]*>(.*?)</div>', re.S)
_CARD_DESC_RE = re.compile(r'class="[^"]*re__card-description[^"]*"[^>]*>(.*?)</div>', re.S)
_CARD_BROKER_RE = re.compile(r'class="[^"]*re__card-contact[^"]*"[^>]*>(.*?)</div>', re.S)


def _split_config(text: str) -> list[str]:
    return [p.strip() for p in text.split(_SEP) if p.strip()]


def _parse_price(config_parts: Iterable[str]) -> tuple[str, str]:
    """First config part is the price. Returns (raw_text, normalised_vnd)."""
    parts = list(config_parts)
    if not parts:
        return "", ""
    raw = parts[0]
    return raw, normalise_vnd(raw)


_UNIT = {
    "ty": 1_000_000_000,
    "tỷ": 1_000_000_000,
    "ti": 1_000_000_000,
    "tr": 1_000_000,
    "trieu": 1_000_000,
    "nghin": 1_000,
    "ngan": 1_000,
    "k": 1_000,
    "vnd": 1,
}


def normalise_vnd(raw: str) -> str:
    """'10.5 triệu' → 10500000. Returns "" when the text is 'Thoả thuận' etc."""
    if not raw:
        return ""
    low = _norm_label(raw)
    if any(w in low for w in ("thoa thuan", "lien he", "thuong luong")):
        return ""
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*([a-zA-Z]+)?", low)
    if not m:
        return ""
    try:
        num = float(m.group(1).replace(",", "."))
    except ValueError:
        return ""
    unit = (m.group(2) or "").lower()
    mult = next((v for k, v in _UNIT.items() if unit == k or unit.startswith(k)), 1)
    if mult == 1 and num < 1000:  # bare "10.5" with no unit → ambiguous, keep raw only
        return ""
    return str(int(round(num * mult)))


_AREA_RE = re.compile(r"(\d[\d.,]*)\s*m\s*(?:2|²)?", re.I)


def strip_accents(text: str) -> str:
    """Lowercase + Vietnamese diacritics removed — for keyword matching only.

    Matching on precomposed Vietnamese characters with hand-written character
    classes is fragile ('xưởng' vs 'xuong' vs 'xưỏng'); stripping accents once
    makes every pattern plain ASCII. Numbers are unaffected.
    """
    import unicodedata

    text = (text or "").replace("đ", "d").replace("Đ", "D")
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def parse_area_m2(raw: str) -> str:
    """'11.000 m²' → 11000 ; '9000,0 m2' → 9000 ; '1000m' → 1000.

    Vietnamese uses '.' as the thousands separator, so a thousand-grouped number
    must be read as an integer; a single separator with <=2 trailing digits is a
    decimal comma instead.
    """
    if not raw:
        return ""
    m = _AREA_RE.search(raw)
    token = m.group(1) if m else raw.strip()
    token = token.strip()
    if not token:
        return ""
    dots, commas = token.count("."), token.count(",")
    if dots and commas:
        # last separator is the decimal mark
        if token.rfind(",") > token.rfind("."):
            token = token.replace(".", "").replace(",", ".")
        else:
            token = token.replace(",", "")
    elif dots or commas:
        sep = "." if dots else ","
        head, _, tail = token.rpartition(sep)
        if len(tail) == 3 and head:  # thousands grouping: 11.000 / 1.234
            token = token.replace(sep, "")
        elif len(tail) <= 2:
            token = head + "." + tail
        else:
            token = token.replace(sep, "")
    try:
        value = float(token)
    except ValueError:
        return ""
    # never scientific notation: 1.234.567 m² must stay readable and must still
    # compare equal to the digits found in the source text
    if value == int(value):
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def parse_listing_cards(html: str, base: str) -> list[dict]:
    """Extract one row per card. Never filters anything out."""
    rows: list[dict] = []
    for chunk in _CARD_SPLIT_RE.split(html)[1:]:
        # cut the card at the start of the next card / footer to bound the regexes
        title_m = _CARD_TITLE_RE.search(chunk) or _CARD_TITLE_FALLBACK_RE.search(chunk)
        title = strip_html(title_m.group(1)) if title_m else ""
        if not title:
            title_attr = _CARD_INFO_TITLE_RE.search(chunk) or _CARD_LINK_TITLE_RE.search(chunk)
            if title_attr:
                # info-title has one group, link-title has (href, title)
                title = strip_html(title_attr.group(title_attr.lastindex))
        href_m = _CARD_HREF_RE.search(chunk) or _CARD_ANY_HREF_RE.search(chunk)
        config_m = _CARD_CONFIG_RE.search(chunk)
        area_m = _CARD_AREA_RE.search(chunk)
        loc_m = _CARD_LOC_RE.search(chunk)
        desc_m = _CARD_DESC_RE.search(chunk)

        href = href_m.group(1) if href_m else ""
        if href and href.startswith("/"):
            href = base.rstrip("/") + href
        config_raw = strip_html(config_m.group(1)) if config_m else ""
        parts = _split_config(config_raw)
        price_raw, price_vnd = _parse_price(parts)
        per_m2_m = _CARD_PER_M2_RE.search(chunk)
        per_m2_raw = strip_html(per_m2_m.group(1)) if per_m2_m else ""
        area_raw = strip_html(area_m.group(1)) if area_m else (parts[1] if len(parts) > 1 else "")

        # The headline price equals the price-per-m² for listings rented *by m²*
        # (đất/xưởng cho thuê theo diện tích). Keeping it in rent_amount would be
        # wrong by orders of magnitude, so it is separated out.
        price_basis = "total"
        if per_m2_raw:
            pm = normalise_vnd(per_m2_raw)
            if pm and price_vnd and abs(float(pm) - float(price_vnd)) < 1:
                price_basis = "per_m2"
            elif pm:
                price_basis = "total_with_per_m2"
        # A "total" price at or below the per-m² figure (or absurdly small) cannot
        # be a real monthly rent — e.g. '1 nghìn' with '10/m²'. Flag as ambiguous
        # so the value is not exported as a trustworthy total.
        if price_basis == "total" and price_vnd:
            per_m2_num = None
            if per_m2_raw:
                pm_val = normalise_vnd(per_m2_raw)
                per_m2_num = float(pm_val) if pm_val else None
            if (per_m2_num is not None and float(price_vnd) <= per_m2_num) or float(price_vnd) < 100_000:
                price_basis = "ambiguous"

        rows.append(
            {
                "title": title,
                "url": href,
                "price_text": price_raw,
                "price_vnd": price_vnd,
                "price_per_m2_text": per_m2_raw,
                "price_per_m2_vnd": normalise_vnd(per_m2_raw) if per_m2_raw else "",
                "price_basis": price_basis,
                "area_text": area_raw,
                "area_m2": parse_area_m2(area_raw),
                "location": strip_html(loc_m.group(1)) if loc_m else "",
                "description": strip_html(desc_m.group(1))[:2000] if desc_m else "",
                "config_parts": parts,
            }
        )
    return rows


def next_page_urls(html: str, base: str) -> list[str]:
    """All *page* links on a listing page (dedup, absolute).

    Two pagination shapes are in use across the platform:
      batdongsan365.vn      /cho-thue-van-phong/?page=2
      batdongsan.com.vn     /cho-thue-van-phong/p2   (233 pages on 2026-11-17)
    Only the second one appeared on bds.com.vn, so a '?page='-only pattern
    silently limited that site to page 1.
    """
    found = re.findall(
        r'href="([^"]*(?:[?&]page=\d+|/trang-\d+|/p\d+)/?(?:[?#][^"]*)?)"', html, re.I)
    out = []
    for href in found:
        # `?page=1` is relative: resolving it here keeps every returned URL
        # absolute, which the caller needs to key pages/dedup on.
        href = urljoin(base, unescape(href))
        if href not in out:
            out.append(href)
    return out


# --------------------------------------------------------------------------
# detail page
# --------------------------------------------------------------------------

_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S)
_ADDRESS_RE = re.compile(r'<p[^>]*class="[^"]*\bb2\b[^"]*"[^>]*>(.*?)</p>', re.S)
_ROW_START_RE = re.compile(
    r'<div[^>]*class="[^"]*d-flex align-items-center justify-content-between '
    r'border-bottom border-top py-4[^"]*"[^>]*>',
    re.S,
)
_SPAN_VAL_RE = re.compile(r"<span>(.*?)</span>\s*</div>\s*<div>(.*?)</div>", re.S)
# generic label/value pair: last two leaf text blocks of one attribute row
_LEAF_PAIR_RE = re.compile(r"<(span|div)>([^<]{1,80})</\1>", re.S)
_META_PAIR_RE = re.compile(
    r'<div class="space-y-1">\s*<p class="text-gray fw-light">(.*?)</p>\s*<p>(.*?)</p>',
    re.S,
)
_DESCRIPTION_RE = re.compile(r'<h4>\s*Th.{0,4}ng tin m.{0,4} t.{0,4}\s*</h4>(.*?)(?=<h4|</section)', re.S | re.I)
_POST_META_RE = re.compile(r"<h4>\s*Th.{0,4}ng tin tin.{0,6}ng\s*</h4>(.*?)(?=</div>\s*</div>|</section)", re.S | re.I)
_PHONE_RE = re.compile(r"(?:0\d[\d.\s]{7,12}\d)")
_AVATAR_NAME_RE = re.compile(r'<div class="rounded-circle[^"]*">.*?</div>\s*</div>\s*<div class="space-y-1">\s*<p>(.*?)</p>', re.S)

# Label → schema key. Labels are matched accent-free.
DETAIL_LABELS = {
    "muc gia": "price_text",
    "gia thue": "price_text",
    "gia ban": "price_text",
    "dien tich": "area_text",
    "phap ly": "legal",
    "huong": "direction",
    "so phong ngu": "bedrooms",
    "phong ngu": "bedrooms",
    "so phong tam": "bathrooms",
    "phong tam": "bathrooms",
    "so tang": "floors",
    "tang": "floors",
    "loai hinh": "property_type",
    "ma tin": "listing_code",
    "ngay dang": "posted_at",
    "ngay het han": "expires_at",
    "loai tin": "post_type",
    "dien thoai": "contact",
    "lien he": "contact",
}


def _match_label(label: str) -> str:
    key = _norm_label(label)
    for want, dest in DETAIL_LABELS.items():
        if key == want or key.startswith(want) or want.startswith(key):
            return dest
    return ""


def parse_detail(html: str, url: str) -> dict:
    """Extract everything known about one listing. Unknown → ""."""
    out: dict = {
        "title": "",
        "address": "",
        "price_text": "",
        "area_text": "",
        "legal": "",
        "direction": "",
        "bedrooms": "",
        "bathrooms": "",
        "floors": "",
        "property_type": "",
        "listing_code": "",
        "posted_at": "",
        "expires_at": "",
        "post_type": "",
        "contact": "",
        "description": "",
        "attributes": {},
    }
    m = _H1_RE.search(html)
    if m:
        out["title"] = strip_html(m.group(1))
    m = _ADDRESS_RE.search(html)
    if m:
        out["address"] = strip_html(m.group(1))

    # label/value attribute rows — slice from one row marker to the next
    starts = [m.end() for m in _ROW_START_RE.finditer(html)]
    ends = [m.start() for m in _ROW_START_RE.finditer(html)][1:] + [len(html)]
    for start, end in zip(starts, ends):
        body = html[start:end]
        pair = _SPAN_VAL_RE.search(body)
        if pair:
            label, value = strip_html(pair.group(1)), strip_html(pair.group(2))
        else:
            # fallback: drop icons, then take the first and last leaf text nodes
            clean = re.sub(r"<svg.*?</svg>", "", body, flags=re.S)
            leaves = [strip_html(m.group(2)) for m in _LEAF_PAIR_RE.finditer(clean)]
            leaves = [t for t in leaves if t]
            if len(leaves) < 2:
                continue
            label, value = leaves[0], leaves[-1]
        if not label or not value:
            continue
        out["attributes"][label] = value
        dest = _match_label(label)
        if dest and not out.get(dest):
            out[dest] = value

    # posting metadata grid (Ngày đăng / Ngày hết hạn / Loại tin / Mã tin)
    for m in _META_PAIR_RE.finditer(html):
        label, value = strip_html(m.group(1)), strip_html(m.group(2))
        if not label or not value:
            continue
        out["attributes"].setdefault(label, value)
        dest = _match_label(label)
        if dest and not out.get(dest):
            out[dest] = value

    m = _DESCRIPTION_RE.search(html)
    if m:
        out["description"] = strip_html(m.group(1))[:8000]

    m = _AVATAR_NAME_RE.search(html)
    if m:
        out["attributes"].setdefault("Người đăng", strip_html(m.group(1)))

    phones = _PHONE_RE.findall(out["description"]) if out["description"] else []
    if not phones:
        # sidebar shows '******9528 Hiện số' — keep the masked form as evidence
        for m in re.finditer(r'\*{4,}\d{3,4}', html):
            phones.append(m.group(0))
            break
    if phones:
        out["contact"] = phones[0].replace(" ", "")

    out["url"] = url
    return out


def location_parts(address: str) -> dict:
    """'Xã Hạ Bằng, Huyện Thạch Thất, Thành phố Hà Nội' → ward/district/province."""
    out = {"ward": "", "district": "", "province": ""}
    parts = [p.strip() for p in (address or "").split(",") if p.strip()]
    for part in parts:
        low = _norm_label(part)
        if low.startswith(("phuong", "xa", "thi tran")) and not out["ward"]:
            out["ward"] = part
        elif low.startswith(("quan", "huyen", "thi xa", "thanh pho thuoc")) and not out["district"]:
            out["district"] = part
        elif low.startswith(("thanh pho", "tinh")) and not out["province"]:
            out["province"] = part
    if not out["province"] and parts:
        out["province"] = parts[-1]
    if not out["district"] and len(parts) >= 2:
        out["district"] = parts[-2]
    return out