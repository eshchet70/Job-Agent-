"""
Coordinator state definitions.

Job lifecycle:
  discovered → approved → tailoring → resume_ready → submitted
                ↓                        ↓
             skipped              rejected_resume
"""
from __future__ import annotations

from enum import Enum


class JobStatus(str, Enum):
    discovered          = "discovered"           # Scout found it, awaiting user approval
    skipped             = "skipped"              # User rejected for this cycle
    approved            = "approved"             # User approved for tailoring
    tailoring           = "tailoring"            # Resume Agent running
    resume_ready        = "resume_ready"         # Tailored resume generated, awaiting approval
    rejected_resume     = "rejected_resume"      # User rejected resume draft
    submission_approved = "submission_approved"  # User approved resume, ready to submit
    submitting          = "submitting"           # Submission Agent running
    submitted           = "submitted"            # Application confirmed sent
    submission_failed   = "submission_failed"    # Playwright error / CAPTCHA
    interview           = "interview"            # Response received — interview
    rejected            = "rejected"             # Application rejected
    no_response         = "no_response"          # 21+ days silence


# Which statuses require user action in the UI
PENDING_USER_ACTION = {
    JobStatus.discovered,
    JobStatus.resume_ready,
    JobStatus.rejected_resume,
    JobStatus.submission_failed,
}

# Terminal statuses (no further action needed)
TERMINAL = {
    JobStatus.skipped,
    JobStatus.submitted,
    JobStatus.interview,
    JobStatus.rejected,
    JobStatus.no_response,
}
