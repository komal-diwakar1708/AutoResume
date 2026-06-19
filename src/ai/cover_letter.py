"""
Cover letter generator — template-based (OpenAI disabled).

Generates a professional, personalised-looking cover letter using
config data (name, skills, experience, location) without any API calls.

To re-enable OpenAI, uncomment the block marked OPENAI_BLOCK below and
set OPENAI_API_KEY in your .env file.
"""

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ── OPENAI_BLOCK (disabled) ────────────────────────────────────────────────
# import os
# from openai import OpenAI
#
# def _generate_with_openai(job_title, company, job_description, config) -> Optional[str]:
#     api_key = os.getenv("OPENAI_API_KEY", "")
#     if not api_key:
#         return None
#     resume_text = _extract_resume_text(config.get("resume_path", "resume/resume.pdf"))
#     personal = config.get("personal", {})
#     full_name = f"{personal.get('first_name','')} {personal.get('last_name','')}".strip()
#     years_exp = personal.get("years_of_experience", "")
#     desc_snippet = job_description[:3000] if job_description else "Not provided"
#     resume_snippet = resume_text[:3000] if resume_text else "Not provided"
#     prompt = f"""You are a professional career coach helping a candidate apply for a job.
# Write a compelling, concise cover letter (150–200 words) tailored to this specific role.
# Candidate Name: {full_name}
# Years of Experience: {years_exp}
# Resume Summary:
# {resume_snippet}
# Target Role: {job_title} at {company}
# Job Description Excerpt:
# {desc_snippet}
# Instructions:
# - Address it "Dear Hiring Team,"
# - Highlight 2–3 specific skills from the resume that match the job
# - Mention the company name naturally
# - End with a call to action
# - Do NOT use buzzwords or clichés
# - Plain text only, no markdown or bullet points
# - Sign off with the candidate's full name
# """
#     try:
#         client = OpenAI(api_key=api_key)
#         response = client.chat.completions.create(
#             model="gpt-4o",
#             messages=[{"role": "user", "content": prompt}],
#             max_tokens=400,
#             temperature=0.7,
#         )
#         letter = response.choices[0].message.content.strip()
#         logger.info("OpenAI cover letter generated for %s @ %s", job_title, company)
#         return letter
#     except Exception as exc:
#         logger.error("OpenAI API error: %s — falling back to template", exc)
#         return None
# ── END OPENAI_BLOCK ───────────────────────────────────────────────────────


def generate_cover_letter(
    job_title: str,
    company: str,
    job_description: str,
    config: dict,
) -> str:
    """
    Generate a cover letter for a specific job.
    Currently uses the template generator only (OpenAI disabled).
    """
    # Uncomment the two lines below to re-enable OpenAI:
    # letter = _generate_with_openai(job_title, company, job_description, config)
    # if letter:
    #     return letter

    return _template_cover_letter(job_title, company, job_description, config)


def _template_cover_letter(
    job_title: str,
    company: str,
    job_description: str,
    config: dict,
) -> str:
    """
    Builds a professional cover letter from config data.
    Picks skills that actually appear in the job description for relevance.
    """
    personal = config.get("personal", {})
    first_name = personal.get("first_name", "")
    last_name = personal.get("last_name", "")
    full_name = f"{first_name} {last_name}".strip()
    years_exp = personal.get("years_of_experience", "several")
    location = personal.get("current_location", "")
    linkedin_url = personal.get("linkedin_url", "")

    all_skills: list[str] = config.get("skills", [])
    jd_lower = job_description.lower() if job_description else ""

    # Prefer skills that appear in the job description; fall back to top 4
    matched_skills = [s for s in all_skills if s.lower() in jd_lower]
    highlight_skills = matched_skills[:3] if matched_skills else all_skills[:3]

    if len(highlight_skills) >= 2:
        skills_str = ", ".join(highlight_skills[:-1]) + f" and {highlight_skills[-1]}"
    elif highlight_skills:
        skills_str = highlight_skills[0]
    else:
        skills_str = "product strategy, agile delivery and stakeholder management"

    # Pick an achievement sentence based on years of experience
    if isinstance(years_exp, int) and years_exp >= 5:
        achievement = (
            f"Over the past {years_exp} years I have led cross-functional teams to ship "
            "products that drove measurable growth — from defining roadmaps and running "
            "discovery sprints to coordinating go-to-market launches."
        )
    else:
        achievement = (
            "I have built a strong foundation in end-to-end product delivery — "
            "from writing PRDs and running user research to coordinating releases "
            "with engineering and design teams."
        )

    linkedin_line = (
        f"You can view my profile and portfolio at {linkedin_url}.\n\n" if linkedin_url else ""
    )

    letter = f"""Dear Hiring Team,

I am writing to express my keen interest in the {job_title} role at {company}. \
With {years_exp} years of experience, I bring hands-on expertise in \
{skills_str}.

{achievement}

What draws me to {company} specifically is the opportunity to work on meaningful, \
user-centric products within a collaborative environment. I am confident that my \
background in driving alignment between business goals and customer needs would let me \
contribute quickly and effectively to your team.

{linkedin_line}\
I have attached my resume for your review and would love the opportunity to discuss \
how I can add value to {company}. Thank you for your time and consideration.

Sincerely,
{full_name}"""

    logger.info("Template cover letter generated for %s @ %s", job_title, company)
    return letter
