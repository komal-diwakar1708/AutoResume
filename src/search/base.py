"""
Abstract base class for all job searchers.
All sources must return a list of JobPosting instances.
"""

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class JobPosting:
    url: str
    title: str
    company: str
    location: str = ""
    description: str = ""
    source: str = ""
    posted_date: str = ""
    apply_url: str = ""
    recruiter_name: str = ""
    recruiter_email: str = ""
    match_score: float = 0.0

    @property
    def id(self) -> str:
        """Stable ID derived from the URL."""
        return hashlib.md5(self.url.encode()).hexdigest()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "url": self.url,
            "title": self.title,
            "company": self.company,
            "location": self.location,
            "description": self.description,
            "source": self.source,
            "posted_date": self.posted_date,
            "apply_url": self.apply_url or self.url,
            "recruiter_name": self.recruiter_name,
            "recruiter_email": self.recruiter_email,
            "match_score": self.match_score,
        }


class BaseSearcher(ABC):
    """All job board searchers inherit from this."""

    source_name: str = "unknown"

    def __init__(self, config: dict):
        self.config = config
        self.job_title: str = config.get("job_title", "Product Manager")
        self.alt_titles: list[str] = config.get("alt_titles", [])
        self.locations: list[str] = config.get("locations", [])
        self.max_results: int = config.get("max_results_per_source", 50)

    @abstractmethod
    def search(self, title: str, location: str) -> list[JobPosting]:
        """Search for jobs and return a list of JobPosting objects."""

    def search_all(self) -> list[JobPosting]:
        """Search for the main title + all alt titles across all locations."""
        results: list[JobPosting] = []
        titles = [self.job_title] + self.alt_titles

        for location in self.locations:
            for title in titles:
                try:
                    postings = self.search(title, location)
                    results.extend(postings)
                except Exception as exc:
                    import logging
                    logging.getLogger(__name__).warning(
                        "[%s] search('%s', '%s') failed: %s",
                        self.source_name, title, location, exc
                    )

        # Deduplicate by URL
        seen: set[str] = set()
        unique: list[JobPosting] = []
        for p in results:
            if p.url not in seen:
                seen.add(p.url)
                unique.append(p)

        return unique[: self.max_results]
