"""
StepStone.de job search scraper.
Primary job board for Germany.
"""

import logging
import random
import time
import urllib.parse
from typing import Optional

from .base import BaseSearcher, JobPosting

logger = logging.getLogger(__name__)

STEPSTONE_BASE = "https://www.stepstone.de"


class StepStoneSearcher(BaseSearcher):
    source_name = "stepstone"

    def search(self, title: str, location: str) -> list[JobPosting]:
        # StepStone is only relevant for Germany
        if "germany" not in location.lower() and "deutschland" not in location.lower():
            return []

        try:
            from playwright.sync_api import sync_playwright
            from playwright_stealth import stealth_sync
        except ImportError:
            logger.warning("Playwright not installed.")
            return []

        postings: list[JobPosting] = []

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                locale="de-DE",
            )
            page = context.new_page()
            stealth_sync(page)

            keywords = urllib.parse.quote(title)
            # StepStone age buckets: age_1, age_3, age_7, age_14, age_30
            bucket = min([1, 3, 7, 14, 30], key=lambda b: abs(b - self.max_age_days))
            url = f"{STEPSTONE_BASE}/jobs/{keywords}.html?where=Deutschland&radius=200&ag=age_{bucket}"

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                time.sleep(random.uniform(2, 4))

                # Accept cookies if prompt appears
                try:
                    accept_btn = page.query_selector("button#ccmgt_explicit_accept")
                    if accept_btn:
                        accept_btn.click()
                        time.sleep(1)
                except Exception:
                    pass

                job_cards = page.query_selector_all("article.sc-beqWAB")
                if not job_cards:
                    # Fallback selector
                    job_cards = page.query_selector_all("[data-genesis-element='BASE_CARD']")

                logger.info("[stepstone] Found %d cards for '%s'", len(job_cards), title)

                for card in job_cards[:30]:
                    try:
                        posting = self._parse_card(card)
                        if posting:
                            postings.append(posting)
                    except Exception as exc:
                        logger.debug("[stepstone] Failed to parse card: %s", exc)

            except Exception as exc:
                logger.error("[stepstone] Page error: %s", exc)
            finally:
                browser.close()

        return postings

    def _parse_card(self, card) -> Optional[JobPosting]:
        title_el = card.query_selector("h2 a") or card.query_selector("a[data-at='job-item-title']")
        company_el = card.query_selector("[data-at='job-item-company-name']")
        location_el = card.query_selector("[data-at='job-item-location']")

        title = title_el.inner_text().strip() if title_el else ""
        company = company_el.inner_text().strip() if company_el else ""
        location = location_el.inner_text().strip() if location_el else ""

        href = title_el.get_attribute("href") if title_el else ""
        if not href or not title:
            return None

        url = f"{STEPSTONE_BASE}{href}" if href.startswith("/") else href

        return JobPosting(
            url=url,
            title=title,
            company=company,
            location=location,
            source="stepstone",
            apply_url=url,
        )
