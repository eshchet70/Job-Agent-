# Initial Antigravity build prompt

You are working in the Job Search Operating Agent repository. Read README.md, docs/IMPLEMENTATION_SPEC.md, app/models.py, and all project skills under .agents/skills/ before changing code.

Build the first vertical slice only:
1. Add an LLM-backed JD parser with strict Pydantic structured output.
2. Add a simple Streamlit form accepting a pasted JD, company, title, location and optional job URL.
3. Load data/evidence_library.json if present, otherwise the example library.
4. Run deterministic hard gates.
5. Produce Strategic Fit using the seven dimensions and deterministic weighted calculation.
6. Run ATS analysis and evidence mapping.
7. Display results in the Streamlit review UI.
8. Add unit tests and fixtures for at least one strong-fit and one poor-fit job.

Constraints:
- Do not implement automatic application submission or automatic external messaging.
- Do not add LinkedIn/MyGreenhouse credential collection.
- Do not fabricate candidate evidence.
- Keep numeric calculations deterministic and testable.
- Preserve the existing module boundaries.
