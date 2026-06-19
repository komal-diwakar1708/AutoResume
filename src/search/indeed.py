"""
Indeed job search scraper using Playwright.
Searches jobs.indeed.com (international) and country-specific domains.
"""

import logging
import random
import time
import urllib.parse
from typing import Optional

from .base import BaseSearcher, JobPosting

logger = logging.getLogger(__name__)

# Map country names to Indeed domains
INDEED_DOMAINS: dict[str, str] = {
    "Germany": "de.indeed.com",
    "Singapore": "sg.indeed.com",
    "Japan": "jp.indeed.com",
    "Australia": "au.indeed.com",
    "New Zealand": "nz.indeed.com",
    "Canada": "ca.indeed.com",
    "United States": "www.indeed.com",
}


class IndeedSearcher(BaseSearcher):
    source_name = "indeed"

    def search(self, title: str, location: str) -> list[JobPosting]:
        try:
            from playwright.sync_api import sync_playwright
            from playwright_stealth import stealth_sync
        except ImportError:
            logger.warning("Playwright not installed.")
            return []

        domain = self._get_domain(location)
        postings: list[JobPosting] = []

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                )
            )
            page = context.new_page()
            stealth_sync(page)

            params = urllib.parse.urlencode({
                "q": title,
                "l": location,
                "fromage": "30",  # Last 30 days
                "sort": "date",
            })
            url = f"https://{domain}/jobs?{params}"

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                time.sleep(random.uniform(2, 4))

                job_cards = page.query_selector_all("div.job_seen_beacon")
                logger.info("[indeed] Found %d cards on %s for '%s'", len(job_cards), domain, title)

                for card in job_cards[:30]:
                    try:
                        posting = self._parse_card(card, domain)
                        if posting:
                            postings.append(posting)
                    except Exception as exc:
                        logger.debug("[indeed] Failed to parse card: %s", exc)

            except Exception as exc:
                logger.error("[indeed] Page error on %s: %s", domain, exc)
            finally:
                browser.close()

        return postings

    def _get_domain(self, location: str) -> str:
        for country, domain in INDEED_DOMAINS.items():
            if country.lower() in location.lower():
                return domain
        return "www.indeed.com"

    def _parse_card(self, card, domain: str) -> Optional[JobPosting]:
        title_el = card.query_selector("h2.jobTitle a")
        company_el = card.query_selector("span[data-testid='company-name']")
        location_el = card.query_selector("div[data-testid='text-location']")
        date_el = card.query_selector("span[data-testid='myJobsStateDate']")

        title = title_el.inner_text().strip() if title_el else ""
        company = company_el.inner_text().strip() if company_el else ""
        location = location_el.inner_text().strip() if location_el else ""
        posted = date_el.inner_text().strip() if date_el else ""

        href = title_el.get_attribute("href") if title_el else ""
        if not href:
            return None

        url = f"https://{domain}{href}" if href.startswith("/") else href

        return JobPosting(
            url=url,
            title=title,
            company=company,
            location=location,
            source="indeed",
            posted_date=posted,
            apply_url=url,
        )
