"""
MyCareersFuture.sg job search — Singapore's official government job portal.

Unlike the other sources, MyCareersFuture exposes a clean public JSON API, so
this searcher uses direct HTTP requests (no browser needed). It is fast,
reliable, and returns structured data including skills and salary.

API: POST https://api.mycareersfuture.gov.sg/v2/search?limit=N&page=0
     body: {"search": "<keywords>", "sessionId": "", "sortBy": ["new_posting_date"]}
"""

import json
import logging
import urllib.request
from datetime import datetime, timedelta
from typing import Optional

from .base import BaseSearcher, JobPosting

logger = logging.getLogger(__name__)

MCF_SEARCH_API = "https://api.mycareersfuture.gov.sg/v2/search"


class MyCareersFutureSearcher(BaseSearcher):
    source_name = "mycareersfuture"

    def search(self, title: str, location: str) -> list[JobPosting]:
        # MyCareersFuture only covers Singapore
        if "singapore" not in location.lower():
            return []

        limit = min(self.max_results, 100)
        url = f"{MCF_SEARCH_API}?limit={limit}&page=0"
        body = json.dumps({
            "search": title,
            "sessionId": "",
            "sortBy": ["new_posting_date"],
        }).encode("utf-8")

        req = urllib.request.Request(url, data=body, headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/124.0.0.0 Safari/537.36",
        })

        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.load(r)
        except Exception as exc:
            logger.error("[mycareersfuture] API error for '%s': %s", title, exc)
            return []

        results = data.get("results", []) or []
        logger.info("[mycareersfuture] Found %d results for '%s'", len(results), title)

        cutoff = datetime.now().date() - timedelta(days=self.max_age_days)
        postings: list[JobPosting] = []

        for j in results:
            posting = self._parse(j, cutoff)
            if posting:
                postings.append(posting)

        return postings

    def _parse(self, j: dict, cutoff) -> Optional[JobPosting]:
        meta = j.get("metadata") or {}
        url = meta.get("jobDetailsUrl", "")
        title = (j.get("title") or "").strip()
        if not url or not title:
            return None

        # Freshness filter — skip postings older than the configured window
        posted = meta.get("newPostingDate", "")
        if posted:
            try:
                if datetime.strptime(posted, "%Y-%m-%d").date() < cutoff:
                    return None
            except ValueError:
                pass

        company = ""
        posted_company = j.get("postedCompany") or {}
        hiring_company = j.get("hiringCompany") or {}
        company = (posted_company.get("name") or hiring_company.get("name") or "").strip()

        # Location — Singapore unless the posting is explicitly overseas
        addr = j.get("address") or {}
        if addr.get("isOverseas") and addr.get("overseasCountry"):
            location = addr["overseasCountry"]
        else:
            location = "Singapore"

        # The search API doesn't return the full description, but it returns a
        # rich skills list + categories + position levels. We synthesise a
        # description string so the keyword scorer still has something to match.
        skills = [s.get("skill", "") for s in (j.get("skills") or [])]
        categories = [c.get("category", "") for c in (j.get("categories") or [])]
        levels = [p.get("position", "") for p in (j.get("positionLevels") or [])]
        description = " ".join(filter(None, skills + categories + levels))

        return JobPosting(
            url=url,
            title=title,
            company=company,
            location=location,
            description=description,
            source="mycareersfuture",
            posted_date=posted,
            apply_url=url,
        )
