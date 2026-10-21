"""
LinkedIn job search scraper using Playwright.
Uses the public jobs search (no login required for searching).
Login credentials are used for Easy Apply (handled in src/apply/linkedin_apply.py).
"""

import logging
import random
import time
import urllib.parse
from typing import Optional

from .base import BaseSearcher, JobPosting

logger = logging.getLogger(__name__)

LINKEDIN_JOBS_URL = "https://www.linkedin.com/jobs/search/"


class LinkedInSearcher(BaseSearcher):
    source_name = "linkedin"

    def search(self, title: str, location: str) -> list[JobPosting]:
        try:
            from playwright.sync_api import sync_playwright
            from playwright_stealth import stealth_sync
        except ImportError:
            logger.warning("Playwright not installed. Run: pip install playwright playwright-stealth && playwright install chromium")
            return []

        postings: list[JobPosting] = []

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

            params = urllib.parse.urlencode({
                "keywords": title,
                "location": location,
                "f_TPR": f"r{self.max_age_days * 86400}",  # posted within N days (seconds)
                "f_JT": "F",          # Full-time
                "start": "0",
            })
            url = f"{LINKEDIN_JOBS_URL}?{params}"

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                time.sleep(random.uniform(2, 4))

                # Scroll to load more results
                for _ in range(3):
                    page.keyboard.press("End")
                    time.sleep(random.uniform(1, 2))

                job_cards = page.query_selector_all("div.base-card")
                logger.info("[linkedin] Found %d cards for '%s' in '%s'", len(job_cards), title, location)

                for card in job_cards[:30]:
                    try:
                        posting = self._parse_card(card)
                        if posting:
                            postings.append(posting)
                    except Exception as exc:
                        logger.debug("[linkedin] Failed to parse card: %s", exc)

            except Exception as exc:
                logger.error("[linkedin] Page error: %s", exc)
            finally:
                browser.close()

        return postings

    def _parse_card(self, card) -> Optional[JobPosting]:
        title_el = card.query_selector("h3.base-search-card__title")
        company_el = card.query_selector("h4.base-search-card__subtitle")
        location_el = card.query_selector("span.job-search-card__location")
        link_el = card.query_selector("a.base-card__full-link")
        date_el = card.query_selector("time")

        title = title_el.inner_text().strip() if title_el else ""
        company = company_el.inner_text().strip() if company_el else ""
        location = location_el.inner_text().strip() if location_el else ""
        url = link_el.get_attribute("href") if link_el else ""
        posted = date_el.get_attribute("datetime") if date_el else ""

        if not url or not title:
            return None

        # Normalise URL — strip tracking params
        url = url.split("?")[0]

        return JobPosting(
            url=url,
            title=title,
            company=company,
            location=location,
            source="linkedin",
            posted_date=posted,
            apply_url=url,
        )
