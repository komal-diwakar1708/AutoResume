"""
eFinancialCareers job search (finance / fintech roles, many countries).

⚠️ EXPERIMENTAL — eFinancialCareers is an Angular single-page app that renders
job cards client-side, so this uses Playwright to render the page and then reads
the DOM. The CSS selectors here are best-effort and may need updating if the
site changes its markup. Disabled by default in settings.yaml.
"""

import logging
import random
import time
import urllib.parse
from typing import Optional

from .base import BaseSearcher, JobPosting

logger = logging.getLogger(__name__)

BASE = "https://www.efinancialcareers.com"


class EFinancialCareersSearcher(BaseSearcher):
    source_name = "efinancialcareers"

    def search(self, title: str, location: str) -> list[JobPosting]:
        try:
            from playwright.sync_api import sync_playwright
            from playwright_stealth import stealth_sync
        except ImportError:
            logger.warning("[efinancialcareers] Playwright not installed.")
            return []

        postings: list[JobPosting] = []
        q = urllib.parse.quote_plus(title)
        loc = urllib.parse.quote_plus(location)
        url = f"{BASE}/jobs?keyword={q}&location={loc}"

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                )
            )
            page = context.new_page()
            stealth_sync(page)

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                # Wait for client-side rendering of job cards
                try:
                    page.wait_for_selector(
                        "article, [data-testid*='job'], a[href*='/jobs/']",
                        timeout=15000,
                    )
                except Exception:
                    pass
                time.sleep(random.uniform(2, 4))

                cards = (
                    page.query_selector_all("article[data-testid='job-card']")
                    or page.query_selector_all("article")
                )
                logger.info("[efinancialcareers] Found %d cards for '%s'", len(cards), title)

                for card in cards[:30]:
                    try:
                        posting = self._parse_card(card, location)
                        if posting:
                            postings.append(posting)
                    except Exception as exc:
                        logger.debug("[efinancialcareers] parse failed: %s", exc)

            except Exception as exc:
                logger.error("[efinancialcareers] Page error: %s", exc)
            finally:
                browser.close()

        return postings

    def _parse_card(self, card, location: str) -> Optional[JobPosting]:
        link_el = (
            card.query_selector("a[href*='/jobs/']")
            or card.query_selector("a[data-testid*='title']")
            or card.query_selector("h2 a, h3 a")
        )
        if not link_el:
            return None

        title = (link_el.inner_text() or "").strip()
        href = link_el.get_attribute("href") or ""
        if not title or not href:
            return None
        url = href if href.startswith("http") else f"{BASE}{href}"

        company_el = (
            card.query_selector("[data-testid*='company']")
            or card.query_selector(".company, .companyName")
        )
        loc_el = card.query_selector("[data-testid*='location'], .location")

        company = (company_el.inner_text().strip() if company_el else "")
        job_loc = (loc_el.inner_text().strip() if loc_el else location)

        return JobPosting(
            url=url.split("?")[0],
            title=title,
            company=company,
            location=job_loc,
            source="efinancialcareers",
            apply_url=url,
        )
