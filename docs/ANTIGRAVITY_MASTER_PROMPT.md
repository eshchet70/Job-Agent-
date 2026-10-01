# Antigravity Master Build Prompt

You are the implementation agent for this repository. Build the application described by `docs/FINAL_BUILD_SPEC.md`.

Read first, in order:
1. `README.md`
2. `docs/FINAL_BUILD_SPEC.md`
3. `data/candidate_profile.json`
4. `data/evidence_library.json`
5. every `.agents/skills/*/SKILL.md`
6. existing `app/` code and `tests/`

## Goal
Turn this scaffold into a runnable local MVP. Do not redesign the product unless required to fix a contradiction. Preserve evidence-grounding and human approval boundaries.

## Build order
### Phase A — vertical slice
1. Implement/finish Pydantic domain models.
2. Implement SQLite repository and schema migrations/bootstrap.
3. Implement JD parser interface. It must support pasted JD immediately; URL fetching is an adapter.
4. Implement hard gates.
5. Implement Strategic Fit calculation and deterministic weighting.
6. Implement ATS extraction/matching and deterministic scoring. Exact match first; semantic matching through an injectable model interface second.
7. Implement Evidence Mapper. Every recommended candidate claim must cite evidence IDs.
8. Implement recommendation/pursuit tier.
9. Implement Streamlit Analyze Job screen.
10. Persist analysis and show it in the UI.

### Phase B — people/outreach
11. Implement public people-research provider interface with provenance/confidence.
12. Implement hiring-chain aggregation and connection mapper.
13. Implement recipient-specific message generator using only verified evidence.
14. Add Approve/Edit/Skip controls for each draft.
15. Persist people and outreach records.

### Phase C — tracker/sync
16. Implement Excel import/export against `data/tracker_template.xlsx`. Preserve workbook formatting and existing sheets/columns; append/update only mapped fields.
17. Implement MyGreenhouse reconciliation interface and conflict model. Do not implement credential scraping.
18. Implement optional LinkedIn session adapter interface for user-authenticated enrichment. Do not implement password collection or security-control bypass.

### Phase D — quality
19. Add fixtures for at least 10 jobs and regression tests.
20. Add audit logging, source timestamps and user overrides.
21. Add dashboard metrics.

## Required implementation constraints
- Python 3.11+.
- Pydantic v2 models.
- SQLite via SQLAlchemy or standard sqlite3; choose one and document it.
- Streamlit local UI.
- Model provider behind an interface. Do not hard-wire business logic to one model vendor.
- Structured model output must validate against Pydantic schemas.
- All weighted scores are recalculated in Python, never trusted from model prose.
- A keyword cannot be recommended as ADD without a supporting evidence ID.
- `DO_NOT_ADD` must be generated for unsupported material requirements.
- People records require source + checked_at + confidence.
- Inferred hiring managers must be labeled inferred, not confirmed.
- No automated external messaging or application submission in MVP 1.
- Never store passwords/MFA codes. Never bypass CAPTCHA or access controls.

## Deliverables before declaring completion
- `streamlit run app/ui/streamlit_app.py` launches successfully.
- `pytest` passes.
- README contains exact setup/run instructions.
- `.env.example` documents required variables without secrets.
- One sample job can be analyzed end-to-end from pasted JD.
- Results persist to SQLite.
- Excel export/update works against the included tracker template.
- People/outreach screen can accept manually supplied or provider-returned people and generate evidence-grounded drafts.
- Authenticated adapters fail gracefully when no session/provider is configured.
- Provide a `docs/TEST_PLAN.md` and `docs/DECISIONS.md`.

When uncertain, prefer the simplest testable implementation that preserves these contracts. Do not remove safeguards to make a demo easier.
