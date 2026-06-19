"""
Job filter and scorer.

For each JobPosting:
  1. Compute a match score (0.0–1.0) based on title similarity and skill keyword density
  2. Apply hard filters: location, visa sponsorship, min score threshold
  3. Deduplicate against jobs already stored in the DB
"""

import logging
import re
from typing import Optional

from .base import JobPosting
from src.db import tracker

logger = logging.getLogger(__name__)


def _normalise(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", " ", text.lower())


def _is_excluded_title(posting_title: str, exclude_keywords: list[str]) -> bool:
    """Return True if the title contains any excluded keyword (e.g. 'Senior', 'Director')."""
    pt_lower = posting_title.lower()
    return any(kw.lower() in pt_lower for kw in exclude_keywords)


def _score_title(posting_title: str, target_title: str, alt_titles: list[str]) -> float:
    """Score 0.0–0.5 based on how well the job title matches our targets."""
    pt = _normalise(posting_title)
    all_targets = [_normalise(t) for t in [target_title] + alt_titles]

    for target in all_targets:
        if target in pt or pt in target:
            return 0.5
        # Partial word overlap
        target_words = set(target.split())
        pt_words = set(pt.split())
        overlap = len(target_words & pt_words) / max(len(target_words), 1)
        if overlap >= 0.5:
            return round(overlap * 0.5, 2)

    return 0.0


def _score_skills(description: str, skills: list[str]) -> float:
    """Score 0.0–0.5 based on how many skills appear in the job description."""
    if not description or not skills:
        return 0.0
    desc = _normalise(description)
    matched = sum(1 for skill in skills if _normalise(skill) in desc)
    return round(min(matched / len(skills), 1.0) * 0.5, 2)


def _matches_location(posting_location: str, target_locations: list[str]) -> bool:
    """Return True if the posting location matches any of our target locations."""
    if not target_locations:
        return True
    pl = _normalise(posting_location)
    for loc in target_locations:
        if _normalise(loc) in pl or pl in _normalise(loc):
            return True
    return False


def _has_visa_sponsorship(description: str) -> bool:
    keywords = ["visa sponsorship", "work permit", "relocation", "sponsor", "work authorization"]
    desc = description.lower()
    return any(kw in desc for kw in keywords)


def filter_and_score(
    postings: list[JobPosting],
    config: dict,
) -> list[JobPosting]:
    """
    Score and filter a list of JobPosting objects.
    Returns only postings that pass all filters, sorted by match_score desc.
    """
    target_title: str = config.get("job_title", "Product Manager")
    alt_titles: list[str] = config.get("alt_titles", [])
    exclude_keywords: list[str] = config.get("exclude_title_keywords", [])
    skills: list[str] = config.get("skills", [])
    locations: list[str] = config.get("locations", [])
    min_score: float = config.get("min_match_score", 0.3)
    visa_required: bool = config.get("visa_sponsorship_required", False)

    filtered: list[JobPosting] = []

    for p in postings:
        # --- Dedup against DB ---
        if tracker.job_exists(p.url):
            logger.debug("Already tracked: %s @ %s — skipping", p.title, p.company)
            continue

        # --- Exclude unwanted seniority / title keywords ---
        if exclude_keywords and _is_excluded_title(p.title, exclude_keywords):
            logger.debug("Excluded title '%s' (matched exclusion keyword)", p.title)
            continue

        # --- Location filter ---
        if locations and not _matches_location(p.location, locations):
            logger.debug("Location mismatch: '%s' not in targets", p.location)
            continue

        # --- Visa sponsorship filter ---
        if visa_required and not _has_visa_sponsorship(p.description):
            logger.debug("No visa mention: %s @ %s", p.title, p.company)
            continue

        # --- Scoring ---
        title_score = _score_title(p.title, target_title, alt_titles)
        skill_score = _score_skills(p.description, skills)
        total_score = round(title_score + skill_score, 2)
        p.match_score = total_score

        if total_score < min_score:
            logger.debug("Score too low (%.2f): %s @ %s", total_score, p.title, p.company)
            continue

        filtered.append(p)

    filtered.sort(key=lambda x: x.match_score, reverse=True)
    logger.info("Filtered %d → %d jobs after scoring (min=%.2f)", len(postings), len(filtered), min_score)
    return filtered
