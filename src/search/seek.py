"""
Seek.com.au / Seek.co.nz job search scraper.
Covers Australia and New Zealand.
"""

import logging
import random
import time
import urllib.parse
from typing import Optional

from .base import BaseSearcher, JobPosting

logger = logging.getLogger(__name__)

SEEK_DOMAINS: dict[str, str] = {
    "Australia": "www.seek.com.au",
    "New Zealand": "www.seek.co.nz",
}


class SeekSearcher(BaseSearcher):
    source_name = "seek"

    def search(self, title: str, location: str) -> list[JobPosting]:
        domain = self._get_domain(location)
        if not domain:
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
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                )
            )
            page = context.new_page()
            stealth_sync(page)

            keywords = urllib.parse.quote(title)
            url = f"https://{domain}/{keywords}-jobs/in-All-{location.replace(' ', '-')}?daterange=30"

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                time.sleep(random.uniform(2, 4))

                job_cards = page.query_selector_all("article[data-card-type='JobCard']")
                logger.info("[seek] Found %d cards on %s for '%s'", len(job_cards), domain, title)

                for card in job_cards[:30]:
                    try:
                        posting = self._parse_card(card, domain)
                        if posting:
                            postings.append(posting)
                    except Exception as exc:
                        logger.debug("[seek] Failed to parse card: %s", exc)

            except Exception as exc:
                logger.error("[seek] Page error: %s", exc)
            finally:
                browser.close()

        return postings

    def _get_domain(self, location: str) -> Optional[str]:
        for country, domain in SEEK_DOMAINS.items():
            if country.lower() in location.lower():
                return domain
        return None

    def _parse_card(self, card, domain: str) -> Optional[JobPosting]:
        title_el = card.query_selector("a[data-automation='jobTitle']")
        company_el = card.query_selector("a[data-automation='jobCompany']")
        location_el = card.query_selector("a[data-automation='jobLocation']")
        date_el = card.query_selector("span[data-automation='jobListingDate']")

        title = title_el.inner_text().strip() if title_el else ""
        company = company_el.inner_text().strip() if company_el else ""
        location = location_el.inner_text().strip() if location_el else ""
        posted = date_el.inner_text().strip() if date_el else ""

        href = title_el.get_attribute("href") if title_el else ""
        if not href or not title:
            return None

        url = f"https://{domain}{href}" if href.startswith("/") else href

        return JobPosting(
            url=url,
            title=title,
            company=company,
            location=location,
            source="seek",
            posted_date=posted,
            apply_url=url,
        )
