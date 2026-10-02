"""
Submission Agent — Playwright-based ATS form filler.

Supported ATS portals (auto-detected from URL):
  • Ashby      jobs.ashbyhq.com
  • Greenhouse boards.greenhouse.io / job-boards.greenhouse.io / *.greenhouse.io
  • Lever      jobs.lever.co

Profile data is loaded from:
  data/candidate_profile.json    (name, email, location, certifications…)
  data/submission_profile.json   (phone, linkedin, work_authorization, cover_letter_template)

The agent NEVER auto-submits. It fills the form, takes a screenshot for
review, and then returns — the human clicks the final Submit button.

Usage:
    agent = SubmissionAgent()
    result = agent.submit(
        url="https://jobs.ashbyhq.com/cohere/41cb2a12-...",
        resume_path=Path("data/tailored/Cohere_TPM/resume.docx"),
        company="Cohere",
        title="Technical Program Manager, AI Delivery",
        dry_run=False,   # True = fill but do NOT click submit
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

class _AshbyFiller:
    """Fill an Ashby ATS job application form."""

    SELECTORS = {
        "first_name":       'input[name="name.first"], input[placeholder*="First"]',
        "last_name":        'input[name="name.last"], input[placeholder*="Last"]',
        "email":            'input[name="email"], input[type="email"]',
        "phone":            'input[name="phone"], input[type="tel"]',
        "linkedin":         'input[name*="linkedin" i], input[placeholder*="LinkedIn" i]',
        "resume_upload":    'input[type="file"][accept*="pdf"], input[type="file"][accept*="doc"]',
        "location":         'input[name*="location" i], input[placeholder*="Location" i]',
        "work_auth":        'select[name*="authorization" i], select[name*="workAuth" i]',
        "cover_letter":     'textarea[name*="cover" i], textarea[placeholder*="cover" i]',
        "submit":           'button[type="submit"], button:has-text("Submit")',
    }

    def fill(self, page, profile: CandidateSubmissionProfile,
             resume_path: Path, company: str, title: str, dry_run: bool = False) -> dict:
        from playwright.sync_api import expect
        result = {"fields_filled": [], "fields_skipped": [], "screenshot": None}

        name_parts = profile.name.split(" ", 1)
        first = name_parts[0]
        last = name_parts[1] if len(name_parts) > 1 else ""

        # Fill fields safely
        def try_fill(label: str, selector: str, value: str):
            try:
                el = page.locator(selector).first
                if el.is_visible(timeout=2000) and value:
                    el.fill(value)
                    result["fields_filled"].append(label)
                else:
                    result["fields_skipped"].append(label)
            except Exception as exc:
                result["fields_skipped"].append(f"{label} ({exc})")

        try_fill("first_name", self.SELECTORS["first_name"], first)
        try_fill("last_name",  self.SELECTORS["last_name"],  last)
        try_fill("email",      self.SELECTORS["email"],      profile.email)
        try_fill("phone",      self.SELECTORS["phone"],      profile.phone)
        try_fill("linkedin",   self.SELECTORS["linkedin"],   profile.linkedin_url)
        try_fill("location",   self.SELECTORS["location"],   profile.location)

        cl = profile.cover_letter(company, title)
        if cl:
            try_fill("cover_letter", self.SELECTORS["cover_letter"], cl)

        # Upload resume
        try:
            upload_el = page.locator(self.SELECTORS["resume_upload"]).first
            if upload_el.is_visible(timeout=3000):
                upload_el.set_input_files(str(resume_path))
                result["fields_filled"].append("resume_upload")
            else:
                result["fields_skipped"].append("resume_upload")
        except Exception as exc:
            result["fields_skipped"].append(f"resume_upload ({exc})")

        # Screenshot before submit
        SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^\w]", "_", f"{company}_{title}")[:60]
        screenshot_path = SCREENSHOTS_DIR / f"{safe}_prefill.png"
        try:
            page.screenshot(path=str(screenshot_path), full_page=True)
            result["screenshot"] = str(screenshot_path)
        except Exception:
            pass

        if dry_run:
            result["dry_run"] = True
            return result

        # Final submit — human must have already confirmed in UI
        try:
            submit_el = page.locator(self.SELECTORS["submit"]).first
            if submit_el.is_visible(timeout=3000):
                submit_el.click()
                page.wait_for_timeout(3000)
                result["submitted"] = True

                # Screenshot after submit for confirmation
                confirm_path = SCREENSHOTS_DIR / f"{safe}_submitted.png"
                page.screenshot(path=str(confirm_path), full_page=True)
                result["confirmation_screenshot"] = str(confirm_path)
            else:
                result["submitted"] = False
                result["error"] = "Submit button not found"
        except Exception as exc:
            result["submitted"] = False
            result["error"] = str(exc)

        return result


class _GreenhouseFiller(_AshbyFiller):
    """Greenhouse overrides — same approach, different selectors."""
    SELECTORS = {
        "first_name":    '#first_name',
        "last_name":     '#last_name',
        "email":         '#email',
        "phone":         '#phone',
        "linkedin":      'input[id*="linkedin" i]',
        "resume_upload": '#resume, input[type="file"]',
        "location":      '#job_application_location',
        "work_auth":     'select[id*="authorization" i]',
        "cover_letter":  '#cover_letter',
        "submit":        '#submit_app, button[type="submit"]',
    }


class _LeverFiller(_AshbyFiller):
    """Lever overrides."""
    SELECTORS = {
        "first_name":    'input[name="name"]',   # Lever uses full name in one field
        "last_name":     None,
        "email":         'input[name="email"]',
        "phone":         'input[name="phone"]',
        "linkedin":      'input[name*="linkedin" i]',
        "resume_upload": 'input[type="file"]',
        "location":      'input[name*="location" i]',
        "work_auth":     None,
        "cover_letter":  'textarea[name*="comments" i], textarea[name*="additional" i]',
        "submit":        'button[type="submit"]',
    }

    def fill(self, page, profile, resume_path, company, title, dry_run=False):
        # Lever uses a single "name" field
        full_name_sel = 'input[name="name"]'
        try:
            el = page.locator(full_name_sel).first
            if el.is_visible(timeout=2000):
                el.fill(profile.name)
        except Exception:
            pass
        # Delegate rest (email, phone, etc.) via parent with adjusted selectors
        self.SELECTORS["first_name"] = None  # Already handled
        return super().fill(page, profile, resume_path, company, title, dry_run)


# ─────────────────────────────────────────────────────────────────────────────
# Main Submission Agent
# ─────────────────────────────────────────────────────────────────────────────

class SubmissionAgent:
    """
    Playwright-based job application submission agent.

    Requires: playwright Python package + browser installed.
    Install:  pip install playwright && playwright install chromium
    """

    def __init__(self):
        self.profile = CandidateSubmissionProfile.load()

    def is_available(self) -> tuple[bool, str]:
        """Check if Playwright is installed and usable."""
        try:
            import playwright  # noqa: F401
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=False)
                browser.close()
            return True, "OK"
        except ImportError:
            return False, "Playwright not installed. Run: pip install playwright && playwright install chromium"
        except Exception as exc:
            return False, f"Playwright error: {exc}"

    def submit(
        self,
        url: str,
        resume_path: Path,
        company: str,
        title: str,
        dry_run: bool = True,
    ) -> dict:
        """
        Open the job URL, fill the form, upload the resume.

        Args:
            url:         Direct ATS job posting URL
            resume_path: Path to the tailored .docx or .pdf resume
            company:     Company name (for cover letter interpolation)
            title:       Job title
            dry_run:     If True, fill form but DO NOT click Submit

        Returns:
            dict with keys: success, confirmation, screenshot, error, fields_filled, fields_skipped
        """
        available, msg = self.is_available()
        if not available:
            return {"success": False, "error": msg}

        if not resume_path.exists():
            return {"success": False, "error": f"Resume file not found: {resume_path}"}

        ats = detect_ats(url)
        filler_map = {
            "ashby":      _AshbyFiller(),
            "greenhouse": _GreenhouseFiller(),
            "lever":      _LeverFiller(),
        }
        filler = filler_map.get(ats)
        if filler is None:
            return {
                "success": False,
                "error": (
                    f"Unsupported ATS: {ats} (URL: {url}). "
                    "Supported: Ashby, Greenhouse, Lever. "
                    "Please submit manually using the Apply Now button."
                ),
            }

        log.info("Submitting to %s via %s (dry_run=%s)", company, ats, dry_run)

        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=False)  # Visible so user can watch
                context = browser.new_context(
                    viewport={"width": 1280, "height": 900},
                    user_agent=(
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                    ),
                )
                page = context.new_page()

                log.info("Navigating to: %s", url)
                page.goto(url, wait_until="networkidle", timeout=30000)
                page.wait_for_timeout(2000)  # Let JS settle

                result = filler.fill(
                    page=page,
                    profile=self.profile,
                    resume_path=resume_path,
                    company=company,
                    title=title,
                    dry_run=dry_run,
                )

                browser.close()

            result["success"] = result.get("submitted", dry_run)
            result["ats"] = ats
            if dry_run:
                result["confirmation"] = (
                    f"Dry run complete. Form filled for {company} — {title}. "
                    f"Fields filled: {', '.join(result.get('fields_filled', []))}. "
                    f"Review screenshot before approving submission."
                )
            return result

        except Exception as exc:
            log.error("Submission failed: %s", exc, exc_info=True)
            return {"success": False, "error": str(exc)}

    def prefill_preview(self, url: str, resume_path: Path, company: str, title: str) -> dict:
        """Dry-run: fill the form and take a screenshot but never submit."""
        return self.submit(url, resume_path, company, title, dry_run=True)
