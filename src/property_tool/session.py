"""One browser session per site, reused for every request in a single run.

Why this exists
---------------
The previous pipeline started a browser in four separate places
(``phase_explorer`` once per phase, ``discover.explore``, and
``crawler._launch``) and closed the page after every fetch. Two effects were
visible to the user:

* request tabs were opened and closed repeatedly instead of keeping a work tab;
* independently created contexts did not share cookies or authentication state.

Reusing a context avoids throwing away that state. It cannot guarantee that a
website will accept the session or that a Cloudflare clearance will stay valid.

Design
------
* One Playwright driver for the whole run.
* One context per site — cookies/localStorage must never leak between domains.
* One *work page* per context, reused for every fetch and never closed. This is
  the piece that keeps the window alive while navigation happens in place.
* Persistent profile is reused (never re-created) so Cloudflare clearance is
  preserved for the duration of the run.

Nothing here bypasses Cloudflare. A challenge is surfaced to the human, and an
unsolved challenge is reported as ``blocked`` — never as success.
"""

from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path

from playwright.sync_api import sync_playwright

# English and Vietnamese markers. The Vietnamese page title is "Chờ một chút..."
# — a Vietnamese-only check missed it entirely and every follow-up
# ``page.content()`` failed against a challenge page we never noticed.
CHALLENGE_MARKERS = (
    "just a moment",
    "performing security verification",
    "verifying you are human",
    "attention required",
    "cf-chl",
    "chờ một chút",
    "chờ chút",
    "đang xác minh",
    "xác minh bạn là người",
)

ANCHOR_URL = "about:blank"


@dataclass
class SiteSession:
    """One site's browser context plus the single work page reused for it."""

    site_id: str
    context: object
    browser: object | None  # None for persistent contexts
    page: object | None = None
    persistent: bool = False
    challenge_solved_at: str | None = None
    challenge_count: int = 0

    def ensure_page(self):
        """Return the site's work page, re-creating it if it was closed.

        The page is never closed by the pipeline. Closing the last page destroys
        the context window and drops any Cloudflare clearance, which is exactly
        the flicker/re-challenge behaviour this module exists to prevent.
        """
        try:
            if self.page is not None and not self.page.is_closed():
                return self.page
        except Exception:
            pass
        self.page = self.context.new_page()
        return self.page


class SessionRuntime:
    """Owns the Playwright driver and one reusable context per site."""

    def __init__(self, headed: bool = False):
        self.headed = headed
        self.sessions: dict[str, SiteSession] = {}
        self._stack = ExitStack()
        self._pw = None
        self._closed = False

    # ------------------------------------------------------------------ life
    def __enter__(self) -> "SessionRuntime":
        if self._closed:
            raise RuntimeError("SessionRuntime đã đóng; tạo runtime mới cho lượt khác")
        if self._pw is None:
            self._pw = self._stack.enter_context(sync_playwright())
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    def close(self):
        """Idempotent teardown. Safe to call twice."""
        if self._closed:
            return
        self._closed = True
        for session in list(self.sessions.values()):
            self._close_session(session)
        self.sessions.clear()
        self._stack.close()
        self._pw = None

    def keep_alive_until_dismissed(self):
        """Show the browser and wait for the user before tearing down.

        Only meaningful interactively: the Playwright driver lives inside this
        process, so a browser cannot outlive the process. Call this instead of
        relying on a ``--keep-open`` flag inside ``close()``.
        """
        if not self.sessions:
            return
        print(">> Browser đang mở để kiểm tra. Nhấn Enter để đóng và kết thúc.",
              flush=True)
        try:
            input()
        except (EOFError, OSError):
            print(">> Không có stdin tương tác — đóng browser.", flush=True)

    @staticmethod
    def _close_session(session: SiteSession):
        try:
            if session.browser is not None:
                session.browser.close()
            else:
                session.context.close()
        except Exception:
            pass

    # ------------------------------------------------------------------ sites
    def site(self, site_id: str, profile_dir: str | None = None,
             viewport: dict | None = None, locale: str = "vi-VN") -> SiteSession:
        """Return the site's session, creating it once and reusing it after."""
        if self._closed or self._pw is None:
            raise RuntimeError(
                "SessionRuntime chưa được mở hoặc đã đóng — dùng `with SessionRuntime(...)`")

        existing = self.sessions.get(site_id)
        if existing is not None:
            existing.ensure_page()
            return existing

        viewport = viewport or {"width": 1440, "height": 1000}
        if profile_dir:
            profile = Path(profile_dir)
            profile.mkdir(parents=True, exist_ok=True)
            # launch_persistent_context returns a context, not a browser.
            context = self._pw.chromium.launch_persistent_context(
                str(profile),
                headless=not self.headed,
                viewport=viewport,
                locale=locale,
            )
            browser = None
            persistent = True
        else:
            browser = self._pw.chromium.launch(headless=not self.headed)
            context = browser.new_context(viewport=viewport, locale=locale)
            persistent = False

        session = SiteSession(
            site_id=site_id, context=context, browser=browser,
            page=None, persistent=persistent,
        )
        # The work page must exist before any request page is opened, otherwise
        # closing the first request page takes the window with it.
        session.page = session.ensure_page()
        self.sessions[site_id] = session
        print(f"   [session] mở context cho {site_id} "
              f"({'persistent' if persistent else 'ephemeral'})", flush=True)
        return session

    # -------------------------------------------------------------- challenge
    @staticmethod
    def is_challenge(page) -> bool:
        try:
            title = (page.title() or "").lower()
        except Exception:
            title = ""
        if any(m in title for m in CHALLENGE_MARKERS):
            return True
        try:
            body = page.locator("body").inner_text(timeout=4000).lower()[:2000]
        except Exception:
            body = ""
        return any(m in body for m in CHALLENGE_MARKERS)