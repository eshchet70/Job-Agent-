"""Tests for the interview agent's assessment call (fake client, no network)."""
from __future__ import annotations

import json
from types import SimpleNamespace as NS

import pytest

from app.agents import interview_agent as ia
from app.agents.interview_agent import InterviewAgent, InterviewRecord, verify_record

ASSESSMENT = {
    "overall_impression": "Strong recruiter screen.",
    "likelihood_to_proceed": "likely",
    "likelihood_rationale": "Clear match on portfolio governance.",
    "dimension_scores": {k: {"score": 7, "rationale": "ok"} for k in
                         ("communication", "technical_fit", "leadership_fit", "cultural_fit",
                          "candidate_preparedness")},
    "positive_signals": ["Asked about start date"], "concerning_signals": [], "neutral_signals": [],
    "gaps_identified": ["No Azure examples"], "strengths_demonstrated": ["Governance"],
    "follow_up_actions": ["Send thank-you note"], "next_round_prep": [], "thank_you_note_points": [],
    "process_stage": "After recruiter screen", "estimated_timeline": "1-2 weeks",
}


class FakeClient:
    def __init__(self, answer=None, error=None):
        self.answer, self.error, self.requests = answer, error, []
        self.messages = self

    def create(self, **kw):
        self.requests.append(kw)
        if self.error:
            raise self.error
        return NS(content=[NS(type="text", text=json.dumps(self.answer))], stop_reason="end_turn")


@pytest.fixture
def agent_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(ia, "INTERVIEWS_DIR", tmp_path)
    return tmp_path


def _record(agent: InterviewAgent) -> InterviewRecord:
    rec = agent.get_or_create("greenhouse:acme:1", "Acme", "Senior TPM", "https://x")
    agent.add_round(rec, {"round_type": "recruiter_screen", "date": "2026-10-01",
                          "interviewer_name": "Sam", "duration_minutes": 30,
                          "topics_covered": ["portfolio governance"],
                          "candidate_notes": "Went well; they asked about Bell TCO work in detail.",
                          "outcome": "passed"})
    return rec


def test_assessment_is_saved_and_request_is_valid_for_new_models(agent_dir):
    client = FakeClient(ASSESSMENT)
    agent = InterviewAgent(model="test", client=client)
    rec = _record(agent)
    out = agent.assess(rec, jd_text="Lead programs.")
    assert out["likelihood_to_proceed"] == "likely" and "_placeholder" not in out
    assert agent.load(rec.job_id).last_assessment == ASSESSMENT
    req = client.requests[0]
    # Forced tool calls, manual thinking and custom temperature are rejected by current models.
    for banned in ("tool_choice", "tools", "thinking", "temperature"):
        assert banned not in req
    assert req["output_config"]["format"]["type"] == "json_schema"


def test_api_failure_is_reported_and_not_cached(agent_dir):
    agent = InterviewAgent(model="test", client=FakeClient(error=RuntimeError("400 bad request")))
    rec = _record(agent)
    out = agent.assess(rec)
    assert out["_placeholder"] and "400 bad request" in out["_error"]
    assert agent.load(rec.job_id).last_assessment is None


def test_missing_key_says_so(agent_dir, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    agent = InterviewAgent(model="test")
    out = agent.assess(_record(agent))
    assert out["_placeholder"] and "ANTHROPIC_API_KEY" in out["_error"]


def test_verify_flags_missing_details(agent_dir):
    agent = InterviewAgent(model="test", client=FakeClient(ASSESSMENT))
    rec = agent.get_or_create("j", "Acme", "TPM")
    assert verify_record(rec).is_valid is False
    agent.add_round(rec, {"round_type": "technical"})
    assert any("Date not recorded" in w for w in verify_record(rec).warnings)
