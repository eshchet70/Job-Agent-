"""
Excel Tracker Writer — sync SQLite analysis results to data/tracker_template.xlsx.
Preserves all 11 sheets, existing rows, formulas, fonts, cell styles and formatting.
Only appends/updates explicitly mapped columns; never silently overwrites.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

from app.config import settings
from app.models import ApplicationBrief, OutreachRecord

# ---------------------------------------------------------------------------
# Column mapping: logical name → exact header text in Applications sheet
# ---------------------------------------------------------------------------

APP_COLUMN_MAP = {
    "company":              "Company",
    "title":                "Role Title",
    "location":             "City / Remote",
    "country":              "Country",
    "status":               "Status",
    "next_action":          "Next Action",
    "next_action_date":     "Next Action Date",
    "weighted_score":       "Strategic Fit Score",
    "pursuit_tier":         "Pursuit Tier",
    "functional_score":     "Functional Fit (0-100)",
    "seniority_score":      "Seniority Fit (0-100)",
    "domain_score":         "Domain Fit (0-100)",
    "evidence_score":       "Evidence Strength (0-100)",
    "location_auth_score":  "Location/Auth Fit (0-100)",
    "competitive_score":    "Competitive Positioning (0-100)",
    "relationship_score":   "Relationship Access (0-100)",
    "ats_readiness":        "Fit Score (%)",
    "date_applied":         "Date Applied",
}

OUTREACH_COLUMN_MAP = {
    "date":        "Date",
    "person":      "Person",
    "company":     "Company",
    "contact_type":"Contact Type",
    "channel":     "Channel",
    "purpose":     "Purpose",
    "message_sent":"Message Sent?",
    "linked_app":  "Linked Application?",
}


def write_brief_to_tracker(
    brief: ApplicationBrief,
    tracker_path: Optional[str] = None,
) -> None:
    """
    Append or update an ApplicationBrief in the Excel tracker.
    Finds an existing row by Company+Title match; otherwise appends.
    """
    path = Path(tracker_path or settings.tracker_path)
    if not path.exists():
        raise FileNotFoundError(f"Tracker not found: {path}")

    wb = load_workbook(path)

    # ── Applications sheet ─────────────────────────────────────────────────
    ws_app = wb["Applications"]
    header_map = _build_header_map(ws_app)

    # Find existing row by Company + Title
    existing_row = _find_row(ws_app, header_map,
                              brief.job.company, brief.job.title)

    # Build the cell values to write
    values: dict[str, object] = {
        "company":      brief.job.company,
        "title":        brief.job.title,
        "location":     brief.job.location or "",
        "country":      brief.job.country or "",
        "status":       "Applied" if brief.next_action else "Analyzing",
        "next_action":  brief.next_action or "",
        "date_applied": datetime.now().strftime("%Y-%m-%d") if brief.next_action else "",
    }

    if brief.fit:
        values.update({
            "weighted_score":      brief.fit.weighted_score,
            "pursuit_tier":        brief.fit.tier.value.replace("_", " ").title(),
            "functional_score":    brief.fit.functional.score,
            "seniority_score":     brief.fit.seniority.score,
            "domain_score":        brief.fit.domain.score,
            "evidence_score":      brief.fit.evidence.score,
            "location_auth_score": brief.fit.location_auth.score,
            "competitive_score":   brief.fit.competitive.score,
            "relationship_score":  brief.fit.relationship.score,
        })

    if brief.ats:
        values["ats_readiness"] = brief.ats.readiness

    _write_values(ws_app, header_map, existing_row, values)

    # ── Outreach Log sheet ─────────────────────────────────────────────────
    if brief.outreach:
        ws_out = wb["Outreach Log"]
        out_header_map = _build_header_map(ws_out)
        for rec in brief.outreach:
            _append_outreach_row(ws_out, out_header_map, brief.job.company, rec)

    wb.save(path)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_header_map(ws) -> dict[str, int]:
    """Return {header_text: column_index} for row 1."""
    result = {}
    for cell in ws[1]:
        if cell.value:
            result[str(cell.value).strip()] = cell.column
    return result


def _find_row(ws, header_map: dict[str, int],
              company: str, title: str) -> Optional[int]:
    """Return the row number matching Company+Title, or None."""
    company_col = header_map.get("Company")
    title_col = header_map.get("Role Title")
    if not company_col or not title_col:
        return None
    for row in ws.iter_rows(min_row=2, values_only=False):
        c = row[company_col - 1].value
        t = row[title_col - 1].value
        if (c and str(c).strip().lower() == company.lower() and
                t and str(t).strip().lower() == title.lower()):
            return row[0].row
    return None


def _write_values(ws, header_map: dict[str, int],
                  row_num: Optional[int], values: dict) -> None:
    """Write key→value pairs to the appropriate columns; append if no existing row."""
    if row_num is None:
        row_num = ws.max_row + 1

    for logical_key, col_header in APP_COLUMN_MAP.items():
        col_idx = header_map.get(col_header)
        if col_idx and logical_key in values:
            ws.cell(row=row_num, column=col_idx, value=values[logical_key])


def _append_outreach_row(ws, header_map: dict[str, int],
                         company: str, rec: OutreachRecord) -> None:
    """Append one row to the Outreach Log sheet."""
    next_row = ws.max_row + 1
    values = {
        "Date":       datetime.now().strftime("%Y-%m-%d"),
        "Person":     rec.person_name or "",
        "Company":    company,
        "Channel":    rec.channel or "",
        "Purpose":    rec.objective or "",
        "Message Sent?": "No",
        "Linked Application?": company,
        "Contact Type": "Target",
    }
    for col_header, value in values.items():
        col_idx = header_map.get(col_header)
        if col_idx:
            ws.cell(row=next_row, column=col_idx, value=value)


def ensure_ats_headers(tracker_path: Optional[str] = None) -> None:
    """Add ATS-specific columns to Applications sheet if not present."""
    path = Path(tracker_path or settings.tracker_path)
    wb = load_workbook(path)
    ws = wb["Applications"]
    existing = {str(c.value).strip(): c.column for c in ws[1] if c.value}
    col = ws.max_column + 1
    ats_headers = [
        "ATS Readiness Score", "Critical Keyword Coverage %",
        "Important Keyword Coverage %", "Evidence Coverage %",
        "Missing Critical Keywords", "Keywords to Add",
        "Unsupported Keywords", "Resume Version",
    ]
    for h in ats_headers:
        if h not in existing:
            ws.cell(1, col, h)
            col += 1
    wb.save(path)
