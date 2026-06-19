"""
JSearch API searcher — aggregates LinkedIn, Indeed, Glassdoor, ZipRecruiter, and
20+ other boards via a single RapidAPI endpoint.

API docs: https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch
Free tier: 500 requests/month
"""

import logging
import os
import time
from typing import Optional

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from .base import BaseSearcher, JobPosting

logger = logging.getLogger(__name__)

JSEARCH_BASE_URL = "https://jsearch.p.rapidapi.com/search"


def _is_retriable(exc: BaseException) -> bool:
    """Only retry on transient errors — never on auth/quota errors."""
    if isinstance(exc, httpx.HTTPStatusError):
        # 401 = bad key, 403 = forbidden, 429 = quota exhausted → don't retry
        return exc.response.status_code not in (401, 403, 429)
    return isinstance(exc, (httpx.TimeoutException, httpx.NetworkError))


class JSearchSearcher(BaseSearcher):
    source_name = "jsearch"

    def __init__(self, config: dict):
        super().__init__(config)
        self.api_key = os.getenv("RAPIDAPI_KEY", "")
        if not self.api_key:
            raise ValueError("RAPIDAPI_KEY not set in .env")
        self.headers = {
            "X-RapidAPI-Key": self.api_key,
            "X-RapidAPI-Host": "jsearch.p.rapidapi.com",
        }
        # Set to True after a fatal auth/quota error so we stop hammering the API
        self._disabled = False
        self._disabled_reason = ""

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception(_is_retriable),
        reraise=True,
    )
    def _call_api(self, query: str, location: str, page: int = 1) -> dict:
        params = {
            "query": f"{query} in {location}",
            "page": str(page),
            "num_pages": "1",
            "date_posted": "month",
            "employment_types": "FULLTIME",
        }
        with httpx.Client(timeout=30) as client:
            resp = client.get(JSEARCH_BASE_URL, headers=self.headers, params=params)
            resp.raise_for_status()
            return resp.json()

    def search(self, title: str, location: str) -> list[JobPosting]:
        if self._disabled:
            return []

        logger.info("[jsearch] Searching '%s' in '%s'", title, location)
        try:
            data = self._call_api(title, location)
        except httpx.HTTPStatusError as exc:
            self._handle_http_error(exc)
            return []
        except Exception as exc:
            logger.error("[jsearch] API error: %s", exc)
            return []

        postings: list[JobPosting] = []
        for item in data.get("data", []):
            url = item.get("job_apply_link") or item.get("job_google_link", "")
            if not url:
                continue

            postings.append(
                JobPosting(
                    url=url,
                    title=item.get("job_title", ""),
                    company=item.get("employer_name", ""),
                    location=self._format_location(item),
                    description=item.get("job_description", ""),
                    source="jsearch",
                    posted_date=item.get("job_posted_at_datetime_utc", ""),
                    apply_url=item.get("job_apply_link", ""),
                )
            )

        logger.info("[jsearch] Found %d results for '%s' in '%s'", len(postings), title, location)
        time.sleep(1)  # Rate-limit courtesy
        return postings

    def _format_location(self, item: dict) -> str:
        parts = [
            item.get("job_city", ""),
            item.get("job_state", ""),
            item.get("job_country", ""),
        ]
        return ", ".join(p for p in parts if p)

    def _handle_http_error(self, exc: httpx.HTTPStatusError) -> None:
        """Log a clear, actionable message based on the HTTP status code."""
        code = exc.response.status_code
        body = ""
        try:
            body = exc.response.text[:300]
        except Exception:
            pass

        if code == 401:
            logger.error(
                "[jsearch] 401 Unauthorized — your RAPIDAPI_KEY is invalid. "
                "Check .env and copy the key from rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch."
            )
            self._disabled = True
            self._disabled_reason = "invalid api key"
        elif code == 403:
            logger.error(
                "[jsearch] 403 Forbidden — your RAPIDAPI_KEY is not subscribed to JSearch. "
                "Subscribe to the FREE Basic plan at rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch/pricing."
            )
            self._disabled = True
            self._disabled_reason = "not subscribed"
        elif code == 429:
            logger.error(
                "[jsearch] 429 Quota exceeded — JSearch free tier allows 200 requests/month. "
                "Upgrade your plan or wait for next month's reset. Disabling JSearch for this run."
            )
            self._disabled = True
            self._disabled_reason = "quota exceeded"
        elif 500 <= code < 600:
            logger.error("[jsearch] %d Server error — JSearch API is having issues. Body: %s", code, body)
        else:
            logger.error("[jsearch] HTTP %d error. Body: %s", code, body)
