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

## Daily job scout (automated)

Every morning a GitHub Actions workflow (`.github/workflows/daily-scout.yml`, 6:47 am Toronto):

1. **Discovers** openings from the company watchlist in `data/scout/config.json` (public Greenhouse, Lever and Ashby job-board APIs) and from Adzuna's aggregator API for broad Canadian coverage.
2. **Filters** by title family + seniority, location (Canada / remote-Canada) and excluded companies (Amazon, CGI).
3. **Scores** each new job with the existing engines: hard gates → strategic fit tier → ATS readiness against `data/master_resume.txt`.
4. **Tailors a resume** for each new Tier 1–2 job with Claude, using only facts from the master resume and the evidence library's `safe_claims`. Every draft is fact-checked (numbers, dates, roles, unsafe claims, plus a second Claude audit pass). Drafts that still have issues are marked *Needs review* instead of *Ready*.
5. **Publishes the dashboard** to GitHub Pages and commits the updated job store (`data/scout/jobs.json`).

Tailored resumes (`.docx` + `.md` + a notes file listing keywords added and JD requirements deliberately *not* added) are uploaded as a **private workflow artifact** for each run, never to the public dashboard.

### One-time setup

1. **Make the repository private** (Settings → General → Danger zone). Your resume, profile and evidence library live in `data/`.
2. **Add secrets** (Settings → Secrets and variables → Actions → New repository secret):
   - `ANTHROPIC_API_KEY` — from https://console.anthropic.com/ (resume agent; skipped if absent)
   - `ADZUNA_APP_ID`, `ADZUNA_APP_KEY` — free at https://developer.adzuna.com/ (aggregator; skipped if absent)
   - Optional *variables*: `ANTHROPIC_MODEL` (default `claude-sonnet-5-5`), `MAX_RESUMES_PER_RUN` (default 8)
3. **Enable Pages**: Settings → Pages → Build and deployment → Source: **GitHub Actions**. Publishing Pages from a private repo requires a paid GitHub plan; on a free plan the dashboard is still produced every day as a downloadable run artifact.
4. **Run it once now**: Actions → *Daily job scout* → *Run workflow*.

### Tuning

- Add companies to `watchlist` in `data/scout/config.json` (`ats` = greenhouse | lever | ashby, `slug` = the name in the company's job-board URL). Run `python -m app.scout check` to verify slugs.
- Adjust `title_filters`, `adzuna_queries` and `locations` in the same file.
- Run locally: `python -m app.scout daily` (or `run`, `resumes`, `dashboard` individually).

## Coordinator workflow (local app)

The Coordinator screen in the Streamlit app walks each scouted job through three gates:

1. **Gate 1 — approve or skip.** Jobs the scout later drops (posting closed, or outside your location filters) are skipped automatically on the next *Sync from Scout*.
2. **Gate 2 — resume.** *Tailor Resume* runs the Claude resume agent: it rewrites the master resume using only facts from `data/master_resume.txt` and the evidence library's `safe_claims`, then fact-checks the draft. The screen shows whether the fact check passed, what to review if it didn't, and which job requirements were left out for lack of evidence. *Re-tailor* sends your notes back to the agent for a new draft.
3. **Gate 3 — apply.** *Open & pre-fill application* opens the form in a browser window (Ashby, Greenhouse, Lever), fills your contact details and attaches the tailored resume. **It never clicks Submit.** You answer the employer's questions, submit it yourself, close the window, and click *I submitted it — mark as applied*.

After that, log interview rounds on the same screen and run the AI assessment.

### Keys for the local app

```bash
cp .env.example .env        # then paste your keys into .env (it is git-ignored)
python -m app.scout llm-check   # one small Claude call: confirms the key and model work
```

Without `ANTHROPIC_API_KEY` the resume agent and interview assessment do not run, and the app says so. Without the Adzuna keys the scout searches only the company watchlist. Pre-fill needs `pip install -e .[submission] && playwright install chromium`.

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
