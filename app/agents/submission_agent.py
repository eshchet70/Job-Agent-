"""
Submission Agent — opens an application form and pre-fills it. It never submits.

Supported ATS portals (auto-detected from URL):
  • Ashby      jobs.ashbyhq.com
  • Greenhouse boards.greenhouse.io / job-boards.greenhouse.io
  • Lever      jobs.lever.co

Profile data is loaded from:
  data/candidate_profile.json    (name, email, location)
  data/submission_profile.json   (phone, linkedin, work_authorization, cover letter)

What it does: opens the posting in a visible browser window, fills the
standard contact fields, attaches the tailored resume, takes a screenshot,
and then leaves the window open. The candidate answers the employer's own
questions (work authorization, EEO, screening questions), checks everything,
and clicks Submit herself. There is no code path here that clicks Submit.

It runs as an ordinary browser: no disguised user agent, no CAPTCHA or
bot-check workarounds. If a site blocks automated browsers, apply by hand.

Usage:
    agent = SubmissionAgent()
    result = agent.prefill(
        url="https://jobs.ashbyhq.com/cohere/41cb2a12-...",
        resume_path=Path("data/tailored/Cohere_TPM/resume.docx"),
        company="Cohere",
        title="Technical Program Manager, AI Delivery",
    )
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

log = logging.getLogger("submission_agent")

ROOT = Path(__file__).resolve().parent.parent.parent
CANDIDATE_PROFILE_PATH = ROOT / "data" / "candidate_profile.json"
SUBMISSION_PROFILE_PATH = ROOT / "data" / "submission_profile.json"
SCREENSHOTS_DIR = ROOT / "data" / "submissions" / "screenshots"


# ─────────────────────────────────────────────────────────────────────────────
# Profile
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class CandidateSubmissionProfile:
    """Contact & authorization data used to fill ATS forms."""
    name: str = ""
    email: str = ""
    phone: str = ""
    linkedin_url: str = ""
    location: str = ""
    work_authorization: str = ""          # e.g. "Canadian Citizen - No sponsorship required"
    willing_to_relocate: bool = False
    salary_expectation: str = ""          # e.g. "$180,000 - $220,000 CAD"
    cover_letter_template: str = ""       # Optional; {company} / {title} are interpolated

    @classmethod
    def load(cls) -> "CandidateSubmissionProfile":
        profile = cls()

        # Base from candidate_profile.json (name, email, location)
        if CANDIDATE_PROFILE_PATH.exists():
            cp = json.loads(CANDIDATE_PROFILE_PATH.read_text(encoding="utf-8"))
            profile.name = cp.get("name", "")
            profile.email = cp.get("email", "")
            profile.location = cp.get("location", "")

        # Submission-specific overrides from submission_profile.json
        if SUBMISSION_PROFILE_PATH.exists():
            sp = json.loads(SUBMISSION_PROFILE_PATH.read_text(encoding="utf-8"))
            profile.phone = sp.get("phone", profile.phone)
            profile.linkedin_url = sp.get("linkedin_url", profile.linkedin_url)
            profile.work_authorization = sp.get("work_authorization", profile.work_authorization)
            profile.willing_to_relocate = sp.get("willing_to_relocate", profile.willing_to_relocate)
            profile.salary_expectation = sp.get("salary_expectation", profile.salary_expectation)
            profile.cover_letter_template = sp.get("cover_letter_template", profile.cover_letter_template)
            # Allow overriding base fields
            if sp.get("name"):
                profile.name = sp["name"]
            if sp.get("email"):
                profile.email = sp["email"]

        return profile

    def cover_letter(self, company: str, title: str) -> str:
        if not self.cover_letter_template:
            return ""
        return self.cover_letter_template.format(
            company=company, title=title,
            name=self.name, location=self.location,
        )


# ─────────────────────────────────────────────────────────────────────────────
# ATS Detection
# ─────────────────────────────────────────────────────────────────────────────

def detect_ats(url: str) -> str:
    """Return 'ashby' | 'greenhouse' | 'lever' | 'unknown' based on URL."""
    url_lower = url.lower()
    if "ashbyhq.com" in url_lower:
        return "ashby"
    if "greenhouse.io" in url_lower or "greenhouse" in url_lower:
        return "greenhouse"
    if "lever.co" in url_lower:
        return "lever"
    if "workday" in url_lower:
        return "workday"
    return "unknown"


# ─────────────────────────────────────────────────────────────────────────────
# ATS-specific form fillers
# ─────────────────────────────────────────────────────────────────────────────

def application_url(url: str, ats: str) -> str:
    """The page that actually shows the form (Ashby and Lever keep it on a sub-page)."""
    base = url.split("?")[0].rstrip("/")
    if ats == "ashby" and not base.endswith("/application"):
        return base + "/application"
    if ats == "lever" and not base.endswith("/apply"):
        return base + "/apply"
    return url


def is_placeholder(value: str) -> bool:
    """Template values that were never filled in, e.g. '.../in/YOUR_LINKEDIN_HANDLE/'."""
    v = (value or "").strip()
    return not v or "YOUR_" in v.upper() or v.lower() in ("todo", "tbd", "n/a")


class _AshbyFiller:
    """Fill the standard fields of an Ashby application form."""

    SELECTORS: dict[str, Optional[str]] = {
        "first_name":    'input[name="name.first"], input[placeholder*="First"]',
        "last_name":     'input[name="name.last"], input[placeholder*="Last"]',
        "full_name":     'input[name="_systemfield_name"], input[name="name"]',
        "email":         'input[name="_systemfield_email"], input[name="email"], input[type="email"]',
        "phone":         'input[name="phone"], input[type="tel"]',
        "linkedin":      'input[name*="linkedin" i], input[placeholder*="LinkedIn" i]',
        "resume_upload": 'input[type="file"]',
        "location":      'input[name*="location" i], input[placeholder*="Location" i]',
        "cover_letter":  'textarea[name*="cover" i], textarea[placeholder*="cover" i]',
    }

    def fill(self, page, profile: CandidateSubmissionProfile,
             resume_path: Path, company: str, title: str) -> dict:
        result: dict = {"fields_filled": [], "fields_skipped": [], "screenshot": None}

        first, _, last = profile.name.partition(" ")

        def try_fill(label: str, value: str) -> bool:
            selector = self.SELECTORS.get(label)
            if not selector:
                return False
            if is_placeholder(value):
                result["fields_skipped"].append(f"{label} (no value in your profile)")
                return False
            try:
                el = page.locator(selector).first
                if el.is_visible(timeout=2000):
                    el.fill(value)
                    result["fields_filled"].append(label)
                    return True
                result["fields_skipped"].append(f"{label} (field not found)")
            except Exception:
                result["fields_skipped"].append(f"{label} (field not found)")
            return False

        # Name: either separate first/last fields or one full-name field.
        if not (try_fill("first_name", first) and try_fill("last_name", last)):
            if try_fill("full_name", profile.name):
                result["fields_skipped"] = [f for f in result["fields_skipped"]
                                            if not f.startswith(("first_name", "last_name"))]
        try_fill("email", profile.email)
        try_fill("phone", profile.phone)
        try_fill("linkedin", profile.linkedin_url)
        try_fill("location", profile.location)
        try_fill("cover_letter", profile.cover_letter(company, title))

        # Attach the resume
        try:
            upload = page.locator(self.SELECTORS["resume_upload"]).first
            upload.set_input_files(str(resume_path), timeout=5000)
            result["fields_filled"].append("resume_upload")
        except Exception:
            result["fields_skipped"].append("resume_upload (upload field not found)")

        SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^\w]", "_", f"{company}_{title}")[:60]
        screenshot_path = SCREENSHOTS_DIR / f"{safe}_prefill.png"
        try:
            page.screenshot(path=str(screenshot_path), full_page=True)
            result["screenshot"] = str(screenshot_path)
        except Exception:
            pass
        return result


class _GreenhouseFiller(_AshbyFiller):
    SELECTORS = {
        "first_name":    '#first_name',
        "last_name":     '#last_name',
        "full_name":     None,
        "email":         '#email',
        "phone":         '#phone',
        "linkedin":      'input[id*="linkedin" i], input[aria-label*="LinkedIn" i]',
        "resume_upload": '#resume, input[type="file"]',
        "location":      '#job_application_location, #candidate-location',
        "cover_letter":  '#cover_letter_text, textarea[id*="cover" i]',
    }


class _LeverFiller(_AshbyFiller):
    SELECTORS = {
        "first_name":    None,                   # Lever uses one full-name field
        "last_name":     None,
        "full_name":     'input[name="name"]',
        "email":         'input[name="email"]',
        "phone":         'input[name="phone"]',
        "linkedin":      'input[name*="LinkedIn" i]',
        "resume_upload": 'input[type="file"]',
        "location":      'input[name*="location" i]',
        "cover_letter":  'textarea[name*="comments" i], textarea[name*="additional" i]',
    }


FILLERS = {"ashby": _AshbyFiller, "greenhouse": _GreenhouseFiller, "lever": _LeverFiller}


# ─────────────────────────────────────────────────────────────────────────────
# Main Submission Agent
# ─────────────────────────────────────────────────────────────────────────────

class SubmissionAgent:
    """
    Opens an application form in a visible browser and pre-fills it.
    The candidate reviews it and clicks Submit herself.

    Requires: playwright Python package + browser installed.
    Install:  pip install playwright && playwright install chromium
    """

    def __init__(self):
        self.profile = CandidateSubmissionProfile.load()

    def is_available(self) -> tuple[bool, str]:
        """Check that Playwright is installed (does not open a browser)."""
        try:
            import playwright.sync_api  # noqa: F401
            return True, "OK"
        except ImportError:
            return False, "Playwright not installed. Run: pip install playwright && playwright install chromium"

    def profile_gaps(self) -> list[str]:
        """Profile values that are missing or still template placeholders."""
        checks = {"name": self.profile.name, "email": self.profile.email,
                  "phone": self.profile.phone, "LinkedIn URL": self.profile.linkedin_url}
        return [label for label, value in checks.items() if is_placeholder(value)]

    def prefill(
        self,
        url: str,
        resume_path: Path,
        company: str,
        title: str,
        keep_open: bool = True,
        headless: bool = False,
        max_wait_minutes: int = 45,
    ) -> dict:
        """
        Open the application form, fill the standard fields and attach the resume.
        Nothing is submitted.

        Args:
            keep_open:        Leave the window open so the candidate can finish the
                              form and submit it herself. The call returns when she
                              closes the window (or after max_wait_minutes).
            headless:         Run without a visible window (tests only; implies the
                              window is not kept open).

        Returns:
            dict with keys: success (form opened and filled), ats, fields_filled,
            fields_skipped, screenshot, confirmation, error
        """
        available, msg = self.is_available()
        if not available:
            return {"success": False, "error": msg}

        resume_path = Path(resume_path)
        if not resume_path.exists():
            return {"success": False, "error": f"Resume file not found: {resume_path}"}

        ats = detect_ats(url)
        filler_cls = FILLERS.get(ats)
        if filler_cls is None:
            return {
                "success": False,
                "ats": ats,
                "error": (
                    f"Pre-fill is not supported for this site ({ats}). "
                    "Supported: Ashby, Greenhouse, Lever. Please apply on the posting directly."
                ),
            }

        log.info("Pre-filling %s application via %s", company, ats)

        def drive_browser() -> dict:
            from playwright.sync_api import TimeoutError as PlaywrightTimeout
            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                browser = p.chromium.launch(headless=headless)
                page = browser.new_context(viewport={"width": 1280, "height": 900}).new_page()
                page.goto(application_url(url, ats), wait_until="domcontentloaded", timeout=45000)
                try:
                    page.wait_for_load_state("networkidle", timeout=15000)
                except PlaywrightTimeout:
                    pass  # some ATS pages keep polling; the form is usually ready anyway

                result = filler_cls().fill(page=page, profile=self.profile, resume_path=resume_path,
                                           company=company, title=title)

                if keep_open and not headless:
                    try:
                        page.wait_for_event("close", timeout=max_wait_minutes * 60 * 1000)
                    except Exception:
                        pass  # waited the maximum time, or the window was already closed
                try:
                    browser.close()
                except Exception:
                    pass
            return result

        try:
            # Playwright's sync API cannot run in a thread that already has an event
            # loop (some app hosts do), so the browser always gets its own thread.
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=1) as pool:
                result = pool.submit(drive_browser).result()

            result["ats"] = ats
            result["success"] = bool(result.get("fields_filled"))
            if result["success"]:
                result["confirmation"] = (
                    f"Form pre-filled for {company} — {title}: "
                    f"{', '.join(result['fields_filled'])}. Nothing was submitted."
                )
            else:
                result["error"] = ("The page opened but no form fields were recognised. "
                                   "The site layout may have changed; please apply on the posting directly.")
            return result

        except Exception as exc:
            log.error("Pre-fill failed: %s", exc, exc_info=True)
            return {"success": False, "ats": ats, "error": str(exc)[:400]}

    def prefill_preview(self, url: str, resume_path: Path, company: str, title: str) -> dict:
        """Fill the form, take a screenshot and close the window straight away."""
        return self.prefill(url, resume_path, company, title, keep_open=False)
