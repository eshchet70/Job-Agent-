# Architecture Decisions

1. SQLite is system of record for MVP; Excel is synchronized human-facing tracker.
2. Strategic Fit and ATS are separate because keyword similarity is not interview probability.
3. LLM/model output is advisory extraction/classification; formulas, gates, IDs and persistence are deterministic code.
4. Evidence Library is canonical for candidate claims.
5. Authenticated services are optional adapters and cannot become a dependency for core analysis.
6. External communication remains human-approved in MVP 1.
7. Job qualification is an application service with injected persistence and tracker adapters; importing the analysis entry points does not initialize the database.
