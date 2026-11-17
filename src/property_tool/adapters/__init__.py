"""Site-specific parsers.

Each module targets one platform/template and exposes:

    parse_detail(html, url) -> dict
    parse_listing_cards(html, base) -> list[dict]    (optional)

Adding a site: create a module here, register it in config/sites.json under
`platform`, and add snapshot tests to src/property_tool/regression.py.
"""

from . import batdongsan_group, batdongsan_vn  # noqa: F401

__all__ = ["batdongsan_group", "batdongsan_vn"]