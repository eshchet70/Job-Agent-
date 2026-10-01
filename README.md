# Job Search Operating Agent — Antigravity MVP 1

This repository is the handoff package for building Elena Shchetinina's evidence-grounded job-search agent in Antigravity.

## Start here in Antigravity
Open this repository root as the workspace. Then give Antigravity exactly this instruction:

> Read `docs/ANTIGRAVITY_MASTER_PROMPT.md` and execute it. Treat `docs/FINAL_BUILD_SPEC.md`, `data/candidate_profile.json`, `data/evidence_library.json`, and `.agents/skills/*/SKILL.md` as product contracts. Build Phase A first, run tests, and do not proceed to authenticated integrations until the core vertical slice passes.

## Product workflow
Discover -> Verify -> Deduplicate -> Hard Gates -> Strategic Fit -> ATS Match -> Evidence Map -> Hiring Management Chain -> Connection Analysis -> Personalized Messages -> Human Approval -> Tracker -> MyGreenhouse Sync -> Learning.

## Included assets
- Candidate profile customized for the target search.
- Evidence library covering Bell, Amazon and IBM examples with safe/unsafe claims.
- Existing enhanced Excel tracker as `data/tracker_template.xlsx`.
- Antigravity project skills for fit, ATS, evidence, hiring-chain research and outreach.
- Python scaffold and tests.
- Final product/build specification, data dictionary, test plan and architecture decisions.

## Local setup
```bash
python3.11 -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -e .[dev]
pytest
streamlit run app/ui/streamlit_app.py
```

## Security / account access
- Never store LinkedIn or MyGreenhouse passwords or MFA codes.
- Authenticated integrations must use an interactive user-authorized session/provider.
- Do not bypass CAPTCHA, MFA, rate limits or access controls.
- Core analysis must continue in public/manual mode when authenticated access is unavailable.
- Draft outreach automatically; sending requires explicit user approval.

## Candidate targeting constraints
Primary: senior/lead/principal TPM, technology portfolio leadership, AI program/portfolio/transformation, AI engineering portfolio & operations, data/platform program leadership, engineering/product operations, technology transformation.

Selective/avoid: pure hands-on engineering/ML research, architecture ownership roles, and pure product-management roles without program/portfolio scope. Do not target Amazon employment; exclude CGI from recommendations.
