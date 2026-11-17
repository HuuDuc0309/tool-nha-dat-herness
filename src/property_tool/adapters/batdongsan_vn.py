"""Parser for the *new* batdongsan.com.vn detail layout (re__pr-* markup).

The site shares a brand with batdongsan365.vn but the 2026 redesign uses a
different detail template:

    div.re__pr-info
      h1.re__pr-title
      div.re__ldp-address > span.re__address > span.re__address-line-1 / -2
      div.re__pr-short-info-item > span.title + span.value   (price, area, dates, code)
      div.re__pr-specs-content-item > ...-title + ...-value  (extra attributes)
      div.re__detail-content                                  (free-text description)
      disclaimer text  'Mã tin <id>'

No JSON-LD is emitted, so everything is read from that markup. Attributes are
returned raw; normalisation happens in the caller.
"""

from __future__ import annotations

import re
from html import unescape

_WS = re.compile(r"\s+")
_TAG = re.compile(r"<[^>]+>")


def strip_html(value: str) -> str:
    if not value:
        return ""
    return _WS.sub(" ", unescape(_TAG.sub(" ", value))).strip()


_H1_RE = re.compile(r'<h1[^>]*class="[^"]*re__pr-title[^"]*"[^>]*>(.*?)</h1>', re.S)
_ADDR1_RE = re.compile(r'<span class="re__address-line-1[^"]*">(.*?)</span>', re.S)
_ADDR2_RE = re.compile(r'<span class="re__address-line-2[^"]*">(.*?)</span>', re.S)
_SHORT_ITEM_RE = re.compile(
    r'<div class="re__pr-short-info-item[^"]*">\s*'
    r'<span class="title">(.*?)</span>\s*'
    r'<span class="value">(.*?)</span>',
    re.S,
)
_SPEC_ITEM_RE = re.compile(
    r'<div class="re__pr-specs-content-item">(.*?)</div>\s*</div>', re.S
)
_SPEC_TITLE_RE = re.compile(r'content-item-title">(.*?)</span>', re.S)
_SPEC_VALUE_RE = re.compile(r'content-item-value">(.*?)</span>', re.S)
_DESC_RE = re.compile(r'class="[^"]*re__detail-content[^"]*"[^>]*>(.*?)(?=<div class="re__section|</div>\s*</div>\s*</div>)', re.S)
_CODE_RE = re.compile(r"Mã tin\s*(\d{4,})")
_BREADCRUMB_RE = re.compile(r're__breadcrumb[^"]*"[^>]*>(.*?)</div>', re.S)
_PROJECT_RE = re.compile(r'class="[^"]*re__project-name[^"]*"[^>]*>(.*?)</', re.S)

LABEL_MAP = {
    "khoang gia": "price_text",
    "muc gia": "price_text",
    "gia thue": "price_text",
    "dien tich": "area_text",
    "ngay dang": "posted_at",
    "ngay het han": "expires_at",
    "loai tin": "post_type",
    "ma tin": "listing_code",
    "phap ly": "legal",
    "huong": "direction",
    "so phong ngu": "bedrooms",
    "so phong tam": "bathrooms",
    "so tang": "floors",
    "loai hinh": "property_type",
}


def _norm(text: str) -> str:
    import unicodedata

    text = text.replace("đ", "d").replace("Đ", "D")
    decomposed = unicodedata.normalize("NFD", text)
    return _WS.sub(" ", "".join(c for c in decomposed if not unicodedata.combining(c))).strip().lower()


def _match(label: str) -> str:
    key = _norm(label)
    for want, dest in LABEL_MAP.items():
        if key == want or key.startswith(want):
            return dest
    return ""


def parse_detail(html: str, url: str) -> dict:
    out = {
        "title": "", "address": "", "address_alt": "",
        "price_text": "", "area_text": "", "legal": "", "direction": "",
        "bedrooms": "", "bathrooms": "", "floors": "", "property_type": "",
        "listing_code": "", "posted_at": "", "expires_at": "", "post_type": "",
        "contact": "", "description": "", "breadcrumb": "", "project": "",
        "attributes": {}, "url": url,
    }

    m = _H1_RE.search(html)
    if m:
        out["title"] = strip_html(m.group(1))

    m = _ADDR1_RE.search(html)
    if m:
        out["address"] = strip_html(m.group(1))
    m = _ADDR2_RE.search(html)
    if m:
        out["address_alt"] = strip_html(m.group(1)).strip("() ")

    # short-info block (price / area / dates / code)
    for m in _SHORT_ITEM_RE.finditer(html):
        label, value = strip_html(m.group(1)), strip_html(m.group(2))
        if not label or not value:
            continue
        out["attributes"][label] = value
        dest = _match(label)
        if dest and not out.get(dest):
            out[dest] = value

    # specs block (extra attributes)
    for m in _SPEC_ITEM_RE.finditer(html):
        body = m.group(1)
        t = _SPEC_TITLE_RE.search(body)
        v = _SPEC_VALUE_RE.search(body)
        if not (t and v):
            continue
        label, value = strip_html(t.group(1)), strip_html(v.group(1))
        if not label or not value:
            continue
        out["attributes"].setdefault(label, value)
        dest = _match(label)
        if dest and not out.get(dest):
            out[dest] = value

    m = _CODE_RE.search(html)
    if m:
        out["listing_code"] = out["listing_code"] or m.group(1)

    m = _DESC_RE.search(html)
    if m:
        out["description"] = strip_html(m.group(1))[:8000]

    m = _BREADCRUMB_RE.search(html)
    if m:
        out["breadcrumb"] = strip_html(m.group(1))[:300]

    m = _PROJECT_RE.search(html)
    if m:
        out["project"] = strip_html(m.group(1))[:200]

    # Contact: batdongsan.com.vn masks broker numbers ('0937 992 ***') and links
    # the site hotline via tel:. The masked form is kept verbatim as evidence —
    # the real number must be revealed interactively, which this tool never does.
    desc = out["description"]
    masked = re.findall(r"0\d{2,3}(?:[\s.]\d{2,4}){1,2}[\s.]?\*{3,}", desc) or \
        re.findall(r"0\d{2,3}(?:[\s.]\d{2,4}){1,2}[\s.]?\*{3,}", html)
    unmasked = re.findall(r"\b0(?!1900)\d{8,9}\b", desc)
    if unmasked:
        out["contact"] = unmasked[0]
        out["contact_masked"] = ""
    elif masked:
        out["contact"] = masked[0].strip()
        out["contact_masked"] = "yes"
    else:
        out["contact"] = ""
        out["contact_masked"] = ""
    return out


def parse_listing_cards(html: str, base: str) -> list[dict]:
    """Listing pages on the redesigned site use the same re__card markup."""
    from .batdongsan_group import parse_listing_cards as shared

    return shared(html, base)