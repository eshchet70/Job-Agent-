"""Local storage helpers for the candidate's master resume."""
from pathlib import Path

MASTER_RESUME_PATH = Path(__file__).resolve().parents[2] / "data" / "master_resume.txt"

CANDIDATE_RESUME_SYNOPSIS = """
Senior Technical Program Manager and Portfolio Leader with 20+ years experience.
Technical program management, portfolio management, program governance, roadmap planning,
dependency management, risk management, capacity and resource planning,
executive stakeholder management, cross-functional delivery, AI and data initiatives,
cloud and platform modernization, ServiceNow, Agile, SAFe, Lean Portfolio Management,
vendor governance, financial analysis, TCO, process re-engineering.
Bell Canada: Led application TCO discovery across 400+ applications, 60+ stakeholders,
seven data systems. Portfolio governance, intake, long-range planning cycles, Agile delivery.
Payment platform modernization with six enterprise architects.
Amazon: Managed Hardlines catalog, ontology, data quality programs with data scientists,
ontologists, 10+ engineers. Seller compliance program reduced non-compliant listings by 20%.
IBM: CLM and procurement integration reduced review time by 30%, improved accuracy by 15%.
Enterprise webmaster program, automation tooling, public sector health and human services.
MBA Rotman School of Management. B.S. Computer Information Systems.
SAFe Lean Portfolio Management. SAFe Advanced Scrum Master.
"""


def load_master_resume(allow_fallback: bool = False) -> str:
    if MASTER_RESUME_PATH.exists():
        try:
            content = MASTER_RESUME_PATH.read_text(encoding="utf-8").strip()
            if content:
                return content
        except OSError:
            pass
    return CANDIDATE_RESUME_SYNOPSIS.strip() if allow_fallback else ""


def save_master_resume(text: str) -> None:
    MASTER_RESUME_PATH.parent.mkdir(parents=True, exist_ok=True)
    MASTER_RESUME_PATH.write_text(text.strip(), encoding="utf-8")
