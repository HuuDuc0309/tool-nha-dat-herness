"""Runtime settings: record cap and Excel export switches.

`config/settings.json` is optional; missing keys fall back to these defaults so a
fresh checkout still runs. Values are read once per process.
"""
from __future__ import annotations

import json
from pathlib import Path

DEFAULT_SETTINGS = {
    "max_records": 500,
    "export": {
        # Extra sheets (Chưa xác định / Bằng chứng / Cảnh báo / Báo cáo crawl /
        # Thông tin bổ sung / Tin nghi trùng) cost tokens whenever an AI reads the
        # workbook, so they are opt-in. "Danh sách tin đăng" is always written.
        "extra_sheets": False,
        # Columns dropped from the main sheet. `confidence` is a heuristic score
        # that invites AI re-checking, so it is hidden unless explicitly enabled.
        "main_sheet_exclude_fields": ["confidence"],
    },
}


def _merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def load_settings(path: Path | str = Path("config/settings.json")) -> dict:
    path = Path(path)
    if not path.exists():
        return json.loads(json.dumps(DEFAULT_SETTINGS))
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} không phải JSON hợp lệ: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{path} phải là một JSON object")
    return _merge(DEFAULT_SETTINGS, data)


def max_records(settings: dict | None = None) -> int:
    """Record cap; <=0 means unlimited. Never negative in practice."""
    value = (settings or load_settings()).get("max_records", 500)
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return DEFAULT_SETTINGS["max_records"]