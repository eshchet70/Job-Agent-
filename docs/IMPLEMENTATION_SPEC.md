# MVP 1 Implementation Specification

## System of record
SQLite is the operational store. Excel is the human-facing tracker/report. Do not make workbook formulas the only business logic.

## LLM boundaries
Use structured outputs for JD parsing, semantic keyword matching, dimension rationales, evidence mapping, hiring-chain synthesis, and message drafting. Recalculate numeric weights and enforce gates in deterministic Python.

## Required stages
1. Job verification: OPEN/CLOSED/UNKNOWN, source, checked timestamp.
2. Deduplication: job ID/URL, then company+title+date similarity.
3. JD parsing: role family, seniority, must-haves, preferred, keywords, reporting clues, location/auth clues.
4. Hard gates.
5. Strategic Fit.
6. ATS analysis.
7. Evidence mapping.
8. Hiring-chain research for Tier 1 / strong Tier 2.
9. Connection enrichment when an authenticated, permitted session is available.
10. Personalized drafts.
11. Human approval.
12. Persist to DB + tracker.
13. Status synchronization / outcome learning.

## Authenticated integration boundary
LinkedIn and MyGreenhouse adapters are intentionally stubs. Implement only with a supported/permitted API or user-controlled authenticated browser capability in the target environment. Do not implement credential collection, CAPTCHA bypass, MFA bypass, or covert scraping.

## Definition of done
A single job can move from raw JD to a persisted application brief containing gate result, 7 fit dimensions, pursuit tier, ATS metrics/actions, evidence IDs, people targets with source/confidence, personalized draft messages, and next action.
