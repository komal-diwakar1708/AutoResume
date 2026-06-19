"""
Recruiter email finder.

Strategy (in order of preference):
  1. Hunter.io Domain Search API — finds HR/recruiting emails at a company domain
  2. Parse email directly from the job description text
  3. Return None if no email found
"""

import logging
import os
import re
from typing import Optional
from urllib.parse import urlparse

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

HUNTER_SEARCH_URL = "https://api.hunter.io/v2/domain-search"
HUNTER_FIND_URL = "https://api.hunter.io/v2/email-finder"

# Job titles likely to receive applications
RECRUITER_TITLES = [
    "recruiter",
    "talent acquisition",
    "hr",
    "human resources",
    "hiring",
    "people",
    "talent",
]


def find_recruiter_email(job: dict) -> Optional[str]:
    """
    Attempt to find a recruiter email for the given job.

    Args:
        job: dict with at least 'company', 'url', and optionally 'description'

    Returns:
        email address string or None
    """
    # Try parsing email from job description first (free, instant)
    desc_email = _extract_from_description(job.get("description", ""))
    if desc_email:
        logger.info("Found email in job description: %s", desc_email)
        return desc_email

    # Hunter.io lookup
    domain = _extract_domain(job.get("url", ""), job.get("company", ""))
    if domain:
        email = _hunter_domain_search(domain)
        if email:
            return email

    logger.info("No recruiter email found for %s", job.get("company", "unknown"))
    return None


def _extract_from_description(description: str) -> Optional[str]:
    """Look for a direct email address in the job description."""
    if not description:
        return None
    pattern = r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"
    matches = re.findall(pattern, description)
    for match in matches:
        # Prefer HR/recruiting-looking emails
        lower = match.lower()
        if any(kw in lower for kw in ["recruit", "hr", "talent", "hiring", "people", "career", "jobs"]):
            return match
    # Return first found email if no recruiting-specific one
    return matches[0] if matches else None


def _extract_domain(job_url: str, company_name: str) -> Optional[str]:
    """Extract the company's domain from the job URL or company name."""
    if job_url:
        try:
            parsed = urlparse(job_url)
            hostname = parsed.netloc.lower()
            # Skip job board domains — we want the company's own domain
            skip_domains = {
                "linkedin.com", "indeed.com", "glassdoor.com", "seek.com.au",
                "seek.co.nz", "stepstone.de", "monster.com", "ziprecruiter.com",
                "wellfound.com", "lever.co", "greenhouse.io", "workday.com",
                "taleo.net", "icims.com", "jobvite.com", "smartrecruiters.com",
                "myworkday.com", "jobs.de", "xing.com",
            }
            for skip in skip_domains:
                if skip in hostname:
                    return None
            # Remove www.
            domain = re.sub(r"^www\.", "", hostname)
            if "." in domain:
                return domain
        except Exception:
            pass
    return None


@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=8))
def _hunter_domain_search(domain: str) -> Optional[str]:
    """Search Hunter.io for recruiter emails at a given domain."""
    api_key = os.getenv("HUNTER_API_KEY", "")
    if not api_key:
        logger.debug("HUNTER_API_KEY not set — skipping Hunter.io lookup")
        return None

    try:
        params = {
            "domain": domain,
            "api_key": api_key,
            "limit": 10,
        }
        with httpx.Client(timeout=15) as client:
            resp = client.get(HUNTER_SEARCH_URL, params=params)
            resp.raise_for_status()
            data = resp.json()

        emails = data.get("data", {}).get("emails", [])
        if not emails:
            return None

        # Sort: prefer recruiting/HR-titled emails
        def recruiter_priority(e: dict) -> int:
            title = (e.get("position") or e.get("title") or "").lower()
            return -sum(1 for kw in RECRUITER_TITLES if kw in title)

        emails.sort(key=recruiter_priority)
        best = emails[0]
        email_addr = best.get("value", "")
        if email_addr:
            logger.info("Hunter.io found: %s (%s) at %s", email_addr, best.get("position", ""), domain)
            return email_addr

    except Exception as exc:
        logger.warning("Hunter.io lookup failed for %s: %s", domain, exc)

    return None
