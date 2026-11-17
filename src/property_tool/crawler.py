"""Crawler for the batdongsan group platform (batdongsan.com.vn / batdongsan365.vn).

Design rules (per CLAUDE.md):
- Deterministic fetch/queue/pagination; no record is dropped for missing fields.
- A site that fails never blocks the other one — per-site, per-queue-item status.
- Cloudflare is never bypassed: the human solves it in a headed browser and the
  session is kept in a local persistent profile (gitignored).
- Every listing keeps its raw evidence (detail text + snapshot path).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from .adapters.batdongsan_group import (
    location_parts,
    next_page_urls,
    normalise_vnd,
    parse_area_m2,
    parse_listing_cards,
    strip_accents,
)
from .adapters import batdongsan_vn as adapter_vn
from .session import CHALLENGE_MARKERS, SessionRuntime


def detail_parser_for(platform: str):
    """Each platform gets its own detail parser; listing cards are shared."""
    if platform == "batdongsan_vn":
        return adapter_vn.parse_detail
    from .adapters.batdongsan_group import parse_detail as shared_detail

    return shared_detail

_PERIOD_PATTERNS = [
    (r"/\s*(?:th|tháng|thang)\b", "tháng"),
    (r"\b(?:mỗi\s+)?tháng\b", "tháng"),
    (r"/\s*(?:năm|nam|year)\b", "năm"),
    (r"\b(?:mỗi\s+)?năm\b", "năm"),
    (r"/\s*(?:ngày|ngay|day)\b", "ngày"),
]


def detect_period(price_text: str, price_vnd: str = "") -> str:
    """Infer the price period ONLY from evidence in the price text itself.

    Returns "" (Chưa xác định) when the text gives no period hint, e.g. a bare
    'Thỏa thuận' or a per-m² price with no '/tháng' suffix — never guesses a
    default, since a wrong period silently rescales the value by 12x.
    """
    if not price_text:
        return ""
    for pattern, label in _PERIOD_PATTERNS:
        if re.search(pattern, price_text, re.I):
            return label
    return ""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class QueueItem:
    url: str
    kind: str  # "listing" | "detail"
    site_id: str
    category: str = ""
    status: str = "pending"  # pending|success|warning|needs_review|failed|blocked
    notes: list = field(default_factory=list)
    attempts: int = 0


@dataclass
class SiteState:
    site_id: str
    base: str
    profile_dir: str | None
    cloudflare: bool
    detail_re: re.Pattern
    platform: str = "batdongsan_group"
    parse_detail: object = None
    needs_human: bool = False
    challenge_solved_at: str | None = None
    visited_listing: set = field(default_factory=set)
    visited_detail: set = field(default_factory=set)


def load_registry(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class Crawler:
    def __init__(self, registry: dict, out_root: Path, max_listing_pages: int,
                 max_details: int, delay: float, headed: bool, wait_human: int,
                 runtime: SessionRuntime | None = None):
        self.runtime = runtime
        self.registry = registry
        self.out_root = out_root
        self.max_listing_pages = max_listing_pages
        self.max_details = max_details
        self.delay = delay
        self.headed = headed
        self.wait_human = wait_human
        self.records: list[dict] = []
        self.evidence: list[dict] = []
        self.unknown: list[dict] = []
        self.warnings: list[dict] = []
        self.queue_items: list[dict] = []
        self.snapshot_root = out_root / "snapshots"

    # ------------------------------------------------------------------ browser
    def _session(self, runtime: SessionRuntime, state: SiteState):
        """One reusable context per site, with a work page keeping it alive."""
        session = runtime.site(state.site_id, profile_dir=state.profile_dir)
        return session.context, session.ensure_page()

    @staticmethod
    def _is_challenge(page) -> bool:
        return SessionRuntime.is_challenge(page)

    # Each platform needs a different marker to know the content has rendered.
    # A fixed timeout captured half-built pages (45 KB instead of ~1 MB), which
    # silently degraded address/area to card-level values.
    CONTENT_READY = {
        "batdongsan_vn": ("h1.re__pr-title", "div.re__pr-short-info-item"),
        "batdongsan_group_detail": ("h1", "div.property-content"),
        "batdongsan_group_listing": ("div.js__card-full-web",),
        "list": ("div.js__card-full-web",),
    }

    def _wait_content(self, page, state: SiteState, kind: str, url: str):
        platform = state.platform
        if kind == "detail":
            keys = [k for k in (platform, f"{platform}_detail") if k in self.CONTENT_READY]
        else:
            keys = [f"{platform}_listing", "list"]
        selectors: tuple[str, ...] = ()
        for key in keys:
            if key in self.CONTENT_READY:
                selectors = self.CONTENT_READY[key]
                break
        if not selectors:
            page.wait_for_timeout(2500)
            return
        for selector in selectors:
            try:
                page.wait_for_selector(selector, timeout=25000, state="attached")
            except Exception:
                self.warnings.append({
                    "site": state.site_id, "url": url,
                    "issue": "content_marker_missing",
                    "detail": f"selector {selector!r} không xuất hiện sau 25s — trang có thể chưa render "
                              "hoặc layout đã đổi; snapshot có thể thiếu dữ liệu",
                })
                return
        page.wait_for_timeout(600)  # let sibling fields settle after the marker

    def _ensure_session(self, ctx, state: SiteState, url: str, kind: str = "detail"):
        """Return a page ready for `url`, waiting for the human if challenged.

        The site's single work page is reused and never closed here: closing it
        would destroy the window and drop the Cloudflare clearance.
        """
        session = self.runtime.sessions[state.site_id]
        page = session.ensure_page()
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(1200)
        if self._is_challenge(page):
            if not self.headed:
                raise ChallengeRequired(state.site_id)
            print("=" * 78, flush=True)
            print(f"[{state.site_id}] Cloudflare challenge tại {url}", flush=True)
            print(f">> Mở browser có cửa sổ. Mời bạn giải thủ công (tối đa {self.wait_human}s).", flush=True)
            print("=" * 78, flush=True)
            deadline = time.time() + self.wait_human
            while time.time() < deadline:
                if not self._is_challenge(page):
                    try:
                        links = page.locator("a[href]").count()
                    except Exception:
                        links = 0
                    if links >= 20:
                        state.challenge_solved_at = now_iso()
                        state.needs_human = True
                        print(f">> Đã vượt challenge ({links} links). Tiếp tục crawl.", flush=True)
                        break
                page.wait_for_timeout(3000)
            else:
                raise ChallengeTimeout(state.site_id)
        self._wait_content(page, state, kind, url)
        return page

    # ------------------------------------------------------------------ fetching
    def _fetch(self, ctx, state: SiteState, url: str, kind: str) -> tuple[str, str]:
        """Returns (html, final_url); raises on challenge."""
        page = self._ensure_session(ctx, state, url, kind)
        return page.content(), page.url

    # ------------------------------------------------------------------ listing
    def crawl_site(self, site: dict) -> dict:
        site_id = site["site_id"]
        base = site["base"]
        state = SiteState(
            site_id=site_id,
            base=base,
            profile_dir=site.get("profile_dir"),
            cloudflare=site.get("cloudflare", False),
            detail_re=re.compile(site["detail_path_re"]),
            platform=site.get("platform", "batdongsan_group"),
            parse_detail=detail_parser_for(site.get("platform", "batdongsan_group")),
        )
        site_dir = self.snapshot_root / site_id
        site_dir.mkdir(parents=True, exist_ok=True)
        summary = {
            "site_id": site_id, "status": "success", "categories": [],
            "listings_fetched": 0, "details_fetched": 0, "records": 0,
            "blocked": False, "challenge_solved_at": None, "notes": [],
        }
        records_start = len(self.records)

        # Build the queue: category first pages first.
        queue: list[QueueItem] = []
        for cat in site["categories"]:
            queue.append(QueueItem(base.rstrip("/") + cat["path"], "listing", site_id, cat["key"]))

        listing_pages_done = 0
        detail_urls: list[tuple[str, dict]] = []  # (url, listing card data)
        pages_per_cat: dict[str, int] = defaultdict(int)  # cap is per-category

        # The runtime is owned by the caller so every site in the run shares one
        # Playwright driver; the per-site context is created once here.
        try:
            ctx, page = self._session(self.runtime, state)
        except Exception as exc:
            summary.update(status="failed", notes=[f"browser_launch_failed: {exc}"])
            self.queue_items.append({"site": site_id, "url": base, "kind": "site",
                                     "status": "failed", "notes": [str(exc)[:200]]})
            return summary

        try:
                while queue:
                    item = queue.pop(0)
                    item.attempts += 1
                    if item.kind == "listing":
                        if item.url in state.visited_listing:
                            item.status = "warning"
                            item.notes.append("duplicate listing url")
                            self._record_item(item)
                            continue
                        if pages_per_cat[item.category] >= self.max_listing_pages:
                            item.status = "warning"
                            item.notes.append(
                                f"category {item.category} hit its cap "
                                f"({self.max_listing_pages} pages)")
                            self._record_item(item)
                            continue
                        state.visited_listing.add(item.url)
                        try:
                            html, final = self._fetch(ctx, state, item.url, item.kind)
                            pages_per_cat[item.category] += 1
                            listing_pages_done += 1
                            summary["listings_fetched"] += 1
                            snap = site_dir / (
                                f"listing_{item.category}_{pages_per_cat[item.category]:03d}.html")
                            snap.write_text(html, encoding="utf-8")
                            cards = parse_listing_cards(html, base)
                            item.status = "success" if cards else "needs_review"
                            if not cards:
                                item.notes.append("0 cards parsed — layout may have changed")
                                self.warnings.append({
                                    "site": site_id, "url": item.url,
                                    "issue": "listing_no_cards",
                                    "detail": f"snapshot: {snap}",
                                })
                            for c in cards:
                                if c["url"] and c["url"] not in state.visited_detail:
                                    detail_urls.append((c["url"], c))
                            # pagination (bounded)
                            for nxt in next_page_urls(html, base):
                                if nxt not in state.visited_listing:
                                    queue.append(QueueItem(nxt, "listing", site_id, item.category))
                            item.notes.append(f"{len(cards)} cards")
                            summary["categories"].append({
                                "category": item.category, "page": item.url,
                                "cards": len(cards),
                            })
                        except ChallengeRequired:
                            item.status = "blocked"
                            item.notes.append("cloudflare challenge; needs headed browser")
                            summary["blocked"] = True
                            summary["status"] = "blocked"
                            self.warnings.append({
                                "site": site_id, "url": item.url,
                                "issue": "cloudflare_challenge",
                                "detail": "Chạy lại với --headed để human giải challenge.",
                            })
                            break
                        except ChallengeTimeout:
                            item.status = "blocked"
                            item.notes.append("cloudflare challenge not solved in time")
                            summary["blocked"] = True
                            summary["status"] = "blocked"
                            self.warnings.append({
                                "site": site_id, "url": item.url,
                                "issue": "cloudflare_challenge_timeout",
                                "detail": f"Human không giải xong trong {self.wait_human}s.",
                            })
                            break
                        except PlaywrightTimeoutError as exc:
                            item.status = "needs_review"
                            item.notes.append(f"timeout: {str(exc)[:150]}")
                            self.warnings.append({"site": site_id, "url": item.url,
                                                  "issue": "timeout", "detail": str(exc)[:300]})
                        except Exception as exc:
                            item.status = "failed"
                            item.notes.append(str(exc)[:250])
                            self.warnings.append({"site": site_id, "url": item.url,
                                                  "issue": "listing_error", "detail": str(exc)[:300]})
                        self._record_item(item)
                        time.sleep(self.delay)
                        continue

                    # ---- detail
                    if len(detail_urls) >= self.max_details:
                        break

                # Details
                for url, card in detail_urls[: self.max_details]:
                    state.visited_detail.add(url)
                    item = QueueItem(url, "detail", site_id)
                    item.attempts += 1
                    try:
                        html, final = self._fetch(ctx, state, url, "detail")
                        summary["details_fetched"] += 1
                        slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", urlparse(url).path)[-70:]
                        snap = site_dir / f"detail_{len(state.visited_detail):04d}_{slug}.html"
                        snap.write_text(html, encoding="utf-8")
                        d = state.parse_detail(html, final or url)
                        rec = self._to_record(d, card, site_id, snap)
                        self.records.append(rec)
                        self._add_evidence(d, card, rec, url, site_id, snap)
                        item.status = "success"
                        missing = [k for k, v in rec.items() if v == "" and k not in (
                            "extraction_status", "confidence", "warnings", "contact_masked",
                            "deposit", "frontage_m", "land_area_m2", "factory_area_m2",
                            "direction", "legal", "project", "address_alt")]
                        if missing:
                            item.status = "warning"
                            item.notes.append(f"missing: {','.join(missing[:8])}")
                    except ChallengeRequired:
                        item.status = "blocked"
                        summary["blocked"] = True
                        summary["status"] = "blocked"
                        self.warnings.append({"site": site_id, "url": url,
                                              "issue": "cloudflare_challenge",
                                              "detail": "detail fetch blocked by challenge"})
                        self._record_item(item)
                        break
                    except Exception as exc:
                        item.status = "failed"
                        item.notes.append(str(exc)[:250])
                        self.warnings.append({"site": site_id, "url": url,
                                              "issue": "detail_error", "detail": str(exc)[:300]})
                        # keep the card-level record so nothing is lost
                        self.records.append(self._card_only_record(card, site_id, url, str(exc)[:200]))
                    self._record_item(item)
                    time.sleep(self.delay)

                summary["challenge_solved_at"] = state.challenge_solved_at
                summary["records"] = len(self.records) - records_start
                if state.needs_human:
                    summary["notes"].append("Cloudflare đã được human giải; session lưu trong persistent profile.")
                if not summary["records"] and summary["status"] == "success":
                    summary["status"] = "needs_review"
                    summary["notes"].append("Không có record nào được tạo.")
        finally:
            # The context and its work page belong to the shared SessionRuntime
            # and are deliberately left open for later sites/steps. Closing them
            # per site is what caused the window to flicker and dropped the
            # Cloudflare clearance. Runtime.close() owns the real teardown.
            session = self.runtime.sessions.get(site_id)
            if session is not None:
                session.ensure_page()
        return summary

    def _record_item(self, item: QueueItem):
        self.queue_items.append({
            "site": item.site_id, "url": item.url, "kind": item.kind,
            "category": item.category, "status": item.status,
            "attempts": item.attempts, "notes": item.notes,
        })

    # ------------------------------------------------------------------ mapping
    def _to_record(self, detail: dict, card: dict, site_id: str, snap: Path) -> dict:
        raw_address = (detail.get("address") or card.get("location") or "").strip(" ·")
        loc = location_parts(raw_address)
        price_text = (detail.get("price_text") or card.get("price_text") or "").strip()
        price_vnd = normalise_vnd(price_text) if price_text else ""
        basis = card.get("price_basis") or "total"
        # a detail-page price that quotes "/m²" is per-m², not a total
        if re.search(r"/\s*m\s*2|/\s*m²|/m2", price_text, re.I):
            basis = "per_m2"
        elif price_text and normalise_vnd(price_text) == "":
            basis = "negotiable"
        per_m2_text = card.get("price_per_m2_text") or ""
        per_m2_vnd = card.get("price_per_m2_vnd") or ""
        if basis == "per_m2" and not per_m2_text:
            per_m2_text, per_m2_vnd = price_text, normalise_vnd(price_text)
        area_text = detail.get("area_text") or card.get("area_text") or ""
        area_m2 = parse_area_m2(area_text) if area_text else card.get("area_m2") or ""

        rec = {
            "title": detail.get("title") or card.get("title") or "",
            "source_url": detail.get("url") or card.get("url") or "",
            "source_site": site_id,
            "address": raw_address,
            "address_alt": detail.get("address_alt") or "",
            "province": loc["province"],
            "district": loc["district"],
            "ward": loc["ward"],
            # rent_amount is only a TOTAL monthly rent. When the site quotes a
            # price per m² there is no total (it depends on the leased area), so
            # rent_amount stays empty and the per-m² figure goes to supplement.
            "rent_amount": "" if basis in ("per_m2", "negotiable", "ambiguous") else price_vnd,
            "rent_amount_text": price_text,
            "price_per_m2_vnd": per_m2_vnd,
            "price_per_m2_text": per_m2_text,
            "rent_period": detect_period(price_text, price_vnd),
            "deposit": "",
            "land_area_m2": "",
            "factory_area_m2": "",
            "usable_area_m2": area_m2,
            "usable_area_text": area_text,
            "frontage_m": "",
            "contact": detail.get("contact") or "",
            "contact_masked": detail.get("contact_masked") or "",
            "extraction_status": "",
            "confidence": "",
            "warnings": "",
            # supplemental (sheet Thông tin bổ sung)
            "listing_code": detail.get("listing_code") or "",
            "posted_at": detail.get("posted_at") or "",
            "expires_at": detail.get("expires_at") or "",
            "post_type": detail.get("post_type") or "",
            "legal": detail.get("legal") or "",
            "direction": detail.get("direction") or "",
            "property_type": detail.get("property_type") or "",
            "project": detail.get("project") or "",
            "snapshot": str(snap),
            "collected_at": now_iso(),
        }

        # areas mentioned inside the free text (kho/xuong often only appear there).
        # Each label set may appear many times with different numbers ("DT từ 500m,
        # 700m, 1000m"), so ALL matches are collected — a single silent pick would
        # hide the fact that the listing offers several sizes.
        # Match on accent-stripped text so 'xưởng'/'xuong'/'khuôn viên' all work
        # regardless of how the poster typed them. Numbers are untouched.
        desc = unicodedata.normalize("NFC", detail.get("description") or card.get("description") or "")
        rec["description"] = desc[:4000]
        flat = strip_accents(desc)
        area_patterns = [
            # 'dien tich xuong: 5.000m2' / 'dien tich nha xuong 5.000 m2'
            ("factory_area_m2", r"dien tich\s+(?:nha\s+)?xuong\s*[:\-–]?\s*(\d[\d.,]*\s*m?\s*(?:2|²)?)"),
            # 'kho xuong: 10.000m2' / 'xuong 5.000m2' / 'kho hang 2.000m2'
            ("factory_area_m2", r"\b(?:kho\s+xuong|nha\s+xuong|xuong|kho(?:\s+hang)?)\s*[:\-–]\s*(\d[\d.,]*\s*m?\s*(?:2|²)?)"),
            # 'dien tich xay dung 10.000m2' / 'tong san 20.000m2'
            ("factory_area_m2", r"(?:dien tich\s+)?(?:xay\s+dung|tong\s+san|san)\s*[:\-–]?\s*(\d[\d.,]*\s*m?\s*(?:2|²)?)"),
            # 'dien tich khuon vien / dat / tong / mat bang <n>'
            ("land_area_m2", r"dien tich\s+(?:khuon vien|dat|tong|mat bang)\s*[:\-–]?\s*(\d[\d.,]*\s*m?\s*(?:2|²)?)"),
            ("land_area_m2", r"khuon vien\s*[:\-–]?\s*(\d[\d.,]*\s*m?\s*(?:2|²)?)"),
            # 'tong dien tich: 3.415,4 m2'
            ("land_area_m2", r"tong\s+dien\s+tich\s*[:\-–]?\s*(\d[\d.,]*\s*m?\s*(?:2|²)?)"),
        ]
        found_areas: dict[str, set] = {"factory_area_m2": set(), "land_area_m2": set()}
        for key, pat in area_patterns:
            for m in re.finditer(pat, flat, re.I):
                value = parse_area_m2(m.group(1))
                if value:
                    found_areas[key].add(value)
        for key, values in found_areas.items():
            if values:
                rec[key] = next(iter(values)) if len(values) == 1 else "; ".join(sorted(values, key=float))

        # every distinct area mentioned in the text, for conflict detection
        all_areas = {parse_area_m2(m) for m in re.findall(r"(\d[\d.,]*\s*m\s*(?:2|²)?)", flat, re.I)}
        all_areas = {a for a in all_areas if a}
        area_note = ""
        if len(all_areas) > 1:
            extra = sorted(all_areas - {rec.get("usable_area_m2") or ""}, key=lambda x: float(x))
            if extra:
                area_note = (
                    f"Trang nêu nhiều diện tích khác nhau ({', '.join(sorted(all_areas, key=float))} m²); "
                    f"usable_area_m2={rec.get('usable_area_m2')} là diện tích site hiển thị — "
                    "cần kiểm tra thủ công xem đó là đất, sàn hay phần cho thuê")
        if rec["factory_area_m2"] and ";" in str(rec["factory_area_m2"]):
            area_note = (area_note + "; " if area_note else "") + \
                f"Diện tích xưởng có nhiều giá trị: {rec['factory_area_m2']}"
        rec["area_conflict"] = area_note

        filled = sum(1 for k, v in rec.items() if v not in ("", None)
                     and k not in ("snapshot", "collected_at", "extraction_status", "confidence",
                                   "warnings", "source_site", "area_conflict"))
        total = len([k for k in rec if k not in ("snapshot", "collected_at", "extraction_status",
                                                 "confidence", "warnings", "source_site",
                                                 "description", "area_conflict")])
        rec["confidence"] = round(min(0.95, 0.35 + 0.6 * (filled / max(total, 1))), 2)
        warns = []
        if not rec["title"]:
            warns.append("Thiếu tiêu đề")
        if not rec["rent_amount"]:
            if basis == "per_m2":
                unit = "" if re.search(r"/\s*m\s*2|/\s*m²", price_text, re.I) else "/m²"
                warns.append(
                    f"Giá thuê theo m² ({price_text}{unit}), không có tổng giá — "
                    "tổng phụ thuộc diện tích thuê")
            elif basis == "negotiable":
                warns.append(f"Giá thuê thoả thuận, không có số ({price_text})")
            elif basis == "ambiguous":
                warns.append(
                    f"Giá '{price_text}' không đủ tin cậy để coi là tổng giá thuê "
                    "(nhỏ hơn/không khớp giá theo m², hoặc đơn vị lạ) — cần kiểm tra thủ công")
            elif price_text:
                warns.append(f"Giá thuê chưa parse được thành số (raw: {price_text})")
            else:
                warns.append("Không có giá thuê")
        if not rec["rent_period"]:
            warns.append("Chu kỳ giá chưa xác định (tin không nêu /tháng hay /năm)")
        if not rec["contact"]:
            warns.append("Không tìm thấy số liên hệ (site có thể ẩn)")
        elif rec.get("contact_masked") == "yes":
            warns.append("Số liên hệ bị ẩn một phần trên site (cần bấm 'Hiện số' để xem đầy đủ)")
        elif rec.get("contact") and not re.match(r"^0\d{8,10}$", str(rec["contact"]).replace(" ", "").replace(".", "")):
            warns.append(f"Số liên hệ có dạng bất thường, cần kiểm tra: {rec['contact']}")
        if rec["area_conflict"]:
            warns.append(rec["area_conflict"])
            rec["confidence"] = round(min(rec["confidence"], 0.6), 2)
        rec["warnings"] = "; ".join(warns)
        if rec["title"] and (rec["address"] or rec["usable_area_m2"]):
            base_status = "Đã parse HTML detail"
            rec["extraction_status"] = (
                f"{base_status} — cần kiểm tra" if rec["area_conflict"] else base_status)
        elif rec["title"]:
            rec["extraction_status"] = "Chỉ có dữ liệu card listing — cần kiểm tra"
            warns.append("Không vào được trang chi tiết")
            rec["warnings"] = "; ".join(warns)
        else:
            rec["extraction_status"] = "Không parse được nội dung"
        return rec

    def _card_only_record(self, card: dict, site_id: str, url: str, err: str) -> dict:
        """Same key set as a full record so the workbook schema stays uniform.

        A failed detail fetch must not silently change the column shape; the
        record simply carries empty values plus a clear status and warning.
        """
        loc = location_parts(card.get("location") or "")
        price_text = card.get("price_text", "")
        basis = card.get("price_basis") or "total"
        return {
            "title": card.get("title", ""),
            "source_url": card.get("url") or url,
            "source_site": site_id,
            "address": card.get("location", ""),
            "address_alt": "",
            "province": loc["province"], "district": loc["district"], "ward": loc["ward"],
            "rent_amount": "" if basis in ("per_m2", "negotiable", "ambiguous") else card.get("price_vnd", ""),
            "rent_amount_text": price_text,
            "price_per_m2_vnd": card.get("price_per_m2_vnd", ""),
            "price_per_m2_text": card.get("price_per_m2_text", ""),
            "rent_period": detect_period(price_text, card.get("price_vnd", "")),
            "deposit": "",
            "land_area_m2": "",
            "factory_area_m2": "",
            "usable_area_m2": card.get("area_m2", ""),
            "usable_area_text": card.get("area_text", ""),
            "frontage_m": "",
            "contact": "",
            "contact_masked": "",
            "listing_code": "",
            "posted_at": "",
            "expires_at": "",
            "post_type": "",
            "legal": "",
            "direction": "",
            "property_type": "",
            "project": "",
            "description": card.get("description", ""),
            "area_conflict": "",
            "extraction_status": "Chỉ có dữ liệu card listing — cần kiểm tra",
            "confidence": 0.35,
            "warnings": f"Không vào được trang chi tiết: {err[:150]}",
            "snapshot": "",
            "collected_at": now_iso(),
        }

    def _add_evidence(self, detail: dict, card: dict, rec: dict, url: str, site_id: str, snap: Path):
        src_text = (detail.get("description") or "")[:1200] or card.get("description", "")[:1200]
        for key in ("title", "address", "rent_amount", "rent_amount_text", "rent_period",
                    "price_per_m2_text", "usable_area_m2", "factory_area_m2", "land_area_m2",
                    "contact", "posted_at", "legal"):
            value = rec.get(key, "")
            if value not in ("", None):
                self.evidence.append({
                    "source_url": url, "site": site_id, "field": key, "value": value,
                    "source_text": src_text[:600], "snapshot": str(snap),
                    "confidence": rec.get("confidence", 0),
                })
            else:
                self.unknown.append({
                    "source_url": url, "site": site_id, "field": key,
                    "reason": "Không tìm thấy trong trang detail/card",
                })
        # every attribute row seen on the detail page is evidence too
        for label, value in (detail.get("attributes") or {}).items():
            self.evidence.append({
                "source_url": url, "site": site_id, "field": f"attr:{label}", "value": value,
                "source_text": src_text[:300], "snapshot": str(snap),
                "confidence": rec.get("confidence", 0),
            })


class ChallengeRequired(Exception):
    pass


class ChallengeTimeout(Exception):
    pass


def crawl(registry_path: Path, out_root: Path, site_filter: list[str] | None = None,
          max_listing_pages: int = 5, max_details: int = 200, delay: float = 1.5,
          headed: bool = False, wait_human: int = 300,
          keep_open: bool = False) -> dict:
    reg = load_registry(registry_path)
    site_summaries = []
    with SessionRuntime(headed=headed) as runtime:
        crawler = Crawler(reg, out_root, max_listing_pages, max_details, delay,
                          headed, wait_human, runtime=runtime)
        for site in reg["sites"]:
            if site_filter and site["site_id"] not in site_filter:
                continue
            print(f"\n### CRAWL {site['site_id']} (categories={len(site['categories'])}) ###", flush=True)
            try:
                site_summaries.append(crawler.crawl_site(site))
            except Exception as exc:  # a site never blocks the others
                site_summaries.append({
                    "site_id": site["site_id"], "status": "failed",
                    "notes": [f"unhandled: {exc}"[:300]], "records": 0,
                })
                crawler.warnings.append({"site": site["site_id"], "url": site["base"],
                                         "issue": "site_error", "detail": str(exc)[:400]})
        if keep_open:
            runtime.keep_alive_until_dismissed()
    return {
        "generated_at": now_iso(),
        "sites": site_summaries,
        "records": crawler.records,
        "evidence": crawler.evidence,
        "unknown": crawler.unknown,
        "warnings": crawler.warnings,
        "queue": crawler.queue_items,
    }


def main():
    ap = argparse.ArgumentParser(description="Crawl batdongsan group sites")
    ap.add_argument("--sites", nargs="*", help="site_id(s); default = all in registry")
    ap.add_argument("--registry", type=Path, default=Path("config/sites.json"))
    ap.add_argument("--out", type=Path, required=True, help="job directory for raw JSON")
    ap.add_argument("--max-listing-pages", type=int, default=5)
    ap.add_argument("--max-details", type=int, default=200)
    ap.add_argument("--delay", type=float, default=1.5, help="seconds between requests (rate limit)")
    ap.add_argument("--headed", action="store_true", help="visible browser so a human can solve challenges")
    ap.add_argument("--wait-human", type=int, default=300)
    ap.add_argument("--keep-open", action="store_true",
                    help="giữ browser mở sau khi crawl xong để kiểm tra thủ công")
    args = ap.parse_args()

    result = crawl(args.registry, args.out, args.sites, args.max_listing_pages,
                   args.max_details, args.delay, args.headed, args.wait_human,
                   keep_open=args.keep_open)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "crawl-result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "status": "success",
        "records": len(result["records"]),
        "evidence": len(result["evidence"]),
        "warnings": len(result["warnings"]),
        "sites": [{"site_id": s["site_id"], "status": s["status"],
                   "records": s.get("records"), "listings": s.get("listings_fetched"),
                   "details": s.get("details_fetched")} for s in result["sites"]],
        "output": str(args.out / "crawl-result.json"),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()