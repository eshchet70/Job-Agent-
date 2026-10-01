"""
JSON job store for the daily scout.

Kept as a plain JSON file (data/scout/jobs.json) that the GitHub Actions run
commits back to the repo, so state survives between daily runs without a
hosted database and every day's changes are visible in git history.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_STORE = ROOT / "data" / "scout" / "jobs.json"

# Aggregator results only cover the last few days, so absence from one run
# does not mean the job closed. Expire them after this many days unseen.
AGGREGATOR_EXPIRY_DAYS = 21
# Closed jobs are dropped from the store after this many days to keep the file small.
CLOSED_RETENTION_DAYS = 45


def normalize_key(company: str, title: str) -> str:
    """Cross-source identity: same company + same title = same opening."""
    def norm(s: str) -> str:
        s = (s or "").lower()
        s = re.sub(r"\(.*?\)", " ", s)
        s = re.sub(r"\b(inc|ltd|llc|corp|corporation|limited|canada)\b\.?", " ", s)
        return re.sub(r"[^a-z0-9]+", " ", s).strip()
    return f"{norm(company)}|{norm(title)}"


@dataclass
class JobStore:
    path: Path = DEFAULT_STORE
    jobs: dict[str, dict[str, Any]] = field(default_factory=dict)
    runs: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "JobStore":
        path = Path(path or DEFAULT_STORE)
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls(path=path, jobs=data.get("jobs", {}), runs=data.get("runs", []))
        return cls(path=path)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"jobs": dict(sorted(self.jobs.items())), "runs": self.runs[-60:]}
        self.path.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

    # ------------------------------------------------------------------
    def find_by_identity(self, company: str, title: str) -> Optional[str]:
        key = normalize_key(company, title)
        for jid, rec in self.jobs.items():
            if rec.get("identity") == key and rec.get("status") == "open":
                return jid
        return None

    def open_jobs(self) -> list[dict[str, Any]]:
        return [j for j in self.jobs.values() if j.get("status") == "open"]

    def close_missing(self, seen_ids: set[str], healthy_sources: set[str], today: date) -> int:
        """Close board jobs that vanished from a board that fetched cleanly."""
        closed = 0
        for jid, rec in self.jobs.items():
            if rec.get("status") != "open" or jid in seen_ids:
                continue
            src = rec.get("source_key")
            if rec.get("source") == "adzuna":
                last = date.fromisoformat(rec["last_seen"])
                if (today - last).days > AGGREGATOR_EXPIRY_DAYS:
                    rec["status"], rec["closed_on"] = "expired", today.isoformat()
                    closed += 1
            elif src in healthy_sources:
                rec["status"], rec["closed_on"] = "closed", today.isoformat()
                rec.pop("description", None)  # no longer needed; keeps the file small
                closed += 1
        return closed

    def prune(self, today: date) -> None:
        for jid in [j for j, r in self.jobs.items()
                    if r.get("closed_on")
                    and (today - date.fromisoformat(r["closed_on"])).days > CLOSED_RETENTION_DAYS]:
            del self.jobs[jid]
