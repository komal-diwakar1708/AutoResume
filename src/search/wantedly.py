"""
Wantedly job search (Japan + some Asia).

⚠️ EXPERIMENTAL — Wantedly is a Next.js single-page app that loads its project
listings via a client-side GraphQL call, so the listings are NOT in the initial
HTML. This uses Playwright to render the page and read the project cards from the
DOM. Selectors are best-effort. Content is often Japanese. Disabled by default.
"""

import logging
import random
import re
import time
import urllib.parse
from typing import Optional

from .base import BaseSearcher, JobPosting

logger = logging.getLogger(__name__)

BASE = "https://www.wantedly.com"


class WantedlySearcher(BaseSearcher):
    source_name = "wantedly"

    def search(self, title: str, location: str) -> list[JobPosting]:
        # Wantedly is Japan-focused
        if "japan" not in location.lower() and "tokyo" not in location.lower():
            return []

        try:
            from playwright.sync_api import sync_playwright
            from playwright_stealth import stealth_sync
        except ImportError:
            logger.warning("[wantedly] Playwright not installed.")
            return []

        postings: list[JobPosting] = []
        q = urllib.parse.quote_plus(title)
        url = f"{BASE}/projects?q={q}"

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                locale="en",
            )
            page = context.new_page()
            stealth_sync(page)

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                try:
                    page.wait_for_selector("a[href*='/projects/']", timeout=15000)
                except Exception:
                    pass
                # Scroll to load more lazily-rendered cards
                for _ in range(3):
                    page.keyboard.press("End")
                    time.sleep(random.uniform(1, 2))

                anchors = page.query_selector_all("a[href*='/projects/']")
                seen: set[str] = set()
                count = 0
                for a in anchors:
                    try:
                        posting = self._parse_anchor(a, seen)
                        if posting:
                            postings.append(posting)
                            count += 1
                    except Exception as exc:
                        logger.debug("[wantedly] parse failed: %s", exc)
                logger.info("[wantedly] Found %d project cards for '%s'", count, title)

            except Exception as exc:
                logger.error("[wantedly] Page error: %s", exc)
            finally:
                browser.close()

        return postings

    def _parse_anchor(self, a, seen: set) -> Optional[JobPosting]:
        href = a.get_attribute("href") or ""
        # Only genuine project detail links: /projects/<id>
        if not re.search(r"/projects/\d+", href):
            return None
        url = (href if href.startswith("http") else f"{BASE}{href}").split("?")[0]
        if url in seen:
            return None
        seen.add(url)

        title = (a.inner_text() or "").strip().split("\n")[0]
        if not title:
            # Fall back to the image alt or aria-label
            title = (a.get_attribute("aria-label") or "").strip()
        if not title:
            return None

        return JobPosting(
            url=url,
            title=title,
            company="",
            location="Japan",
            source="wantedly",
            apply_url=url,
        )
