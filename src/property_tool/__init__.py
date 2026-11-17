"""Property data collection MVP."""
import sys


def _force_utf8_stdio() -> None:
    """Vietnamese labels and scraped text crash a cp1252 console on Windows."""
    for stream in (sys.stdout, sys.stderr):
        encoding = (getattr(stream, "encoding", "") or "").lower().replace("-", "")
        if encoding != "utf8":
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (AttributeError, ValueError):
                pass


_force_utf8_stdio()