"""
Submission agent tests: it must fill the form and never submit it.

The browser tests run against local HTML fixtures that use each ATS's field
names. They are skipped when Playwright or its Chromium build is not installed.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.agents import submission_agent as sa
from app.agents.submission_agent import (
    CandidateSubmissionProfile, SubmissionAgent, application_url, detect_ats, is_placeholder,
)

PROFILE = CandidateSubmissionProfile(
    name="Elena Test", email="elena@example.com", phone="555-0100",
    linkedin_url="https://www.linkedin.com/in/YOUR_LINKEDIN_HANDLE/", location="Toronto, ON",
)

# Each form flags itself if anything submits it.
_TAIL = """<input type="file" id="resume" name="resume">
<button type="submit" id="submit_app">Submit Application</button></form>
<script>window.__submitted=false;
document.getElementById('f').addEventListener('submit',e=>{e.preventDefault();window.__submitted=true;});</script>"""
GREENHOUSE = f"""<form id="f"><input id="first_name"><input id="last_name"><input id="email">
<input id="phone"><input id="question_linkedin" aria-label="LinkedIn Profile">
<input id="candidate-location"><select id="work_auth"><option>Select...</option></select>{_TAIL}"""
LEVER = f"""<form id="f"><input name="name"><input name="email"><input name="phone">
<input name="urls[LinkedIn]"><textarea name="comments"></textarea>{_TAIL}"""
ASHBY = f"""<form id="f"><input name="_systemfield_name"><input name="_systemfield_email" type="email">
<input type="tel" name="phone"><input placeholder="LinkedIn URL">{_TAIL}"""


def test_helpers():
    assert detect_ats("https://jobs.ashbyhq.com/cohere/abc") == "ashby"
    assert application_url("https://jobs.ashbyhq.com/cohere/abc?utm=1", "ashby").endswith("/abc/application")
    assert application_url("https://jobs.lever.co/acme/1/apply", "lever").endswith("/1/apply")
    assert application_url("https://job-boards.greenhouse.io/okta/jobs/1", "greenhouse").endswith("/jobs/1")
    assert is_placeholder("https://www.linkedin.com/in/YOUR_LINKEDIN_HANDLE/") and is_placeholder("")
    assert not is_placeholder("https://www.linkedin.com/in/someone/")


def test_no_code_path_clicks_or_disguises_the_browser():
    source = Path(sa.__file__).read_text(encoding="utf-8")
    assert ".click(" not in source and "user_agent" not in source


def test_unsupported_site_and_missing_resume(tmp_path):
    agent = SubmissionAgent()
    resume = tmp_path / "r.docx"
    resume.write_bytes(b"x")
    out = agent.prefill("https://acme.wd5.myworkdayjobs.com/job/1", resume, "Acme", "TPM", headless=True)
    assert out["success"] is False and "not supported" in out["error"]
    out = agent.prefill("https://jobs.lever.co/acme/1", tmp_path / "missing.docx", "Acme", "TPM")
    assert out["success"] is False and "not found" in out["error"]


def test_profile_gaps_reports_placeholders():
    agent = SubmissionAgent()
    agent.profile = PROFILE
    assert agent.profile_gaps() == ["LinkedIn URL"]


@pytest.fixture(scope="module")
def browser():
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as p:
        try:
            b = p.chromium.launch(headless=True)
        except Exception as exc:  # browser build not installed
            pytest.skip(f"Chromium not available: {exc}")
        yield b
        b.close()


@pytest.mark.parametrize("html,filler,name_fields", [
    (GREENHOUSE, sa._GreenhouseFiller, ["first_name", "last_name"]),
    (LEVER, sa._LeverFiller, ["full_name"]),
    (ASHBY, sa._AshbyFiller, ["full_name"]),
])
def test_fills_standard_fields_and_never_submits(browser, tmp_path, monkeypatch, html, filler, name_fields):
    monkeypatch.setattr(sa, "SCREENSHOTS_DIR", tmp_path / "shots")
    resume = tmp_path / "resume.docx"
    resume.write_bytes(b"resume")
    page = browser.new_page()
    page.set_content(html)
    result = filler().fill(page=page, profile=PROFILE, resume_path=resume, company="Acme", title="TPM")

    for field in name_fields + ["email", "phone", "resume_upload"]:
        assert field in result["fields_filled"], result
    # The template LinkedIn URL is left blank rather than typed into the form.
    assert "linkedin" not in result["fields_filled"]
    assert any(s.startswith("linkedin") for s in result["fields_skipped"])
    assert page.evaluate("document.querySelector('input[type=file]').files.length") == 1
    assert page.evaluate("window.__submitted") is False
    assert Path(result["screenshot"]).exists()
    page.close()


def test_prefill_end_to_end_leaves_form_unsubmitted(tmp_path, monkeypatch, browser):
    """Whole flow against a local page whose path looks like a Greenhouse URL."""
    monkeypatch.setattr(sa, "SCREENSHOTS_DIR", tmp_path / "shots")
    form = tmp_path / "boards.greenhouse.io" / "acme" / "jobs" / "1.html"
    form.parent.mkdir(parents=True)
    form.write_text(GREENHOUSE, encoding="utf-8")
    resume = tmp_path / "resume.docx"
    resume.write_bytes(b"resume")
    agent = SubmissionAgent()
    agent.profile = PROFILE
    out = agent.prefill(form.as_uri(), resume, "Acme", "TPM", headless=True)
    assert out["success"] and out["ats"] == "greenhouse"
    assert "Nothing was submitted" in out["confirmation"] and "submitted" not in out
