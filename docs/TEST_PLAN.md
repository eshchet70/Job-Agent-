# Test Plan

## Unit tests
- Strategic Fit weighted formula and tier boundaries.
- Hard-gate precedence.
- ATS weighted coverage, exact matching, semantic match adapter behavior.
- ADD requires evidence ID; unsupported term becomes DO_NOT_ADD.
- Evidence mapper never returns an unknown evidence ID.
- Hiring-chain confidence enum and inferred/confirmed labeling.
- Message generator rejects unsupported claims.
- Dedupe by job ID, canonical URL and normalized company/title/date.
- MyGreenhouse reconciliation creates conflicts rather than overwriting ambiguous values.

## Regression set
Use historical roles with known outcomes, including at least: active interview examples, screening examples, high-fit rejections, profession mismatches, U.S. authorization barriers, high ATS/low strategic-fit cases, and high strategic-fit/low ATS cases.

## End-to-end acceptance
Paste a JD -> analyze -> persist -> view fit/ATS/evidence -> add/research people -> generate drafts -> approve/skip -> export/update tracker.
