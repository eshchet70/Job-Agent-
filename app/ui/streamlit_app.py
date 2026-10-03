"""
Job Search Operating Agent — Streamlit MVP UI

Screens:
  1. Analyze Job     — paste JD → full qualification pipeline
  2. People & Outreach — manage hiring chain + draft messages
  3. Application Record — view persisted briefs
  4. Dashboard        — metrics overview
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

import streamlit as st

st.set_page_config(
    page_title="Job Search Operating Agent",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Imports ──────────────────────────────────────────────────────────────────
import importlib
from pathlib import Path

import pandas as pd

from app.config import settings
import app.db.database as db_module
import app.db.repository as repo
from app.db.database import init_db
from app.models import (
    Confidence,
    OutreachApproval,
    PersonTarget,
    PersonType,
)
import app.orchestrator as orch
from app.services import resume_tailor
from app.services import tracker_service

process_job = orch.process_job
load_evidence = orch.load_evidence
attach_people_and_outreach = orch.attach_people_and_outreach

MASTER_RESUME_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "master_resume.txt"

def load_master_resume() -> str:
    if MASTER_RESUME_FILE.exists():
        try:
            content = MASTER_RESUME_FILE.read_text(encoding="utf-8").strip()
            if content:
                return content
        except Exception:
            pass
    return ""

def save_master_resume(text: str) -> None:
    MASTER_RESUME_FILE.parent.mkdir(parents=True, exist_ok=True)
    MASTER_RESUME_FILE.write_text(text.strip(), encoding="utf-8")
    if hasattr(orch, "save_master_resume"):
        try:
            orch.save_master_resume(text)
        except Exception:
            pass

def clear_master_resume() -> None:
    MASTER_RESUME_FILE.parent.mkdir(parents=True, exist_ok=True)
    MASTER_RESUME_FILE.write_text("", encoding="utf-8")
    if hasattr(orch, "save_master_resume"):
        try:
            orch.save_master_resume("")
        except Exception:
            pass

from app.services import document_handler, message_generator, linkedin_finder, email_service

# Candidate profile info for outreach
candidate_profile_data = {}
try:
    c_prof_path = Path(__file__).resolve().parent.parent.parent / "data" / "candidate_profile.json"
    if c_prof_path.exists():
        candidate_profile_data = json.loads(c_prof_path.read_text(encoding="utf-8"))
except Exception:
    pass
cand_name = candidate_profile_data.get("name", "Elena Shchetinina")


def format_relative_time(dt) -> str:
    """Format a datetime into a human-readable relative string."""
    if not dt:
        return ""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    diff = now - dt
    days = diff.days
    if days <= 0:
        return "today"
    elif days == 1:
        return "yesterday"
    elif days < 7:
        return f"{days} days ago"
    elif days < 14:
        return "1 week ago"
    elif days < 30:
        return f"{days // 7} weeks ago"
    elif days < 60:
        return "1 month ago"
    else:
        return f"{days // 30} months ago"


def render_smtp_config_form(key_prefix: str = "global"):
    """Render an interactive SMTP settings and test form."""
    cfg = email_service.load_saved_email_config()

    st.markdown("###### ⚙️ SMTP Email Server Settings")
    st.caption("Configure credentials to dispatch outreach emails directly from the application.")

    configured_user = cfg.get("smtp_username", "").strip()
    configured_pass = cfg.get("smtp_password", "").strip()
    configured_host = cfg.get("smtp_host", "").strip()
    configured_port = cfg.get("smtp_port", 587)

    if configured_user and configured_pass:
        st.success(f"🟢 **Configured:** `{configured_user}` via `{configured_host}:{configured_port}`")
    else:
        st.info("ℹ️ Enter your email address and App Password below, then click **Save Credentials**.")

    provider_options = [
        "Gmail (smtp.gmail.com:587)",
        "Outlook / Office 365 (smtp.office365.com:587)",
        "iCloud (smtp.mail.me.com:587)",
        "Yahoo (smtp.mail.yahoo.com:587)",
        "Custom SMTP Server",
    ]

    current_host = cfg.get("smtp_host", "")
    current_provider_idx = 0
    if "office365" in current_host or "outlook" in current_host:
        current_provider_idx = 1
    elif "mail.me.com" in current_host:
        current_provider_idx = 2
    elif "yahoo" in current_host:
        current_provider_idx = 3
    elif current_host and "gmail" not in current_host:
        current_provider_idx = 4

    provider_choice = st.selectbox(
        "Email Provider Preset",
        provider_options,
        index=current_provider_idx,
        key=f"{key_prefix}_provider",
    )

    preset_hosts = {
        "Gmail (smtp.gmail.com:587)": ("smtp.gmail.com", 587, True, False),
        "Outlook / Office 365 (smtp.office365.com:587)": ("smtp.office365.com", 587, True, False),
        "iCloud (smtp.mail.me.com:587)": ("smtp.mail.me.com", 587, True, False),
        "Yahoo (smtp.mail.yahoo.com:587)": ("smtp.mail.yahoo.com", 587, True, False),
    }

    if provider_choice in preset_hosts:
        default_host, default_port, default_tls, default_ssl = preset_hosts[provider_choice]
    else:
        default_host = cfg.get("smtp_host") or "smtp.example.com"
        default_port = int(cfg.get("smtp_port") or 587)
        default_tls = bool(cfg.get("smtp_use_tls", True))
        default_ssl = bool(cfg.get("smtp_use_ssl", False))

    col_h, col_p = st.columns([3, 1])
    with col_h:
        smtp_host = st.text_input(
            "SMTP Host",
            value=default_host,
            key=f"{key_prefix}_host",
        )
    with col_p:
        smtp_port = st.number_input(
            "Port",
            value=default_port,
            min_value=1,
            max_value=65535,
            key=f"{key_prefix}_port",
        )

    col_u, col_pwd = st.columns([1, 1])
    with col_u:
        smtp_username = st.text_input(
            "Your Email Address / Username",
            value=cfg.get("smtp_username", ""),
            placeholder="e.g. evschetinina@gmail.com",
            key=f"{key_prefix}_user",
        )
    with col_pwd:
        smtp_password = st.text_input(
            "Password / App Password",
            value=cfg.get("smtp_password", ""),
            type="password",
            placeholder="16-character App Password",
            key=f"{key_prefix}_pass",
            help="For Gmail, use a 16-character Google App Password from myaccount.google.com/apppasswords.",
        )

    col_n, col_sec = st.columns([2, 1])
    with col_n:
        smtp_sender_name = st.text_input(
            "Sender Display Name",
            value=cfg.get("smtp_sender_name") or cand_name,
            key=f"{key_prefix}_name",
        )
    with col_sec:
        smtp_use_tls = st.checkbox(
            "Use STARTTLS",
            value=True if ("gmail" in provider_choice.lower() or default_port == 587) else default_tls,
            key=f"{key_prefix}_tls",
        )

    if "gmail" in provider_choice.lower() or "gmail" in smtp_host.lower():
        st.info(
            "💡 **Gmail App Password Required**:\n"
            "Google accounts require a dedicated 16-character **App Password** (not your regular account password or a browser-generated strong password).\n\n"
            "👉 **[Click here to generate a Google App Password](https://myaccount.google.com/apppasswords)**\n"
            "1. Enter app name (e.g. `Job Agent`) and click **Create**.\n"
            "2. Copy the **16-letter code** (e.g. `abcd efgh ijkl mnop`) and paste it into the Password field above."
        )
    elif "outlook" in provider_choice.lower() or "office365" in provider_choice.lower():
        st.info("💡 **Outlook/M365 Guide**: Ensure Authenticated SMTP is enabled on your Microsoft 365 mailbox settings.")

    col_b1, col_b2 = st.columns([1, 1])
    with col_b1:
        if st.button("💾 Save Credentials", key=f"{key_prefix}_btn_save", type="primary", use_container_width=True):
            clean_host = smtp_host.strip()
            clean_port = int(smtp_port)
            clean_user = smtp_username.strip()
            clean_pass = smtp_password.strip()
            clean_name = smtp_sender_name.strip() or cand_name

            # Gmail & port 587 require STARTTLS
            use_tls = smtp_use_tls or ("gmail" in clean_host.lower()) or (clean_port == 587)
            use_ssl = (clean_port == 465)

            new_cfg = {
                "smtp_host": clean_host,
                "smtp_port": clean_port,
                "smtp_username": clean_user,
                "smtp_password": clean_pass,
                "smtp_sender_email": clean_user,
                "smtp_sender_name": clean_name,
                "smtp_use_tls": use_tls,
                "smtp_use_ssl": use_ssl,
            }
            email_service.save_email_config(new_cfg)
            st.session_state[f"{key_prefix}_save_status"] = f"Credentials saved successfully for {clean_user} ({clean_host}:{clean_port})!"
            st.session_state[f"{key_prefix}_test_res"] = None

    with col_b2:
        if st.button("🔌 Test Connection", key=f"{key_prefix}_btn_test", use_container_width=True):
            clean_host = smtp_host.strip()
            clean_port = int(smtp_port)
            clean_user = smtp_username.strip()
            clean_pass = smtp_password.strip()
            if not clean_host or not clean_user:
                st.warning("Please provide SMTP Host and Username before testing.")
            else:
                with st.spinner(f"Connecting to {clean_host}:{clean_port}..."):
                    use_tls = smtp_use_tls or ("gmail" in clean_host.lower()) or (clean_port == 587)
                    ok, msg = email_service.test_smtp_connection(
                        host=clean_host,
                        port=clean_port,
                        username=clean_user,
                        password=clean_pass,
                        use_tls=use_tls,
                        use_ssl=(clean_port == 465),
                    )
                    from datetime import datetime
                    now_str = datetime.now().strftime("%I:%M:%S %p")
                    st.session_state[f"{key_prefix}_test_res"] = (ok, f"[{now_str}] {msg}")

    # Direct "Send Test Email" button so user can verify delivery in their real inbox
    if st.button("📨 Send Verification Email to My Inbox", key=f"{key_prefix}_btn_send_test", use_container_width=True):
        clean_host = smtp_host.strip()
        clean_port = int(smtp_port)
        clean_user = smtp_username.strip()
        clean_pass = smtp_password.strip()
        if not clean_user or not clean_pass:
            st.warning("Please configure and save your credentials first.")
        else:
            with st.spinner(f"Sending verification email to {clean_user}..."):
                res = email_service.send_email(
                    to_email=clean_user,
                    subject="Job Search Agent — SMTP Verification Email",
                    body=(
                        f"Hello {smtp_sender_name.strip() or 'there'},\n\n"
                        f"This is a confirmation test email from your Job Search Agent!\n\n"
                        f"Your email connection to {clean_host}:{clean_port} is fully operational, "
                        f"and you can now dispatch personalized outreach emails directly from the app.\n\n"
                        f"Best regards,\nJob Search Agent"
                    ),
                    is_approved=True,
                )
                from datetime import datetime
                now_str = datetime.now().strftime("%I:%M:%S %p")
                st.session_state[f"{key_prefix}_send_test_res"] = (res.success, f"[{now_str}] {res.message}")

    if st.session_state.get(f"{key_prefix}_save_status"):
        st.success(f"💾 {st.session_state[f'{key_prefix}_save_status']}")

    if st.session_state.get(f"{key_prefix}_test_res"):
        t_ok, t_msg = st.session_state[f"{key_prefix}_test_res"]
        if t_ok:
            st.success(f"🔌 {t_msg}")
        else:
            st.error(f"❌ {t_msg}")

    if st.session_state.get(f"{key_prefix}_send_test_res"):
        s_ok, s_msg = st.session_state[f"{key_prefix}_send_test_res"]
        if s_ok:
            st.success(f"📬 {s_msg}")
        else:
            st.error(f"❌ {s_msg}")


# ── Init ─────────────────────────────────────────────────────────────────────
init_db()

# ── Styling ───────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
.stApp { background: #0f172a; color: #f8fafc; }
section[data-testid="stSidebar"] {
    background: linear-gradient(160deg, #0f172a 0%, #1e293b 100%);
    border-right: 1px solid #334155;
}
section[data-testid="stSidebar"] * { color: #e2e8f0 !important; }

/* Input, Textarea, and Select Dark Mode & High Contrast */
div[data-baseweb="input"],
div[data-baseweb="base-input"],
div[data-baseweb="textarea"],
div[data-baseweb="select"] {
    background-color: #1e293b !important;
    border: 1px solid #334155 !important;
    border-radius: 8px !important;
    color: #f8fafc !important;
}

input,
textarea,
div[data-baseweb="input"] input,
div[data-baseweb="textarea"] textarea {
    background-color: #1e293b !important;
    color: #f8fafc !important;
    -webkit-text-fill-color: #f8fafc !important;
    font-family: 'Inter', sans-serif !important;
    font-size: 0.95rem !important;
    line-height: 1.5 !important;
}

div[data-baseweb="input"]:focus-within,
div[data-baseweb="textarea"]:focus-within {
    border-color: #38bdf8 !important;
    box-shadow: 0 0 0 1px #38bdf8 !important;
}

input::placeholder,
textarea::placeholder {
    color: #64748b !important;
    -webkit-text-fill-color: #64748b !important;
    opacity: 0.8 !important;
}

div[data-baseweb="select"] div,
ul[role="listbox"],
li[role="option"] {
    background-color: #1e293b !important;
    color: #f8fafc !important;
}

/* Button High Contrast & Interactive States */
button[data-testid="baseButton-secondary"] {
    background-color: #1e293b !important;
    border: 1px solid #475569 !important;
    color: #f8fafc !important;
    font-weight: 500 !important;
    transition: all 0.15s ease-in-out !important;
}
button[data-testid="baseButton-secondary"]:hover {
    background-color: #334155 !important;
    border-color: #38bdf8 !important;
    color: #38bdf8 !important;
    box-shadow: 0 0 10px rgba(56, 189, 248, 0.2) !important;
}
button[data-testid="baseButton-primary"] {
    background: linear-gradient(135deg, #0284c7 0%, #0369a1 100%) !important;
    border: none !important;
    color: #ffffff !important;
    font-weight: 600 !important;
}

/* Base typography scaling - more compact & refined */
html, body {
    font-size: 14px !important;
}

h1, .stApp h1 { font-size: 1.5rem !important; }
h2, .stApp h2 { font-size: 1.25rem !important; }
h3, .stApp h3 { font-size: 1.05rem !important; }
h4, .stApp h4 { font-size: 0.92rem !important; }
h5, .stApp h5 { font-size: 0.85rem !important; }

p, span, label {
    font-size: 0.88rem;
}

/* Streamlit Metrics Font Size & Truncation Fix */
div[data-testid="stMetric"] {
    background-color: #1e293b !important;
    border: 1px solid #334155 !important;
    border-radius: 8px !important;
    padding: 6px 10px !important;
}

div[data-testid="stMetricLabel"] {
    font-size: 0.72rem !important;
    font-weight: 500 !important;
    color: #94a3b8 !important;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    margin-bottom: 2px !important;
}

div[data-testid="stMetricLabel"] p {
    font-size: 0.72rem !important;
    color: #94a3b8 !important;
    margin: 0 !important;
}

div[data-testid="stMetricValue"] {
    font-size: 1.02rem !important;
    font-weight: 600 !important;
    color: #f8fafc !important;
    white-space: normal !important;
    overflow: visible !important;
    text-overflow: unset !important;
    line-height: 1.25 !important;
}

div[data-testid="stMetricValue"] > div {
    font-size: 1.02rem !important;
    white-space: normal !important;
    overflow: visible !important;
    text-overflow: unset !important;
    line-height: 1.25 !important;
}

div[data-testid="stMetricDelta"] {
    font-size: 0.72rem !important;
}

/* Sidebar metrics */
section[data-testid="stSidebar"] div[data-testid="stMetric"] {
    background: transparent !important;
    border: none !important;
    padding: 2px 0 !important;
}
section[data-testid="stSidebar"] div[data-testid="stMetricValue"],
section[data-testid="stSidebar"] div[data-testid="stMetricValue"] > div {
    font-size: 1.15rem !important;
}

/* Expander headers */
div[data-testid="stExpander"] details summary {
    font-size: 0.88rem !important;
    padding: 6px 10px !important;
}
div[data-testid="stExpander"] details summary p {
    font-size: 0.88rem !important;
}

button {
    font-size: 0.85rem !important;
}

.metric-card {
    background: linear-gradient(135deg, #1e3a5f 0%, #0d2137 100%);
    border-radius: 10px; padding: 0.8rem 1rem;
    border-left: 3px solid #4fc3f7; margin-bottom: 0.5rem;
}
.metric-card small {
    font-size: 0.75rem !important;
    color: #94a3b8 !important;
}
.metric-card b {
    font-size: 1.3em !important;
}
.tier-badge-tier_1   { background:#1a7a4a; color:#fff; border-radius:8px; padding:2px 10px; font-weight:700; font-size:0.85em; }
.tier-badge-tier_2   { background:#b5860b; color:#fff; border-radius:8px; padding:2px 10px; font-weight:700; font-size:0.85em; }
.tier-badge-tier_3   { background:#b35c00; color:#fff; border-radius:8px; padding:2px 10px; font-weight:700; font-size:0.85em; }
.tier-badge-do_not_pursue { background:#8b0000; color:#fff; border-radius:8px; padding:2px 10px; font-weight:700; font-size:0.85em; }
.tier-badge-barrier  { background:#555; color:#fff; border-radius:8px; padding:2px 10px; font-weight:700; font-size:0.85em; }
.evidence-tag { background:#1e3a5f; color:#4fc3f7; border-radius:6px; padding:1px 8px; font-size:0.8em; margin-right:4px; }
.barrier-box { background:#3d0000; border-left:4px solid #ff4b4b; border-radius:8px; padding:0.8rem 1rem; margin:0.5rem 0; font-size:0.88em; }
.safe-claim { background:#0a2a0a; border-left:3px solid #4caf50; border-radius:6px; padding:0.5rem 0.8rem; margin:0.3rem 0; font-size:0.85em; }

pre, code {
    background-color: #1e293b !important;
    color: #e2e8f0 !important;
    border-radius: 8px;
    padding: 0.8rem;
    font-size: 0.82rem !important;
    white-space: pre-wrap !important;
    word-break: break-word !important;
}
</style>
""", unsafe_allow_html=True)


# =============================================================================
# Helper: render ApplicationBrief results
# =============================================================================

def _render_brief(brief, in_coordinator: bool = False):
    """Render a full ApplicationBrief result."""
    job = brief.job
    fit = brief.fit
    gate = brief.gate
    ats = brief.ats

    cur_screen = st.session_state.get("nav_screen_radio", "")
    is_in_coord = in_coordinator or (cur_screen == "🎯 Coordinator")

    st.divider()

    # Header row
    hcol1, hcol2, hcol3, hcol4 = st.columns([3, 2, 2, 2])
    with hcol1:
        st.subheader(f"{job.company} — {job.title}")
        st.caption(f"{job.location or ''} · {job.work_model or ''} · {job.role_family or ''}")
    with hcol2:
        if fit:
            tier_label = fit.tier.value.replace("_", " ").title()
            st.markdown(
                f"<div class='metric-card'>"
                f"<small>Strategic Fit</small><br>"
                f"<b style='font-size:1.8em;color:#4fc3f7'>{fit.weighted_score}</b>/100<br>"
                f"<span class='tier-badge-{fit.tier.value}'>{tier_label}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )
    with hcol3:
        if ats:
            st.markdown(
                f"<div class='metric-card'>"
                f"<small>ATS Readiness</small><br>"
                f"<b style='font-size:1.8em;color:#4fc3f7'>{ats.readiness:.0f}%</b><br>"
                f"<small>Critical: {ats.critical_coverage:.0f}% · Important: {ats.important_coverage:.0f}%</small>"
                f"</div>",
                unsafe_allow_html=True,
            )
    with hcol4:
        if gate:
            status = "✅ PASSED" if gate.passed else "🚫 BARRIERS"
            color = "#4caf50" if gate.passed else "#ff4b4b"
            st.markdown(
                f"<div class='metric-card'>"
                f"<small>Hard Gates</small><br>"
                f"<b style='font-size:1.4em;color:{color}'>{status}</b>"
                f"</div>",
                unsafe_allow_html=True,
            )

    # Barriers
    if gate and gate.barriers:
        for b in gate.barriers:
            st.markdown(f"<div class='barrier-box'>⛔ {b}</div>", unsafe_allow_html=True)

    # Next action
    if brief.next_action:
        st.info(f"📌 **Next Action:** {brief.next_action}")

    # ── Coordinator Pipeline Connection ──────────────────────────────────────
    from app.coordinator import CoordinatorAgent, JobStatus
    coord_agent = CoordinatorAgent()
    c_company = (job.company or "").strip()
    c_title = (job.title or "").strip()
    c_url = ((getattr(job, "official_url", "") or "").strip() or (getattr(job, "source_url", "") or "").strip())
    active_cid = st.session_state.get("coordinator_active_job_id")

    coord_entry = coord_agent.queue.find_entry(
        job_id=active_cid,
        company=c_company,
        title=c_title,
        url=c_url,
    )

    with st.container(border=True):
        if coord_entry:
            q_status = coord_entry.status
            key_suffix = coord_entry.id
            if q_status == JobStatus.discovered:
                c_head, c_btn1, c_btn2, c_btn3 = st.columns([3, 1.8, 1.2, 1.5])
                with c_head:
                    st.markdown("**🎯 Coordinator Pipeline: Gate 1 Action**")
                    st.caption("Status: **Awaiting Approval**. Approve this role to proceed with hiring contacts & resume tailoring:")
                with c_btn1:
                    if st.button("✅ Approve for Tailoring", key=f"brief_coord_appr_{key_suffix}", type="primary", use_container_width=True):
                        coord_agent.approve_job(coord_entry.id)
                        st.session_state.pop(f"coord_show_analysis_{coord_entry.id}", None)
                        st.session_state[f"coord_show_analysis_{coord_entry.id}"] = False
                        st.toast(f"Approved {c_company} in Coordinator!", icon="✅")
                        st.session_state["nav_screen"] = "🎯 Coordinator"
                        st.session_state["nav_screen_radio"] = "🎯 Coordinator"
                        st.rerun()
                with c_btn2:
                    if st.button("⏭ Skip Job", key=f"brief_coord_skip_{key_suffix}", use_container_width=True):
                        coord_agent.skip_job(coord_entry.id, "Skipped from Job Analysis")
                        st.session_state.pop(f"coord_show_analysis_{coord_entry.id}", None)
                        st.session_state[f"coord_show_analysis_{coord_entry.id}"] = False
                        st.toast(f"Skipped {c_company} in Coordinator", icon="⏭")
                        st.session_state["nav_screen"] = "🎯 Coordinator"
                        st.session_state["nav_screen_radio"] = "🎯 Coordinator"
                        st.rerun()
                with c_btn3:
                    btn3_label = "✖️ Close Analysis" if is_in_coord else "🎯 Open in Coordinator"
                    btn3_help = "Close analysis and return to Coordinator queue" if is_in_coord else "Switch to Coordinator screen to manage this job"
                    if st.button(btn3_label, key=f"brief_coord_goto_{key_suffix}", use_container_width=True, help=btn3_help):
                        st.session_state.pop(f"coord_show_analysis_{coord_entry.id}", None)
                        st.session_state[f"coord_show_analysis_{coord_entry.id}"] = False
                        st.session_state["nav_screen"] = "🎯 Coordinator"
                        st.session_state["nav_screen_radio"] = "🎯 Coordinator"
                        if is_in_coord:
                            st.toast("Closed analysis view", icon="↩️")
                        else:
                            st.toast(f"Opening Coordinator for {c_company}…", icon="🎯")
                        st.rerun()
            elif q_status == JobStatus.approved:
                c_head, c_btn = st.columns([4, 2])
                with c_head:
                    st.markdown(f"**🎯 Coordinator Status:** ✅ **Approved** (Ready for hiring contacts & resume tailoring)")
                with c_btn:
                    btn_appr_label = "✖️ Close Analysis" if is_in_coord else "🎯 Open in Coordinator Pipeline"
                    if st.button(btn_appr_label, key=f"brief_coord_appr_goto_{key_suffix}", type="primary", use_container_width=True):
                        st.session_state.pop(f"coord_show_analysis_{coord_entry.id}", None)
                        st.session_state[f"coord_show_analysis_{coord_entry.id}"] = False
                        st.session_state["nav_screen"] = "🎯 Coordinator"
                        st.session_state["nav_screen_radio"] = "🎯 Coordinator"
                        st.rerun()
            else:
                c_head, c_btn = st.columns([4, 2])
                with c_head:
                    st.markdown(f"**🎯 Coordinator Status:** ℹ️ **{q_status.value.replace('_', ' ').title()}**")
                with c_btn:
                    btn_oth_label = "✖️ Close Analysis" if is_in_coord else "🎯 View in Coordinator Pipeline"
                    if st.button(btn_oth_label, key=f"brief_coord_view_goto_{key_suffix}", use_container_width=True):
                        st.session_state.pop(f"coord_show_analysis_{coord_entry.id}", None)
                        st.session_state[f"coord_show_analysis_{coord_entry.id}"] = False
                        st.session_state["nav_screen"] = "🎯 Coordinator"
                        st.session_state["nav_screen_radio"] = "🎯 Coordinator"
                        st.rerun()
        else:
            c_add1, c_add2 = st.columns([4, 2])
            with c_add1:
                st.markdown("**🎯 Coordinator Pipeline Connection**")
                st.caption("This job is not yet in your Coordinator queue. Add it to enable human approval, hiring contacts discovery, and automated resume tailoring.")
            with c_add2:
                key_suffix = abs(hash(c_company + c_title)) % 1000000
                if st.button("➕ Add to Coordinator Queue", key=f"brief_coord_add_{key_suffix}", type="primary", use_container_width=True):
                    new_e = coord_agent.queue.upsert_from_brief(brief)
                    coord_agent.save()
                    st.toast(f"Added {c_company} to Coordinator queue!", icon="🎯")
                    st.session_state["coordinator_active_job_id"] = new_e.id
                    st.rerun()

    # ── Application & Company Career Site Access ──────────────────────────────
    import urllib.parse
    company_name = (job.company or "").strip()
    title_name = (job.title or "").strip()
    company_query = urllib.parse.quote_plus(f"{company_name} {title_name} careers apply")
    portal_query = urllib.parse.quote_plus(f"{company_name} careers open positions")
    google_search_url = f"https://www.google.com/search?q={company_query}"
    portal_search_url = f"https://www.google.com/search?q={portal_query}"

    raw_url = ((job.official_url or "").strip() or (job.source_url or "").strip())
    is_linkedin = "linkedin.com" in raw_url.lower() if raw_url else False
    has_company_url = bool(raw_url and not is_linkedin)

    app_bar_c1, app_bar_c2, app_bar_c3 = st.columns([2, 2, 2])
    with app_bar_c1:
        if has_company_url:
            st.link_button(
                "🌐 Open Role on Company Site",
                raw_url,
                type="primary",
                use_container_width=True,
                help=f"Direct link to official company career portal: {raw_url}",
            )
        else:
            st.link_button(
                "🌐 Find on Company Careers Site",
                google_search_url,
                type="primary",
                use_container_width=True,
                help=f"Search Google directly for this role on {company_name}'s official career site (bypasses LinkedIn)",
            )
    with app_bar_c2:
        st.link_button(
            f"🏢 {company_name} Careers Portal",
            portal_search_url,
            use_container_width=True,
            help=f"Open {company_name}'s main careers / jobs portal",
        )
    with app_bar_c3:
        if is_linkedin:
            st.caption("ℹ️ Source JD from LinkedIn. Use buttons to apply on company site.")
        elif has_company_url:
            st.caption("✅ Official company career URL loaded.")
        else:
            st.caption("ℹ️ Direct company career search ready.")

    # Tabs
    tab_fit, tab_ats, tab_ev, tab_tailored, tab_raw = st.tabs(
        ["🎯 Strategic Fit", "🔑 ATS Keywords", "📚 Evidence Map", "📄 Tailored Resume Draft", "🗂 Raw JD"]
    )

    with tab_fit:
        if fit:
            dims = {
                "Functional": fit.functional,
                "Seniority": fit.seniority,
                "Domain": fit.domain,
                "Evidence Strength": fit.evidence,
                "Location/Auth": fit.location_auth,
                "Competitive": fit.competitive,
                "Relationship": fit.relationship,
            }
            for name, dim in dims.items():
                st.markdown(f"**{name}** — {dim.score}/100")
                st.progress(dim.score / 100)
                st.caption(dim.rationale)
                if dim.evidence_ids:
                    tags = " ".join(
                        f"<span class='evidence-tag'>{eid}</span>" for eid in dim.evidence_ids
                    )
                    st.markdown(tags, unsafe_allow_html=True)
                st.divider()
        else:
            st.info("No strategic fit data.")

    with tab_ats:
        if ats:
            col_a, col_b, col_c = st.columns(3)
            col_a.metric("Critical Coverage", f"{ats.critical_coverage:.0f}%")
            col_b.metric("Important Coverage", f"{ats.important_coverage:.0f}%")
            col_c.metric("Evidence Coverage", f"{ats.evidence_coverage:.0f}%")

            missing_kw_matches = [m for m in ats.matches if m.action.value in ("ADD", "DO_NOT_ADD") or not (m.exact_match or m.semantic_match)]
            if missing_kw_matches:
                st.info(
                    f"💡 **{len(missing_kw_matches)} missing keywords detected!** Switch to the **'📄 Tailored Resume Draft'** tab "
                    f"to automatically integrate them into your **current role (Bell Canada)** bullets and boost your ATS score."
                )

            st.subheader("Keyword Actions")
            action_icons = {"KEEP": "🟢", "ADD": "🟡", "STRENGTHEN": "🔵", "DO_NOT_ADD": "🔴"}
            for m in ats.matches:
                icon = action_icons.get(m.action.value, "⚪")
                ev_tags = " ".join(
                    f"<span class='evidence-tag'>{e}</span>" for e in m.evidence_ids
                )
                with st.expander(
                    f"{icon} [{m.action.value}] **{m.keyword}** ({m.importance})", expanded=False
                ):
                    st.caption(f"Category: {m.category}")
                    st.caption(f"Exact match: {m.exact_match} · Semantic: {m.semantic_match}")
                    if ev_tags:
                        st.markdown(f"Evidence: {ev_tags}", unsafe_allow_html=True)
        else:
            st.info("No ATS data.")

    with tab_ev:
        if brief.evidence_map:
            st.subheader("Requirement → Evidence Mapping")
            strength_icons = {"strong": "💪", "medium": "👍", "weak": "🤔", "none": "❌"}
            for em in brief.evidence_map:
                icon = strength_icons.get(em.strength, "❓")
                with st.expander(
                    f"{icon} **{em.requirement}** ({em.strength})", expanded=False
                ):
                    if em.is_supported:
                        ev_tags = " ".join(
                            f"<span class='evidence-tag'>{e}</span>" for e in em.evidence_ids
                        )
                        st.markdown(f"Evidence IDs: {ev_tags}", unsafe_allow_html=True)
                        if em.safe_wording:
                            st.markdown(
                                f"<div class='safe-claim'>✅ Safe wording: {em.safe_wording}</div>",
                                unsafe_allow_html=True,
                            )
                    else:
                        st.warning("No evidence found — DO NOT CLAIM without verified support.")
        else:
            st.info("No evidence mappings.")

    with tab_tailored:
        st.subheader(f"📄 Tailored Resume Draft for {job.company}")
        st.caption(
            "Evidence-grounded tailoring of your Master Resume aligned to this job's requirements and ATS keywords."
        )

        master_text = load_master_resume()
        job_key = str(brief.job.id or "current")

        # ── 1. Keyword Gap & Missing Analysis ──
        parsed_jd = brief.parsed_jd or orch.jd_parser.parse_jd(job.description, company=job.company)
        missing_analysis = resume_tailor.detect_missing_keywords(parsed_jd, master_text)
        missing_cur_role = missing_analysis["missing_from_current_role"]
        missing_resume = missing_analysis["missing_from_resume"]

        keep_kws = [m.keyword for m in (ats.matches if ats else []) if m.action.value == "KEEP"]
        add_kws = [m.keyword for m in (ats.matches if ats else []) if m.action.value == "ADD"]
        strengthen_kws = [m.keyword for m in (ats.matches if ats else []) if m.action.value == "STRENGTHEN"]
        safe_bullets = [em.safe_wording for em in (brief.evidence_map or []) if em.is_supported and em.safe_wording]

        # Metric summary cards
        c_m1, c_m2, c_m3, c_m4 = st.columns(4)
        c_m1.metric("Current ATS Readiness", f"{ats.readiness:.0f}%" if ats else "N/A")
        c_m2.metric("Missing from Current Role", f"{len(missing_cur_role)}")
        c_m3.metric("Missing from Resume", f"{len(missing_resume)}")
        c_m4.metric("Evidence-Supported Gaps", f"{sum(1 for m in missing_cur_role if m['is_supported'])}")

        tc1, tc2 = st.columns(2)
        with tc1:
            st.markdown("##### 🔑 Keywords Missing from Current Role Experience (Bell Canada)")
            if missing_cur_role:
                badge_html = " ".join(
                    f"<span class='tier-badge-tier_{'1' if m['importance']=='critical' else '2'}'>{m['keyword']}</span>"
                    for m in missing_cur_role[:10]
                )
                st.markdown(badge_html, unsafe_allow_html=True)
            else:
                st.info("All target role keywords are already present in your current role experience.")

        with tc2:
            st.markdown("##### 📌 Relevant Safe Evidence Bullets")
            if safe_bullets:
                for b in safe_bullets[:3]:
                    st.markdown(f"- {b}")
            else:
                st.caption("Standard evidence-grounded role formulation.")

        st.divider()

        # ── 2. INTERACTIVE KEYWORD TAILORING CONTROLS ──
        st.markdown("### ⚡ Update Resume & Current Role for Missing Keywords")
        st.caption(
            "Select missing keywords from this job posting to automatically weave into your "
            "**Current Role (Bell Canada)** bullets, Professional Summary, and Core Capabilities."
        )

        all_missing_kw_names = [m["keyword"] for m in missing_cur_role]
        default_selected = [
            m["keyword"] for m in missing_cur_role
            if m["is_supported"] or m["importance"] in ("critical", "important")
        ][:8]

        sess_tailor_kws_key = f"sel_tailor_kws_{job_key}"
        if sess_tailor_kws_key not in st.session_state:
            st.session_state[sess_tailor_kws_key] = default_selected

        selected_tailor_kws = st.multiselect(
            "Missing keywords to integrate:",
            options=all_missing_kw_names,
            default=st.session_state[sess_tailor_kws_key],
            key=f"ms_tailor_kws_{job_key}",
            help="Choose which missing keywords from the job description to weave into your resume",
        )

        custom_kw_input = st.text_input(
            "➕ Add custom keywords (comma-separated, optional):",
            key=f"custom_kw_in_{job_key}",
            placeholder="e.g. Enterprise Architecture, Vendor Negotiation, Executive Reporting",
        )

        tog_c1, tog_c2, tog_c3, tog_c4 = st.columns(4)
        up_cur_role = tog_c1.checkbox("Update Current Role (Bell)", value=True, help="Add or enrich Bell Canada experience bullets with selected keywords")
        up_summary = tog_c2.checkbox("Update Summary", value=True, help="Align summary with target role title and keywords")
        up_comp = tog_c3.checkbox("Update Core Capabilities", value=True, help="Inject keywords into top competencies block")
        up_tools = tog_c4.checkbox("Update Tools & Tech", value=True, help="Add relevant tools to Tools & Technology")

        btn_t1, btn_t2 = st.columns([2, 1])
        with btn_t1:
            if st.button("✨ Update Resume with Missing Keywords", type="primary", use_container_width=True, key=f"btn_do_tailor_{job_key}"):
                extra_kws = [k.strip() for k in custom_kw_input.split(",") if k.strip()]
                final_kws = list(dict.fromkeys(selected_tailor_kws + extra_kws))

                tailored_res, meta = resume_tailor.tailor_resume(
                    master_resume_text=master_text,
                    job=job,
                    parsed_jd=parsed_jd,
                    selected_keywords=final_kws,
                    update_current_role=up_cur_role,
                    update_summary=up_summary,
                    update_competencies=up_comp,
                    update_tools=up_tools,
                )

                impact = resume_tailor.evaluate_tailoring_impact(
                    original_resume_text=master_text,
                    tailored_resume_text=tailored_res,
                    parsed_jd=parsed_jd,
                    role_title=job.title,
                )

                st.session_state[f"tailored_draft_content_{job_key}"] = tailored_res
                st.session_state[f"tailored_impact_{job_key}"] = impact
                st.session_state[f"tailored_meta_{job_key}"] = meta
                st.session_state[sess_tailor_kws_key] = selected_tailor_kws
                st.rerun()

        with btn_t2:
            if st.button("🔄 Reset to Baseline Draft", use_container_width=True, key=f"btn_reset_tailor_{job_key}"):
                st.session_state.pop(f"tailored_draft_content_{job_key}", None)
                st.session_state.pop(f"tailored_impact_{job_key}", None)
                st.session_state.pop(f"tailored_meta_{job_key}", None)
                st.rerun()

        # If tailored draft is not cached in session state, create initial baseline
        if f"tailored_draft_content_{job_key}" not in st.session_state:
            init_tailored, init_meta = resume_tailor.tailor_resume(
                master_resume_text=master_text,
                job=job,
                parsed_jd=parsed_jd,
                selected_keywords=default_selected,
                update_current_role=True,
                update_summary=True,
                update_competencies=True,
                update_tools=True,
            )
            st.session_state[f"tailored_draft_content_{job_key}"] = init_tailored
            st.session_state[f"tailored_meta_{job_key}"] = init_meta

        active_tailored_text = st.session_state[f"tailored_draft_content_{job_key}"]
        active_impact = st.session_state.get(f"tailored_impact_{job_key}")
        active_meta = st.session_state.get(f"tailored_meta_{job_key}")

        if active_impact:
            st.success(
                f"🚀 **ATS Score Boost: {active_impact['original_readiness']:.0f}% ➔ {active_impact['tailored_readiness']:.0f}% "
                f"(+{active_impact['readiness_delta']}%)** · Critical Coverage: **{active_impact['tailored_critical_coverage']:.0f}%** "
                f"· Important Coverage: **{active_impact['tailored_important_coverage']:.0f}%**"
            )
            if active_impact.get("newly_covered_keywords"):
                st.caption(f"✅ **Newly Covered Keywords in Resume:** {', '.join(active_impact['newly_covered_keywords'][:8])}")

        if active_meta and active_meta.get("current_role_bullets_after"):
            with st.expander("🔍 View Current Role (Bell Canada) Experience Updates", expanded=False):
                st.markdown("**Current Role Bullets Aligned to Missing Keywords:**")
                before_b = set(active_meta.get("current_role_bullets_before", []))
                for b in active_meta["current_role_bullets_after"]:
                    prefix = "🆕 " if b not in before_b else "• "
                    st.markdown(f"{prefix}{b}")

        # Live Editable Text Area
        edited_tailored_draft = st.text_area(
            "Tailored Resume Draft Content (Live Editable):",
            value=active_tailored_text,
            height=480,
            key=f"tailored_resume_preview_{job_key}",
        )
        st.session_state[f"tailored_draft_content_{job_key}"] = edited_tailored_draft

        # Export & Save Actions
        st.markdown("##### 📥 Export & Save Tailored Resume")
        dcol1, dcol2, dcol3, dcol4 = st.columns(4)
        with dcol1:
            docx_data = document_handler.create_docx(edited_tailored_draft, f"{job.company} Tailored Resume")
            st.download_button(
                label="📄 Download Word (.docx)",
                data=docx_data,
                file_name=f"Elena_Shchetinina_{job.company.replace(' ', '_')}_Resume.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                use_container_width=True,
            )
        with dcol2:
            pdf_data = document_handler.create_pdf(edited_tailored_draft, f"{job.company} Tailored Resume")
            st.download_button(
                label="📑 Download PDF (.pdf)",
                data=pdf_data,
                file_name=f"Elena_Shchetinina_{job.company.replace(' ', '_')}_Resume.pdf",
                mime="application/pdf",
                use_container_width=True,
            )
        with dcol3:
            st.download_button(
                label="📝 Download Markdown (.md)",
                data=edited_tailored_draft,
                file_name=f"Elena_Shchetinina_{job.company.replace(' ', '_')}_Resume.md",
                mime="text/markdown",
                use_container_width=True,
            )
        with dcol4:
            if st.button("💾 Save as Master Resume", use_container_width=True, help="Update data/master_resume.txt with these experience updates", key=f"btn_save_to_master_{job_key}"):
                save_master_resume(edited_tailored_draft)
                st.session_state["resume_just_saved"] = True
                st.toast("✅ Master Resume successfully updated with tailored experience!", icon="💾")
                st.rerun()

        st.divider()
        st.markdown("##### 🚀 Apply Directly on Company Site")
        st.caption("Submit your tailored Word (.docx) or PDF (.pdf) resume directly on the company's portal to bypass LinkedIn Easy Apply.")

        sub_col1, sub_col2 = st.columns([1, 1])
        with sub_col1:
            if has_company_url:
                st.link_button("🌐 Open Company Application Page", raw_url, type="primary", use_container_width=True)
            else:
                st.link_button("🌐 Open Role on Company Site (Direct Search)", google_search_url, type="primary", use_container_width=True)
        with sub_col2:
            st.link_button(f"🏢 Search {company_name} Career Portal", portal_search_url, use_container_width=True)

    with tab_raw:
        st.markdown(f"**Full Job Description** ({len(brief.job.description):,} characters):")
        st.text_area(
            "Raw JD Content",
            value=brief.job.description,
            height=400,
            disabled=True,
            label_visibility="collapsed",
            key=f"raw_jd_view_{brief.job.id or 'current'}",
        )


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 🎯 Job Search Agent")
    st.caption("Evidence-grounded · Human-in-the-loop")
    st.divider()
    nav_screens = [
        "🔭 Scout",
        "🎯 Coordinator",
        "👥 People & Outreach",
        "📋 Application Record",
        "📊 Dashboard",
        "🔍 Analyze Job",
        "📄 Master Resume",
    ]
    target_screen = st.session_state.pop("nav_screen", None)
    if target_screen and target_screen in nav_screens:
        st.session_state["nav_screen_radio"] = target_screen

    def _format_nav(item: str) -> str:
        if item in ("🔍 Analyze Job", "📄 Master Resume"):
            return f"📎 {item} (Appendix)"
        return item

    nav_captions = [
        "Discovery & suitability",
        "Pipeline orchestration",
        "Hiring team & messaging",
        "Submission tracker",
        "Funnel & metrics",
        "Appendix · Supporting tool",
        "Appendix · Supporting tool",
    ]

    screen = st.radio(
        "Navigation",
        nav_screens,
        format_func=_format_nav,
        captions=nav_captions,
        label_visibility="collapsed",
        key="nav_screen_radio",
    )
    st.divider()

    try:
        stats = repo.get_dashboard_stats()
        st.metric("Total Jobs Analyzed", stats["total_jobs"])
        st.metric("Avg ATS Readiness", f"{stats['avg_ats_readiness']:.0f}%")
        if stats["outreach_pending"]:
            st.warning(f"⏳ {stats['outreach_pending']} outreach pending approval")
            with st.expander("👀 View Pending Contacts", expanded=False):
                try:
                    from app.db.database import get_session, OutreachDB, JobDB
                    s = get_session()
                    pending_list = (
                        s.query(OutreachDB, JobDB)
                        .join(JobDB, OutreachDB.job_id == JobDB.id)
                        .filter(OutreachDB.approval_status == "pending")
                        .all()
                    )
                    for o_row, j_row in pending_list:
                        st.markdown(f"• **{o_row.person_name}**")
                        st.caption(f"  *{j_row.company}*")
                    s.close()
                except Exception:
                    pass
    except Exception:
        pass

    # Scout sidebar stats
    try:
        _scout_store_path = Path(__file__).resolve().parent.parent.parent / "data" / "scout" / "jobs.json"
        if _scout_store_path.exists():
            _sdata = json.loads(_scout_store_path.read_text(encoding="utf-8"))
            _sjobs = [j for j in _sdata.get("jobs", {}).values() if j.get("status") == "open"]
            _t1 = sum(1 for j in _sjobs if j.get("tier") == "tier_1")
            _t2 = sum(1 for j in _sjobs if j.get("tier") == "tier_2")
            st.metric("🔭 Scout Matches", f"{len(_sjobs)} open", delta=f"T1:{_t1} T2:{_t2}")
    except Exception:
        pass

    with st.expander("⚙️ Email / SMTP Settings", expanded=True):
        render_smtp_config_form(key_prefix="sidebar")

    st.divider()
    st.caption(f"DB: `{settings.database_url}`")
    st.caption("v0.2.0 · Phase A MVP")


# =============================================================================
# Screen 1: Analyze Job
# =============================================================================
if screen == "🔍 Analyze Job":
    # Ensure session state form keys exist
    if "form_counter" not in st.session_state:
        st.session_state["form_counter"] = 0
    if "form_company" not in st.session_state:
        st.session_state["form_company"] = ""
    if "form_title" not in st.session_state:
        st.session_state["form_title"] = ""
    if "form_location" not in st.session_state:
        st.session_state["form_location"] = ""
    if "form_url" not in st.session_state:
        st.session_state["form_url"] = ""
    if "form_work_model" not in st.session_state:
        st.session_state["form_work_model"] = ""
    if "form_country" not in st.session_state:
        st.session_state["form_country"] = ""
    if "form_jd" not in st.session_state:
        st.session_state["form_jd"] = ""

    if "load_job_id" in st.session_state:
        load_jid = st.session_state.pop("load_job_id")
        loaded_brief = repo.get_brief_for_job(load_jid)
        if loaded_brief:
            st.session_state["form_company"] = (loaded_brief.job.company or "").strip()
            st.session_state["form_title"] = (loaded_brief.job.title or "").strip()
            st.session_state["form_location"] = loaded_brief.job.location or ""
            st.session_state["form_url"] = loaded_brief.job.source_url or loaded_brief.job.official_url or ""
            st.session_state["form_work_model"] = loaded_brief.job.work_model or ""
            st.session_state["form_country"] = loaded_brief.job.country or ""
            st.session_state["form_jd"] = loaded_brief.job.description or ""
            st.session_state["form_counter"] = st.session_state.get("form_counter", 0) + 1
            st.session_state["last_brief"] = loaded_brief
        else:
            loaded_job = repo.get_job(load_jid)
            if loaded_job:
                st.session_state["form_company"] = (loaded_job.company or "").strip()
                st.session_state["form_title"] = (loaded_job.title or "").strip()
                st.session_state["form_location"] = loaded_job.location or ""
                st.session_state["form_url"] = loaded_job.source_url or loaded_job.official_url or ""
                st.session_state["form_work_model"] = loaded_job.work_model or ""
                st.session_state["form_country"] = loaded_job.country or ""
                st.session_state["form_jd"] = loaded_job.description or ""
                st.session_state["form_counter"] = st.session_state.get("form_counter", 0) + 1

    def reset_analyze_screen():
        st.session_state["form_counter"] = st.session_state.get("form_counter", 0) + 1
        st.session_state["form_company"] = ""
        st.session_state["form_title"] = ""
        st.session_state["form_location"] = ""
        st.session_state["form_url"] = ""
        st.session_state["form_work_model"] = ""
        st.session_state["form_country"] = ""
        st.session_state["form_jd"] = ""
        st.session_state.pop("last_brief", None)

    head_col1, head_col2 = st.columns([5, 1])
    with head_col1:
        st.title("🔍 Analyze Job")
        st.caption(
            "**Appendix · Supporting Tool** — In-depth job qualification and fit analysis (Parse → Hard Gates → Strategic Fit → ATS Keywords → Evidence Map). "
            "Connected directly to your **🎯 Coordinator** pipeline to approve, skip, or queue roles."
        )
    with head_col2:
        st.write("")
        st.write("")
        if st.button("🧹 Clear Screen", key="btn_clear_screen_top", use_container_width=True, help="Clear form inputs and previous analysis results"):
            reset_analyze_screen()
            st.rerun()

    # ── Auto-analyze: triggered from Scout 'Tailor Resume' button ──────────
    if st.session_state.pop("auto_analyze", False):
        _aa_company = st.session_state.get("form_company", "")
        _aa_title   = st.session_state.get("form_title", "")
        _aa_jd      = st.session_state.get("form_jd", "")
        _aa_loc     = st.session_state.get("form_location", "")
        _aa_url     = st.session_state.get("form_url", "")
        if _aa_company and _aa_title and _aa_jd.strip():
            with st.spinner(f"⏳ Running analysis for **{_aa_company} — {_aa_title}**…"):
                try:
                    _aa_brief = process_job(
                        jd_text=_aa_jd,
                        company=_aa_company,
                        title=_aa_title,
                        location=_aa_loc or None,
                        url=_aa_url or None,
                    )
                    st.session_state["last_brief"] = _aa_brief
                    st.success(f"✅ Analysis complete — scroll down to **📄 Tailored Resume Draft** tab below.")
                except Exception as _aa_exc:
                    st.error(f"Pipeline error: {_aa_exc}")
                    st.exception(_aa_exc)
            if "last_brief" in st.session_state:
                st.info("⬇️ Your tailored resume is ready. Click the **📄 Tailored Resume Draft** tab below.")
                _render_brief(st.session_state["last_brief"])
            st.stop()

    work_model_options = ["", "remote", "hybrid", "on-site"]
    current_wm = st.session_state["form_work_model"]
    wm_index = work_model_options.index(current_wm) if current_wm in work_model_options else 0

    country_options = ["", "Canada", "United States"]
    current_country = (st.session_state.get("form_country") or "").strip()
    if current_country.upper() in ("CA", "CAN"):
        current_country = "Canada"
    elif current_country.upper() in ("US", "USA", "U.S.", "UNITED STATES"):
        current_country = "United States"
    c_index = country_options.index(current_country) if current_country in country_options else 0

    form_id = f"analyze_job_form_{st.session_state['form_counter']}"
    with st.form(form_id):
        col1, col2 = st.columns(2)
        with col1:
            company = st.text_input(
                "Company *",
                value=st.session_state["form_company"],
                placeholder="e.g. Shopify",
            )
            title = st.text_input(
                "Job Title *",
                value=st.session_state["form_title"],
                placeholder="e.g. Senior Technical Program Manager",
            )
        with col2:
            location = st.text_input(
                "Location",
                value=st.session_state["form_location"],
                placeholder="e.g. Toronto, ON (Remote)",
            )
            url = st.text_input(
                "Source URL",
                value=st.session_state["form_url"],
                placeholder="https://careers.company.com/job/...",
            )
            work_model = st.selectbox("Work Model", work_model_options, index=wm_index)
            country = st.selectbox("Country", country_options, index=c_index)

        jd_text = st.text_area(
            "Job Description *",
            value=st.session_state["form_jd"],
            height=320,
            placeholder="Paste the full job description here…",
        )
        write_excel = st.checkbox("Update Excel tracker", value=True)

        btn_c1, btn_c2 = st.columns([3, 1])
        with btn_c1:
            submitted = st.form_submit_button("🚀 Run Analysis", type="primary", use_container_width=True)
        with btn_c2:
            cleared = st.form_submit_button("🧹 Clear Form", use_container_width=True)

    if cleared:
        reset_analyze_screen()
        st.rerun()

    if submitted:
        # Persist form inputs in session state so they never vanish
        st.session_state["form_company"] = company
        st.session_state["form_title"] = title
        st.session_state["form_location"] = location
        st.session_state["form_url"] = url
        st.session_state["form_work_model"] = work_model
        st.session_state["form_country"] = country
        st.session_state["form_jd"] = jd_text

        if not company or not title or not jd_text.strip():
            st.error("Company, Job Title, and Job Description are required.")
        else:
            with st.spinner("Running qualification pipeline…"):
                try:
                    brief = process_job(
                        jd_text=jd_text,
                        company=company,
                        title=title,
                        location=location or None,
                        url=url or None,
                        work_model=work_model or None,
                        country=country or None,
                        write_excel=write_excel,
                    )
                    st.session_state["last_brief"] = brief
                    st.success(f"✅ Analysis complete — Job ID: {brief.job.id}")
                except Exception as exc:
                    st.error(f"Pipeline error: {exc}")
                    st.exception(exc)
                    brief = None

            if brief:
                _render_brief(brief)

    elif "last_brief" in st.session_state:
        st.info("Showing last analyzed job. Submit a new JD to re-analyze.")
        _render_brief(st.session_state["last_brief"])


# =============================================================================
# Screen 2: People & Outreach
# =============================================================================
elif screen == "👥 People & Outreach":
    st.title("👥 People & Outreach")
    st.caption(
        "Add hiring chain contacts, generate evidence-grounded drafts, "
        "and approve/edit/skip each message. No message is sent automatically."
    )

    jobs = repo.list_jobs(limit=50)
    if not jobs:
        st.info("No jobs found. Analyze a job first.")
        st.stop()

    job_options = {f"{j.company} — {j.title} (ID:{j.id})": j.id for j in jobs}
    default_job_idx = 0
    target_outreach_jid = st.session_state.pop("selected_outreach_job_id", None)
    if target_outreach_jid:
        for idx, (lbl, jid) in enumerate(job_options.items()):
            if jid == target_outreach_jid:
                default_job_idx = idx
                break

    selected_label = st.selectbox("Select Job", list(job_options.keys()), index=default_job_idx)
    selected_job_id = job_options[selected_label]
    selected_job = next(j for j in jobs if j.id == selected_job_id)

    st.markdown(
        f"**Target Vacancy:** **{selected_job.company}** — *{selected_job.title}* "
        f"| 📍 {selected_job.location or 'Location open'} | 🏷️ {selected_job.role_family or 'Technical Program Management'}"
    )

    app_rec = repo.get_application_for_job(selected_job_id)
    if app_rec and app_rec.status == "applied":
        applied_date_str = app_rec.applied_at.strftime('%B %d, %Y') if app_rec.applied_at else "Recently"
        channel_name = app_rec.channel.replace('_', ' ').title() if app_rec.channel else "Company Site"
        rel_time = f" ({format_relative_time(app_rec.applied_at)})" if app_rec.applied_at else ""
        st.success(
            f"📬 **Application Status: Applied via {channel_name} on {applied_date_str}{rel_time}** "
            f"· Confirmed via LinkedIn · Reaching out to recruiters and hiring managers now is ideal!"
        )
    elif app_rec and app_rec.status != "draft":
        st.info(f"📋 **Application Status:** {app_rec.status.title()}")

    st.divider()

    if "people_flash_msg" in st.session_state:
        st.success(st.session_state.pop("people_flash_msg"))

    people = repo.get_people_for_job(selected_job_id)
    outreach_records = repo.get_outreach_for_job(selected_job_id)
    evidence = load_evidence()
    outreach_map = {r.person_id: r for r in outreach_records if r.person_id}

    pending_records = [r for r in outreach_records if r.approval_status == OutreachApproval.pending]
    pending_count = len(pending_records)
    approved_count = sum(1 for r in outreach_records if r.approval_status == OutreachApproval.approved)

    tab_approval, tab_discovery = st.tabs([
        f"📬 Outreach Review & Approval ({pending_count} pending)",
        f"🤖 Automatic Contact Discovery & Sourcing",
    ])

    # ═════════════════════════════════════════════════════════════════════════
    # TAB 1: OUTREACH REVIEW & APPROVAL QUEUE
    # ═════════════════════════════════════════════════════════════════════════
    with tab_approval:
        st.markdown(f"### 📬 Outreach Review Queue ({pending_count} Pending)")
        st.caption(
            "Review personalized, evidence-grounded outreach messages. "
            "Approve messages to mark them ready for sending, or edit them directly."
        )

        contacted_count = sum(1 for r in outreach_records if r.contacted_at is not None)
        m1, m2, m3, m4, m5 = st.columns([1, 1, 1, 1, 2])
        with m1:
            st.metric("Total Contacts", len(people))
        with m2:
            st.metric("⏳ Pending Approval", pending_count)
        with m3:
            st.metric("✅ Approved", approved_count)
        with m4:
            st.metric("📨 Sent via Email", contacted_count)
        with m5:
            if pending_count > 0:
                if st.button("⚡ Approve All Pending Messages", type="primary", use_container_width=True, key=f"btn_appr_all_{selected_job_id}"):
                    for rec in pending_records:
                        repo.update_outreach_status(rec.id, OutreachApproval.approved, edited_draft=rec.draft)
                    st.success(f"✅ Approved all {pending_count} pending outreach messages!")
                    st.rerun()

        st.divider()

        if not people:
            st.info(
                f"ℹ️ **No contacts in hiring chain for {selected_job.company} yet.** "
                "Switch to the **'🤖 Automatic Contact Discovery & Sourcing'** tab to search for stakeholders, or add verified contacts manually below."
            )
        else:
            for person in sorted(people, key=lambda p: p.outreach_priority):
                draft_rec = outreach_map.get(person.id)
                status_val = draft_rec.approval_status.value if draft_rec else "no draft"
                
                if draft_rec and draft_rec.contacted_at:
                    status_badge = "📨 Sent via Email"
                else:
                    status_badge = {
                        "approved": "✅ Approved",
                        "edited": "✏️ Edited",
                        "skipped": "⏭️ Skipped",
                        "pending": "⏳ Pending Approval",
                    }.get(status_val, "❓ No Draft")

                prio_icons = {1: "🥇", 2: "🥈", 3: "👥", 4: "🏛️"}
                prio_icon = prio_icons.get(person.outreach_priority, "📌")

                with st.container():
                    p_col1, p_col2 = st.columns([3, 1])
                    with p_col1:
                        role_label = person.person_type.value.replace("_", " ").title()
                        st.markdown(
                            f"#### {prio_icon} Priority #{person.outreach_priority} · **{person.name}** "
                            f"<span class='evidence-tag'>{role_label}</span> "
                            f"<span style='background:#1e293b;border:1px solid #475569;color:#94a3b8;border-radius:6px;padding:2px 8px;font-size:0.75rem'>Suggested / Inferred Lead</span>",
                            unsafe_allow_html=True,
                        )
                        st.markdown(f"**Title:** *{person.current_title}* at **{person.company}**")
                        st.caption(f"📌 **Role Relationship:** {person.relationship_to_job}")
                        if person.source_url:
                            st.markdown(f"[🔗 View LinkedIn Profile / Directory]({person.source_url})")

                        with st.expander("⚙️ Adjust Role Archetype or Priority", expanded=False):
                            ec1, ec2, ec3 = st.columns([2, 1, 1])
                            with ec1:
                                type_vals = [e.value for e in PersonType]
                                cur_t_idx = type_vals.index(person.person_type.value) if person.person_type.value in type_vals else 0
                                new_t = st.selectbox("Role Archetype", type_vals, index=cur_t_idx, key=f"edit_ptype_{person.id}")
                            with ec2:
                                new_p = st.number_input("Priority", min_value=1, max_value=99, value=person.outreach_priority, key=f"edit_prio_{person.id}")
                            with ec3:
                                st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
                                if st.button("💾 Save", key=f"btn_save_role_{person.id}", use_container_width=True):
                                    updated_person = person.model_copy(update={
                                        "person_type": PersonType(new_t),
                                        "outreach_priority": int(new_p),
                                    })
                                    repo.save_person(selected_job_id, updated_person)
                                    st.session_state["people_flash_msg"] = f"✅ Updated {person.name}'s role to **{new_t}** (Priority #{new_p})."
                                    st.rerun()

                    with p_col2:
                        st.markdown(f"**Approval Status:** `{status_badge}`")
                        if not draft_rec:
                            if st.button("➕ Generate Draft", key=f"gen_draft_{person.id}", type="primary", use_container_width=True):
                                rec = message_generator.build_draft(job=selected_job, person=person, evidence=evidence)
                                rec = rec.model_copy(update={
                                    "job_id": selected_job_id,
                                    "person_id": person.id,
                                    "recipient_email": email_service.suggest_email_for_contact(person.name, person.company),
                                    "subject": email_service.generate_email_subject(selected_job.title, candidate_name=cand_name, company=selected_job.company),
                                })
                                repo.save_outreach(rec)
                                st.rerun()
                        if st.button("🗑️ Remove Contact", key=f"del_person_{person.id}", help=f"Remove {person.name} from hiring chain", use_container_width=True):
                            repo.delete_person(person.id)
                            st.session_state["people_flash_msg"] = f"🗑️ Removed **{person.name}** from hiring chain."
                            st.rerun()

                    if draft_rec:
                        st.markdown("**Draft Outreach Message:**")
                        raw_draft = draft_rec.draft or ""
                        first_name = (person.name.split()[0] if person.name else "").strip()
                        if first_name.lower() in ("talent", "recruiter", "hiring", "manager"):
                            from app.services.message_generator import get_contact_first_name
                            first_name = get_contact_first_name(person.name)

                        # Clean any legacy generic greeting if present
                        if "Hi Talent," in raw_draft or "Hi Talent Acquisition," in raw_draft:
                            raw_draft = re.sub(r"^Hi Talent( Acquisition)?,", f"Hi {first_name},", raw_draft)
                            repo.update_outreach_status(draft_rec.id, draft_rec.approval_status, edited_draft=raw_draft)

                        sess_key = f"edit_draft_{draft_rec.id}"
                        if sess_key in st.session_state and "Hi Talent," in str(st.session_state[sess_key]):
                            st.session_state[sess_key] = re.sub(r"^Hi Talent( Acquisition)?,", f"Hi {first_name},", st.session_state[sess_key])

                        edited_text = st.text_area(
                            f"Message draft for {person.name}:",
                            value=raw_draft,
                            height=180,
                            key=sess_key,
                            label_visibility="collapsed",
                        )
                        if draft_rec.evidence_ids:
                            ev_tags = " ".join(f"<span class='evidence-tag'>{eid}</span>" for eid in draft_rec.evidence_ids)
                            st.markdown(f"Verified Evidence Grounding: {ev_tags}", unsafe_allow_html=True)
                        
                        btn_c1, btn_c2, btn_c3 = st.columns([2, 2, 2])
                        with btn_c1:
                            if st.button(
                                "✅ Approve",
                                key=f"appr_{draft_rec.id}",
                                type="primary" if draft_rec.approval_status != OutreachApproval.approved else "secondary",
                                disabled=draft_rec.approval_status == OutreachApproval.approved,
                                use_container_width=True,
                            ):
                                repo.update_outreach_status(draft_rec.id, OutreachApproval.approved, edited_draft=edited_text)
                                st.success(f"Approved message for {person.name}!")
                                st.rerun()
                        with btn_c2:
                            if st.button("💾 Save Edits", key=f"save_edit_{draft_rec.id}", use_container_width=True):
                                repo.update_outreach_status(draft_rec.id, OutreachApproval.edited, edited_draft=edited_text)
                                st.success("Saved message edits!")
                                st.rerun()
                        with btn_c3:
                            if st.button("⏭️ Skip", key=f"skip_btn_{draft_rec.id}", use_container_width=True):
                                repo.update_outreach_status(draft_rec.id, OutreachApproval.skipped)
                                st.info("Marked as skipped.")
                                st.rerun()

                        # ── IN-APP EMAIL DISPATCH CENTER ──
                        st.markdown("---")
                        st.markdown(f"##### 📨 Send Email to {person.name} Directly from Application")

                        is_approved = (draft_rec.approval_status == OutreachApproval.approved)

                        suggested_email = (
                            getattr(person, "email", None)
                            or getattr(draft_rec, "recipient_email", None)
                            or email_service.suggest_email_for_contact(person.name, person.company)
                        )
                        suggested_subj = (
                            getattr(draft_rec, "subject", None)
                            or email_service.generate_email_subject(
                                selected_job.title,
                                candidate_name=cand_name,
                                company=selected_job.company,
                            )
                        )

                        if draft_rec.contacted_at:
                            contacted_str = draft_rec.contacted_at.strftime("%Y-%m-%d %H:%M UTC") if hasattr(draft_rec.contacted_at, "strftime") else str(draft_rec.contacted_at)
                            st.success(
                                f"✅ **Email Sent via Application** on {contacted_str} to `{getattr(draft_rec, 'recipient_email', None) or suggested_email}`."
                            )
                        elif is_approved:
                            st.success("✅ **Message Approved**: Ready for direct email dispatch.")
                        else:
                            st.warning(
                                f"🔒 **Email Dispatch Locked**: {person.name} has not been approved yet ({status_badge}). "
                                "Review the message draft and click **'✅ Approve'** above before you can send an email."
                            )

                        e_col1, e_col2 = st.columns([1, 1])
                        with e_col1:
                            target_email = st.text_input(
                                "Recipient Work Email:",
                                value=suggested_email,
                                key=f"recip_email_{draft_rec.id}",
                                help=f"Inferred corporate address: {suggested_email}",
                            )
                        with e_col2:
                            target_subject = st.text_input(
                                "Email Subject:",
                                value=suggested_subj,
                                key=f"subj_email_{draft_rec.id}",
                            )

                        snd_col1, snd_col2, snd_col3 = st.columns([2, 2, 2])

                        with snd_col1:
                            btn_send_label = "🚀 Send Email Now" if is_approved else "🔒 Send Email (Approval Required)"
                            if st.button(
                                btn_send_label,
                                key=f"btn_send_now_{draft_rec.id}",
                                type="primary" if is_approved else "secondary",
                                disabled=not is_approved,
                                help="Send email directly via SMTP" if is_approved else "Approval required: Please review and click '✅ Approve' above first.",
                                use_container_width=True,
                            ):
                                if not is_approved or draft_rec.approval_status != OutreachApproval.approved:
                                    st.error(f"⛔ Security Violation: Cannot send email to {person.name} because outreach is not approved.")
                                    st.stop()

                                if not target_email or "@" not in target_email:
                                    st.error("Please provide a valid recipient email address.")
                                else:
                                    cfg = email_service.load_saved_email_config()
                                    if not cfg.get("smtp_host") or not cfg.get("smtp_username") or not cfg.get("smtp_password"):
                                        st.warning("⚠️ SMTP credentials not fully configured. Expand '⚙️ Configure SMTP Server' below or in the sidebar to add your email credentials, or use '🧪 Simulated Send' to test.")
                                    else:
                                        with st.spinner(f"Connecting to SMTP server and sending to {target_email}..."):
                                            res = email_service.send_outreach_email(
                                                outreach=draft_rec,
                                                to_email=target_email,
                                                subject=target_subject,
                                                body=edited_text,
                                            )
                                            if res.success:
                                                repo.record_email_sent(draft_rec.id, recipient_email=target_email, subject=target_subject, sent_body=edited_text)
                                                p_email = getattr(person, "email", None)
                                                if target_email and (not p_email or p_email != target_email):
                                                    repo.update_person_email(person.id, target_email)
                                                st.success(f"🎉 Email successfully dispatched to {target_email}!")
                                                st.balloons()
                                                st.rerun()
                                            else:
                                                st.error(f"❌ Failed to dispatch email: {res.message}")

                        with snd_col2:
                            btn_sim_label = "🧪 Simulated Send (Test)" if is_approved else "🔒 Simulated Send (Approval Required)"
                            if st.button(
                                btn_sim_label,
                                key=f"btn_sim_send_{draft_rec.id}",
                                disabled=not is_approved,
                                help="Test email flow without live SMTP" if is_approved else "Approval required: Please review and click '✅ Approve' above first.",
                                use_container_width=True,
                            ):
                                if not is_approved or draft_rec.approval_status != OutreachApproval.approved:
                                    st.error(f"⛔ Security Violation: Cannot send simulated email to {person.name} because outreach is not approved.")
                                    st.stop()

                                if not target_email or "@" not in target_email:
                                    st.error("Please provide a valid recipient email address.")
                                else:
                                    res = email_service.send_outreach_email(
                                        outreach=draft_rec,
                                        to_email=target_email,
                                        subject=target_subject,
                                        body=edited_text,
                                        simulated=True,
                                    )
                                    if res.success:
                                        repo.record_email_sent(draft_rec.id, recipient_email=target_email, subject=target_subject, sent_body=edited_text)
                                        p_email = getattr(person, "email", None)
                                        if target_email and (not p_email or p_email != target_email):
                                            repo.update_person_email(person.id, target_email)
                                        st.success(f"🧪 [SIMULATION] Email prepared, validated, and logged as sent to {target_email}!")
                                        st.rerun()
                                    else:
                                        st.error(res.message)

                        with snd_col3:
                            if is_approved:
                                mailto_link = email_service.generate_mailto_link(target_email, target_subject, edited_text)
                                st.link_button("✉️ Open in Email App", mailto_link, use_container_width=True, help="Launch default desktop mail app (Mail, Outlook, etc.) with To, Subject, and Body filled.")
                            else:
                                st.button("🔒 Open in Email App", key=f"btn_mailto_dis_{draft_rec.id}", disabled=True, use_container_width=True, help="Approval required: Please review and click '✅ Approve' above first.")

                        with st.expander("⚙️ Configure SMTP Server for In-App Emailing", expanded=False):
                            render_smtp_config_form(key_prefix=f"card_{draft_rec.id}")
                    st.divider()

    # ═════════════════════════════════════════════════════════════════════════
    # TAB 2: AUTOMATIC DISCOVERY & SOURCING
    # ═════════════════════════════════════════════════════════════════════════
    with tab_discovery:
        st.markdown("### 🤖 Automatic Stakeholder Discovery & Sourcing Engine")
        st.caption(
            "Automatically scans company organizational charts, talent teams, and public profiles "
            "to discover hiring managers, recruiters, peers, and sponsors, and populates them into your review queue."
        )

        discovered_contacts = []
        if hasattr(linkedin_finder, "get_discovered_contacts"):
            try:
                discovered_contacts = linkedin_finder.get_discovered_contacts(selected_job)
            except Exception:
                discovered_contacts = []

        current_names = {p.name.strip().lower() for p in people}
        unadded_count = sum(1 for c in discovered_contacts if c["name"].strip().lower() not in current_names)

        # 1-Click Auto-Populate Banner
        if not discovered_contacts:
            st.info(
                f"ℹ️ **No verified contacts automatically discovered for {selected_job.company}.**\n\n"
                "Please use the targeted live **LinkedIn Search Strategies** or **Google X-Ray** queries below to identify real stakeholders, "
                "or paste an individual's LinkedIn profile in **Quick Import**."
            )
        else:
            disc_col1, disc_col2 = st.columns([3, 1])
            with disc_col1:
                st.info(
                    f"💡 **Discovery Engine Ready:** Identified **{len(discovered_contacts)} key stakeholders** "
                    f"for **{selected_job.company}** ({unadded_count} new to import)."
                )
            with disc_col2:
                if st.button("🚀 Auto-Populate All", type="primary", use_container_width=True, key=f"auto_pop_{selected_job_id}"):
                    added_names = []
                    for c in discovered_contacts:
                        if c["name"].strip().lower() not in current_names:
                            inferred_email = email_service.suggest_email_for_contact(c["name"], c["company"])
                            p_new = PersonTarget(
                                name=c["name"],
                                current_title=c["current_title"],
                                company=c["company"],
                                person_type=c["person_type"],
                                relationship_to_job=c["relationship_to_job"],
                                relationship_status="inferred",
                                confidence=c["confidence"],
                                source_url=c.get("source_url"),
                                checked_at=datetime.now(timezone.utc),
                                outreach_priority=c["priority"],
                                email=inferred_email,
                            )
                            pid = repo.save_person(selected_job_id, p_new)
                            rec = message_generator.build_draft(job=selected_job, person=p_new, evidence=evidence)
                            rec = rec.model_copy(update={
                                "job_id": selected_job_id,
                                "person_id": pid,
                                "recipient_email": inferred_email,
                                "subject": email_service.generate_email_subject(selected_job.title, candidate_name=cand_name, company=selected_job.company),
                            })
                            repo.save_outreach(rec)
                            added_names.append(c["name"])
                    if added_names:
                        st.session_state["people_flash_msg"] = f"🎉 Successfully added {len(added_names)} contacts and generated drafts for review!"
                    else:
                        st.info("All discovered stakeholders are already in the Hiring Chain.")
                    st.rerun()

        st.divider()

        st.markdown("#### 👥 Identified Stakeholders & Hiring Chain Targets")
        if not discovered_contacts:
            st.info(
                f"🔍 **No stakeholders discovered yet for {selected_job.company}.** "
                "Use the search links or Google X-Ray strategies below to find hiring managers and recruiters on LinkedIn."
            )
        else:
            for c in discovered_contacts:
                is_already_added = c["name"].strip().lower() in current_names
                inferred_email = email_service.suggest_email_for_contact(c["name"], c["company"])
                with st.container():
                    dcol1, dcol2 = st.columns([3, 1])
                    with dcol1:
                        badge_type = c["person_type"].value.replace("_", " ").title()
                        st.markdown(
                            f"**{c['name']}** — *{c['current_title']}* "
                            f"<span class='evidence-tag'>{badge_type}</span> · `Priority #{c['priority']}`",
                            unsafe_allow_html=True,
                        )
                        st.caption(f"📌 **Role Relationship:** {c['relationship_to_job']} | ✉️ `{inferred_email}`")
                        if c.get("source_url"):
                            st.markdown(f"[🔗 View LinkedIn Search Profile]({c['source_url']})")
                    with dcol2:
                        if is_already_added:
                            st.success("✅ In Hiring Chain")
                        else:
                            if st.button("➕ Add & Generate Draft", key=f"add_disc_{selected_job_id}_{c['name']}", type="primary", use_container_width=True):
                                p_new = PersonTarget(
                                    name=c["name"],
                                    current_title=c["current_title"],
                                    company=c["company"],
                                    person_type=c["person_type"],
                                    relationship_to_job=c["relationship_to_job"],
                                    relationship_status="inferred",
                                    confidence=c["confidence"],
                                    source_url=c.get("source_url"),
                                    checked_at=datetime.now(timezone.utc),
                                    outreach_priority=c["priority"],
                                    email=inferred_email,
                                    outreach_records=[],
                                )
                                pid = repo.save_person(selected_job_id, p_new)
                                rec = message_generator.build_draft(job=selected_job, person=p_new, evidence=evidence)
                                rec = rec.model_copy(update={
                                    "job_id": selected_job_id,
                                    "person_id": pid,
                                    "recipient_email": inferred_email,
                                    "subject": email_service.generate_email_subject(selected_job.title, candidate_name=cand_name, company=selected_job.company),
                                })
                                repo.save_outreach(rec)
                                st.session_state["people_flash_msg"] = f"✅ Added **{c['name']}** to Hiring Chain! Switch to **📬 Outreach Review & Approval** tab to view draft."
                                st.rerun()
                st.divider()

        # ── Quick Import from LinkedIn ─────────────────────────────────────────
        st.markdown("### ⚡ Quick Import from LinkedIn")
        st.caption(
            "Paste a LinkedIn profile URL (e.g. `https://www.linkedin.com/in/derek-smockum-449879164/`) or a copied profile snippet. "
            "The system will extract their name and generate a personalized outreach draft."
        )

        quick_input = st.text_area(
            "Paste LinkedIn Profile URL or Bio Snippet",
            placeholder="e.g. https://www.linkedin.com/in/derek-smockum-449879164/\nor\nDerek Smockum · 2nd | Senior Talent Acquisition Partner at Lightspeed",
            height=85,
            key=f"quick_li_input_{selected_job_id}",
        )

        if quick_input.strip():
            parsed = linkedin_finder.parse_linkedin_input(quick_input, default_company=selected_job.company)
            if parsed.get("error"):
                st.error(f"⚠️ **Cannot Import Organization / Company Page:**\n\n{parsed['error']}")
            else:
                raw_name = parsed.get("name", "")
                is_real = getattr(linkedin_finder, "is_real_person_name", lambda n: True)(raw_name)
                if not is_real and raw_name:
                    st.warning(
                        f"⚠️ **Notice:** The detected name `'{raw_name}'` looks like an organization or title rather than an individual person. "
                        "Please adjust the full name below."
                    )
                st.markdown("##### 👤 Detected Contact Details")
                st.caption("Review or adjust details below before adding to the hiring chain:")
                
                qi_col1, qi_col2 = st.columns([1, 1])
                with qi_col1:
                    imp_name = st.text_input("Name", value=raw_name, key=f"imp_name_{selected_job_id}")
                    imp_title = st.text_input(
                        "Current Title",
                        value=parsed.get("current_title", "") if parsed.get("current_title") != "Professional" else "",
                        placeholder="e.g. Senior Technical Program Manager or Recruiter",
                        key=f"imp_title_{selected_job_id}",
                    )
                with qi_col2:
                    type_options = [e.value for e in PersonType]
                    p_type_val = parsed.get("person_type", PersonType.hiring_manager)
                    p_type_str = p_type_val.value if hasattr(p_type_val, "value") else str(p_type_val)
                    type_idx = type_options.index(p_type_str) if p_type_str in type_options else 0
                    imp_type = st.selectbox("Role Archetype", type_options, index=type_idx, key=f"imp_type_{selected_job_id}")
                    imp_prio = st.number_input("Outreach Priority (1=first)", min_value=1, max_value=99, value=int(parsed.get("outreach_priority", 1)), key=f"imp_prio_{selected_job_id}")

                q_btn1, q_btn2 = st.columns([2, 3])
                with q_btn1:
                    if st.button("➕ Add to Hiring Chain & Generate Draft", type="primary", use_container_width=True, key=f"btn_add_quick_{selected_job_id}"):
                        final_name = imp_name.strip()
                        final_title = imp_title.strip() or "Professional"
                        if not getattr(linkedin_finder, "is_real_person_name", lambda n: True)(final_name):
                            st.error(f"❌ Cannot add '{final_name}' — this appears to be a company or organization, not an individual person.")
                        else:
                            person = PersonTarget(
                                name=final_name,
                                current_title=final_title,
                                company=parsed.get("company", selected_job.company),
                                person_type=PersonType(imp_type),
                                relationship_to_job=parsed.get("relationship_to_job", f"Key Contact at {selected_job.company}"),
                                relationship_status="inferred",
                                confidence=parsed.get("confidence", Confidence.medium),
                                source_url=parsed.get("source_url"),
                                checked_at=datetime.now(timezone.utc),
                                outreach_priority=int(imp_prio),
                            )
                            pid = repo.save_person(selected_job_id, person)
                            try:
                                rec = message_generator.build_draft(job=selected_job, person=person, evidence=evidence)
                                rec = rec.model_copy(update={"job_id": selected_job_id, "person_id": pid})
                                repo.save_outreach(rec)
                            except Exception:
                                pass
                            # Reset input field and store flash message
                            st.session_state[f"quick_li_input_{selected_job_id}"] = ""
                            st.session_state.pop(f"imp_name_{selected_job_id}", None)
                            st.session_state.pop(f"imp_title_{selected_job_id}", None)
                            st.session_state["people_flash_msg"] = f"✅ Added **{person.name}** ({person.current_title}) to Hiring Chain! Switch to the **📬 Outreach Review & Approval** tab to review and send."
                            st.rerun()

        st.divider()

        # ── Manual Add ────────────────────────────────────────────────────────
        with st.expander("🛠️ Manual Add / Custom Person", expanded=False):
            with st.form("add_person_form"):
                pc1, pc2, pc3 = st.columns(3)
                with pc1:
                    p_name = st.text_input("Full Name *")
                    p_title_input = st.text_input("Current Title *")
                with pc2:
                    p_type = st.selectbox("Person Type", [e.value for e in PersonType])
                    p_confidence = st.selectbox("Confidence", [e.value for e in Confidence])
                with pc3:
                    p_source = st.text_input("Source URL")
                    p_relationship = st.text_input("Relationship to Vacancy")
                    p_priority = st.number_input("Outreach Priority (1=first)", min_value=1, max_value=99, value=5)

                p_connection = st.text_input("Connection Path (optional)")
                add_person = st.form_submit_button("Add Person Manually", type="primary")

            if add_person:
                if not p_name or not p_title_input:
                    st.error("Name and title are required.")
                elif not getattr(linkedin_finder, "is_real_person_name", lambda n: True)(p_name.strip()):
                    st.error(f"❌ '{p_name}' appears to be a company or organization rather than an individual person. Please enter an actual individual's name.")
                else:
                    person = PersonTarget(
                        name=p_name.strip(),
                        current_title=p_title_input.strip(),
                        company=selected_job.company,
                        person_type=PersonType(p_type),
                        relationship_to_job=p_relationship or "Unknown",
                        relationship_status="inferred",
                        confidence=Confidence(p_confidence),
                        source_url=p_source or None,
                        checked_at=datetime.now(timezone.utc),
                        connection_path=p_connection or None,
                        outreach_priority=int(p_priority),
                    )
                    pid = repo.save_person(selected_job_id, person)
                    try:
                        rec = message_generator.build_draft(job=selected_job, person=person, evidence=evidence)
                        rec = rec.model_copy(update={"job_id": selected_job_id, "person_id": pid})
                        repo.save_outreach(rec)
                    except Exception:
                        pass
                    st.session_state["people_flash_msg"] = f"✅ Added **{person.name}** ({person.current_title}) to Hiring Chain! Switch to the **📬 Outreach Review & Approval** tab to review and send."
                    st.rerun()

        # ── Raw Boolean & X-Ray Search Reference ──────────────────────────────
        with st.expander("🔎 Raw Boolean & Google X-Ray Search Queries (Reference)", expanded=False):
            st.caption("Pre-configured Boolean queries for manual exploration on LinkedIn or Google:")
            strategies = linkedin_finder.build_search_strategies(selected_job)
            r1_col1, r1_col2 = st.columns(2)
            r2_col1, r2_col2 = st.columns(2)
            grid_cols = [r1_col1, r1_col2, r2_col1, r2_col2]
            for idx, strat in enumerate(strategies):
                with grid_cols[idx % len(grid_cols)]:
                    st.markdown(f"##### {strat.title}")
                    st.markdown(f"**Target:** `{strat.target_roles}`")
                    st.caption(strat.objective)
                    sc1, sc2 = st.columns([1, 1])
                    with sc1:
                        st.link_button("🔵 Open in LinkedIn", strat.linkedin_url, type="primary", use_container_width=True)
                    with sc2:
                        st.link_button("🔍 Google X-Ray Search", strat.google_xray_url, use_container_width=True)
                    st.code(strat.boolean_query, language="text")


# =============================================================================
# Screen 3: Application Record
# =============================================================================
elif screen == "📋 Application Record":
    st.title("📋 Master Application Tracker & Record")
    st.caption("Live synchronization with `Final_Job_Application_Tracker-5.xlsx` (Applications sheet) & SQLite.")

    # -------------------------------------------------------------------------
    # Cached Data Loader
    # -------------------------------------------------------------------------
    @st.cache_data(ttl=30)
    def _get_cached_applications_df():
        return tracker_service.load_applications_data()

    tracker_file = tracker_service.get_tracker_file_path()
    df_raw = _get_cached_applications_df()

    if df_raw.empty:
        st.warning(f"No application records found in `{tracker_file.name}`. Please verify the file path.")
        st.stop()

    # -------------------------------------------------------------------------
    # Header Action Buttons
    # -------------------------------------------------------------------------
    head_col1, head_col2, head_col3 = st.columns([1.5, 1.2, 1.3])
    with head_col1:
        if tracker_file.exists():
            st.download_button(
                "📥 Download Tracker (.xlsx)",
                data=tracker_file.read_bytes(),
                file_name=tracker_file.name,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                help="Download the latest Excel workbook with all 19 application tracking columns.",
                use_container_width=True,
            )
    with head_col2:
        if st.button("🔄 Refresh Tracker", help="Reload latest application data directly from disk", use_container_width=True):
            _get_cached_applications_df.clear()
            st.rerun()
    with head_col3:
        show_add_app = st.button("➕ Log New Application", help="Record a newly submitted application to the tracker", use_container_width=True)
        if show_add_app:
            st.session_state["show_add_app_form"] = not st.session_state.get("show_add_app_form", False)

    # -------------------------------------------------------------------------
    # Form: Log New Application Submitted Today
    # -------------------------------------------------------------------------
    if st.session_state.get("show_add_app_form", False):
        with st.container(border=True):
            st.markdown("##### ➕ Log New Application Submitted Today")
            st.caption("Add an application row directly into `Final_Job_Application_Tracker-5.xlsx` and SQLite.")
            with st.form("log_new_app_form"):
                n_c1, n_c2, n_c3 = st.columns(3)
                with n_c1:
                    new_app_date = st.date_input("Date Applied", value=datetime.now().date())
                    new_company = st.text_input("Company *", placeholder="e.g. Google, Anthropic, Cohere")
                    new_title = st.text_input("Role Title *", placeholder="e.g. Technical Program Manager")
                with n_c2:
                    new_level = st.selectbox("Seniority Level", ["Senior", "Staff", "Lead", "Director", "Principal", "Manager", "Mid-Level", "Other"])
                    new_country = st.selectbox("Country", ["US", "Canada", "Remote", "UK", "Other"])
                    new_city = st.text_input("City / Remote", placeholder="e.g. Toronto, ON or Remote")
                with n_c3:
                    new_channel = st.selectbox("Channel", ["Cold Portal", "LinkedIn", "LinkedIn Easy Apply", "Recruiter", "Agency", "Indeed", "Dice", "Referral", "Company Site", "Other"])
                    new_status = st.selectbox("Status", ["Applied", "Screening", "Interviewing", "Draft", "Offer", "Rejected"], index=0)
                    new_fit_score = st.number_input("Fit Score (%)", min_value=0, max_value=100, value=75)

                n_sub1, n_sub2 = st.columns(2)
                with n_sub1:
                    new_sponsorship = st.selectbox("Sponsorship Question?", ["Yes", "No", "Not Asked"], index=0)
                    new_contact = st.text_input("Referral / Contact Name", placeholder="e.g. Recruiter Name, Referral contact")
                with n_sub2:
                    new_next_act = st.text_input("Next Action", value="Follow up with recruiter and hiring team within 3-5 business days")

                new_app_notes = st.text_area("Notes", placeholder="Role context, salary range, mismatch drivers, team details...")
                submit_new_app = st.form_submit_button("🚀 Submit & Append to Master Tracker", type="primary", use_container_width=True)

                if submit_new_app:
                    if not new_company.strip() or not new_title.strip():
                        st.error("Company and Role Title are required.")
                    else:
                        new_record = {
                            "Date Applied": new_app_date,
                            "Company": new_company.strip(),
                            "Role Title": new_title.strip(),
                            "Level": new_level,
                            "Country": new_country,
                            "City / Remote": new_city.strip() or "Remote",
                            "Fit Score (%)": int(new_fit_score),
                            "Channel": new_channel,
                            "Referral / Contact Name": new_contact.strip() if new_contact else None,
                            "Sponsorship Question?": new_sponsorship,
                            "Status": new_status,
                            "Response Date": None,
                            "Days to Response": None,
                            "Next Action": new_next_act.strip() if new_next_act else None,
                            "Next Action Date": None,
                            "Notes": new_app_notes.strip() if new_app_notes else "",
                            "Interview/Screen Date(s)": None,
                            "Gap Category": None,
                            "Key Requirements": None,
                        }
                        try:
                            tracker_service.append_application_record(new_record)
                            # Also ensure a corresponding record in SQLite for pipeline continuity
                            try:
                                from app.models import JobRecord, WorkModel
                                job_rec = JobRecord(
                                    company=new_company.strip(),
                                    title=new_title.strip(),
                                    location=new_city.strip() or "Remote",
                                    country=new_country,
                                    work_model=WorkModel.REMOTE if "remote" in (new_city + new_country).lower() else WorkModel.HYBRID,
                                    jd_text=new_app_notes.strip() or f"Role: {new_title} at {new_company}",
                                    status="applied" if new_status.lower() == "applied" else "open",
                                )
                                created_id = repo.create_job(job_rec)
                                repo.update_application_status(
                                    job_id=created_id,
                                    status="applied" if new_status.lower() == "applied" else "draft",
                                    applied_at=datetime.combine(new_app_date, datetime.min.time()),
                                    channel=new_channel.lower().replace(" ", "_"),
                                    notes=new_app_notes.strip(),
                                    next_action=new_next_act.strip(),
                                )
                            except Exception as db_err:
                                logger.debug(f"Could not sync new app to SQLite: {db_err}")

                            _get_cached_applications_df.clear()
                            st.session_state["show_add_app_form"] = False
                            st.success(f"🎉 Successfully logged application for **{new_company}** on **{new_app_date}**!")
                            st.rerun()
                        except Exception as save_err:
                            st.error(f"Failed to append record to Excel: {save_err}")

    # -------------------------------------------------------------------------
    # Master KPI Executive Metrics Bar
    # -------------------------------------------------------------------------
    kpis = tracker_service.get_tracker_kpis(df_raw)

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("📋 Total Tracked", kpis["total"], help="Total applications across all historical and active pipelines")
    m2.metric(
        "📬 Active Pipeline",
        kpis["active_pipeline"],
        delta=f"{kpis['applied']} Applied · {kpis['screening'] + kpis['interviewing']} Screens",
        help="Applications actively in progress (Applied, Screening, Interviewing)",
    )
    m3.metric(
        "⚡ Submitted Last 30 Days",
        kpis["last_30_days"],
        delta=f"{kpis['last_7_days']} in last 7 days",
        help="Applications submitted in the most recent 30-day period",
    )
    m4.metric(
        "⏱️ Avg Days to Response",
        f"{kpis['avg_response_days']} d" if kpis["avg_response_days"] > 0 else "—",
        delta=f"Median {kpis['median_response_days']} d",
        help="Average calendar days between Date Applied and recruiter Response Date",
    )
    m5.metric(
        "🔴 Final Outcomes",
        f"{kpis['rejected']} Rej",
        delta=f"{kpis['ghosted']} Ghosted · {kpis['closed']} Closed",
        delta_color="inverse",
        help="Applications concluded as Rejected, Ghosted (30d+), or Closed",
    )

    st.divider()

    # -------------------------------------------------------------------------
    # Spreadsheet Toolbar: Multi-Faceted Filters & Search
    # -------------------------------------------------------------------------
    st.markdown("##### 🔍 Application Search & Filters")
    f_c1, f_c2, f_c3, f_c4, f_c5 = st.columns([2.0, 1.1, 1.2, 1.1, 1.2])

    with f_c1:
        search_kw = st.text_input("Search Applications", placeholder="Search company, title, location, notes, channel...", label_visibility="collapsed")
    with f_c2:
        status_opts = ["All Statuses", "🟢 Applied", "🟣 Screening", "🎯 Interviewing", "🔴 Rejected", "⚪ Ghosted (30d+)", "⚫ Closed"]
        sel_status = st.selectbox("Status Filter", status_opts, label_visibility="collapsed")
    with f_c3:
        timeline_opts = ["All Time", "⚡ Last 7 Days", "📅 Last 30 Days", "🗓️ Last 90 Days", "2026 Submissions", "2025 Submissions"]
        sel_timeline = st.selectbox("Submission Timeline", timeline_opts, label_visibility="collapsed")
    with f_c4:
        channel_opts = ["All Channels", "Cold Portal", "LinkedIn", "Recruiter", "Agency", "Indeed", "Dice", "Referral", "Other"]
        sel_channel = st.selectbox("Channel Filter", channel_opts, label_visibility="collapsed")
    with f_c5:
        sort_opts = [
            "📅 Date Applied (Newest First)",
            "📅 Date Applied (Oldest First)",
            "🏢 Company (A-Z)",
            "📊 Fit Score (High-Low)",
            "⏱️ Days to Response",
        ]
        sel_sort = st.selectbox("Sort Order", sort_opts, label_visibility="collapsed")

    # -------------------------------------------------------------------------
    # Apply Filtering to DataFrame
    # -------------------------------------------------------------------------
    filtered_df = df_raw.copy()

    # Text search
    if search_kw.strip():
        q = search_kw.strip().lower()
        match_mask = (
            filtered_df["Company"].astype(str).str.lower().str.contains(q)
            | filtered_df["Role Title"].astype(str).str.lower().str.contains(q)
            | filtered_df["City / Remote"].astype(str).str.lower().str.contains(q)
            | filtered_df["Country"].astype(str).str.lower().str.contains(q)
            | filtered_df["Notes"].astype(str).str.lower().str.contains(q)
            | filtered_df["Channel"].astype(str).str.lower().str.contains(q)
            | filtered_df["Next Action"].astype(str).str.lower().str.contains(q)
        )
        filtered_df = filtered_df[match_mask]

    # Status filter
    if sel_status != "All Statuses":
        clean_stat = sel_status.split(" ", 1)[-1].strip().lower()
        if "applied" in clean_stat:
            filtered_df = filtered_df[filtered_df["Status"].astype(str).str.lower() == "applied"]
        elif "screening" in clean_stat:
            filtered_df = filtered_df[filtered_df["Status"].astype(str).str.lower() == "screening"]
        elif "interview" in clean_stat:
            filtered_df = filtered_df[filtered_df["Status"].astype(str).str.lower().str.contains("interview")]
        elif "reject" in clean_stat:
            filtered_df = filtered_df[filtered_df["Status"].astype(str).str.lower().str.contains("reject")]
        elif "ghost" in clean_stat:
            filtered_df = filtered_df[filtered_df["Status"].astype(str).str.lower().str.contains("ghost")]
        elif "close" in clean_stat:
            filtered_df = filtered_df[filtered_df["Status"].astype(str).str.lower().str.contains("close")]

    # Timeline filter
    if sel_timeline != "All Time":
        max_dt = filtered_df["Date Applied Parsed"].dropna().max()
        ref_dt = max_dt if max_dt is not None else pd.Timestamp.now()
        if "7 Days" in sel_timeline:
            filtered_df = filtered_df[filtered_df["Date Applied Parsed"] >= (ref_dt - pd.Timedelta(days=7))]
        elif "30 Days" in sel_timeline:
            filtered_df = filtered_df[filtered_df["Date Applied Parsed"] >= (ref_dt - pd.Timedelta(days=30))]
        elif "90 Days" in sel_timeline:
            filtered_df = filtered_df[filtered_df["Date Applied Parsed"] >= (ref_dt - pd.Timedelta(days=90))]
        elif "2026" in sel_timeline:
            filtered_df = filtered_df[filtered_df["Date Applied Parsed"].dt.year == 2026]
        elif "2025" in sel_timeline:
            filtered_df = filtered_df[filtered_df["Date Applied Parsed"].dt.year == 2025]

    # Channel filter
    if sel_channel != "All Channels":
        c_filter = sel_channel.lower()
        filtered_df = filtered_df[filtered_df["Channel"].astype(str).str.lower().str.contains(c_filter)]

    # Sorting
    if "Date Applied (Newest First)" in sel_sort:
        filtered_df = filtered_df.sort_values(by="Date Applied Parsed", ascending=False, na_position="last")
    elif "Date Applied (Oldest First)" in sel_sort:
        filtered_df = filtered_df.sort_values(by="Date Applied Parsed", ascending=True, na_position="last")
    elif "Company (A-Z)" in sel_sort:
        filtered_df = filtered_df.sort_values(by="Company", ascending=True)
    elif "Fit Score" in sel_sort:
        filtered_df = filtered_df.sort_values(by="Fit Score (%)", ascending=False, na_position="last")
    elif "Days to Response" in sel_sort:
        filtered_df = filtered_df.sort_values(by="Days to Response", ascending=True, na_position="last")

    filtered_df = filtered_df.reset_index(drop=True)

    st.caption(f"Showing **{len(filtered_df)}** of **{len(df_raw)}** applications · Structure aligned with `Final-Excel-Spreadsheet Tracker -5`")

    # -------------------------------------------------------------------------
    # Spreadsheet Table View (st.dataframe)
    # -------------------------------------------------------------------------
    # Prepare display columns exactly mirroring the Excel spreadsheet
    display_df = pd.DataFrame()
    display_df["Date Applied"] = filtered_df["Date Applied Clean"]
    display_df["Company"] = filtered_df["Company"]
    display_df["Role Title"] = filtered_df["Role Title"]
    display_df["Level"] = filtered_df["Level"]
    display_df["Location"] = filtered_df.apply(
        lambda r: f"{r['City / Remote']}, {r['Country']}" if (r["Country"] and r["Country"] not in str(r["City / Remote"])) else str(r["City / Remote"]),
        axis=1,
    )
    display_df["Status"] = filtered_df["Status"]
    display_df["Channel"] = filtered_df["Channel"]
    display_df["Fit Score (%)"] = filtered_df["Fit Score (%)"].fillna(0).astype(int)
    display_df["Days to Resp"] = filtered_df["Days to Response"]
    display_df["Next Action"] = filtered_df["Next Action"]

    col_configs = {
        "Date Applied": st.column_config.DateColumn("📅 Date Applied", format="YYYY-MM-DD", width="small", help="Date the application was submitted"),
        "Company": st.column_config.TextColumn("🏢 Company", width="medium"),
        "Role Title": st.column_config.TextColumn("💼 Role Title", width="large"),
        "Level": st.column_config.TextColumn("🎖️ Level", width="small"),
        "Location": st.column_config.TextColumn("📍 Location / Remote", width="medium"),
        "Status": st.column_config.TextColumn("🎯 Status", width="small"),
        "Channel": st.column_config.TextColumn("📡 Channel", width="medium"),
        "Fit Score (%)": st.column_config.ProgressColumn("📊 Fit Score", min_value=0, max_value=100, format="%d%%", width="small"),
        "Days to Resp": st.column_config.NumberColumn("⏱️ Days Resp", format="%d", width="small", help="Days from application to initial response"),
        "Next Action": st.column_config.TextColumn("⚡ Next Action", width="medium"),
    }

    if filtered_df.empty:
        st.info("No applications match the selected filters. Clear or adjust your filters above.")
        st.stop()

    table_selection = st.dataframe(
        display_df,
        column_config=col_configs,
        use_container_width=True,
        height=450,
        selection_mode="single-row",
        on_select="rerun",
        key="master_application_tracker_dataframe",
    )

    st.caption("💡 **Click any application row above** to inspect full details, salary/mismatch notes, interview dates, or update application status.")

    # -------------------------------------------------------------------------
    # Resolve Selected Application Row
    # -------------------------------------------------------------------------
    selected_row_idx = 0
    if hasattr(table_selection, "selection") and table_selection.selection:
        raw_rows = table_selection.selection.get("rows", []) if isinstance(table_selection.selection, dict) else (table_selection.selection.rows or [])
        if raw_rows and raw_rows[0] < len(filtered_df):
            selected_row_idx = raw_rows[0]

    selected_app = filtered_df.iloc[selected_row_idx]

    # -------------------------------------------------------------------------
    # Application Detail Inspector & Action Center
    # -------------------------------------------------------------------------
    st.divider()

    # Submission date formatting and relative time calculation
    app_date_val = selected_app["Date Applied Clean"]
    rel_time_str = ""
    if app_date_val:
        from datetime import date
        diff_d = (date.today() - app_date_val).days
        if diff_d == 0:
            rel_time_str = "today"
        elif diff_d == 1:
            rel_time_str = "yesterday"
        elif diff_d < 7:
            rel_time_str = f"{diff_d} days ago"
        elif diff_d < 30:
            rel_time_str = f"{diff_d // 7} weeks ago"
        elif diff_d < 365:
            rel_time_str = f"{diff_d // 30} months ago"
        else:
            rel_time_str = f"{diff_d // 365} year(s) ago"

    sub_banner_date = f"📅 Submitted on **{app_date_val}**" if app_date_val else "📅 Submission Date: **Unspecified / Prior Tracker**"
    if rel_time_str:
        sub_banner_date += f" *({rel_time_str})*"

    # Status Pill style
    stat_val = str(selected_app["Status"])
    stat_color = "🟢" if "applied" in stat_val.lower() else ("🟣" if "screen" in stat_val.lower() else ("🎯" if "interview" in stat_val.lower() else ("🔴" if "reject" in stat_val.lower() else "⚪")))

    st.markdown(
        f"#### {stat_color} **{selected_app['Company']}** — {selected_app['Role Title']}\n"
        f"{sub_banner_date} · **Channel:** {selected_app['Channel'] or 'Direct'} · **Status:** {stat_val} · **Excel Row #{selected_app['_excel_row']}**"
    )

    det_tab1, det_tab2, det_tab3 = st.tabs(["📋 Full Record & Timeline", "✏️ Update Status & Notes", "🚀 Action Launchpad"])

    with det_tab1:
        d_col1, d_col2, d_col3 = st.columns(3)
        with d_col1:
            st.markdown("###### 📅 Submission Metadata")
            st.write(f"**Date Applied:** {selected_app['Date Applied Clean'] or '—'} ({rel_time_str or 'N/A'})")
            st.write(f"**Channel:** {selected_app['Channel'] or '—'}")
            st.write(f"**Sponsorship Question?:** {selected_app['Sponsorship Question?'] or 'Not Specified'}")
            st.write(f"**Referral / Contact:** {selected_app['Referral / Contact Name'] or 'None'}")
        with d_col2:
            st.markdown("###### ⏱️ Response & Pipeline Tracking")
            st.write(f"**Current Status:** {selected_app['Status'] or 'Applied'}")
            st.write(f"**Response Date:** {selected_app['Response Date Clean'] or 'Awaiting Response'}")
            resp_days_disp = f"{int(selected_app['Days to Response'])} days" if pd.notnull(selected_app['Days to Response']) else "Pending"
            st.write(f"**Days to Response:** {resp_days_disp}")
            st.write(f"**Interview Date(s):** {selected_app['Interview/Screen Date(s)'] or 'None'}")
        with d_col3:
            st.markdown("###### 📊 Fit & Next Action")
            fit_disp = f"{int(selected_app['Fit Score (%)'])}%" if pd.notnull(selected_app['Fit Score (%)']) else "—"
            st.write(f"**Fit Score:** {fit_disp}")
            st.write(f"**Level:** {selected_app['Level'] or '—'}")
            st.write(f"**Location:** {selected_app['City / Remote']} ({selected_app['Country'] or 'US'})")
            st.write(f"**Next Action:** {selected_app['Next Action'] or 'Follow up with hiring team'}")

        notes_content = selected_app["Notes"]
        if notes_content and str(notes_content).strip() and str(notes_content).strip() != "None":
            st.info(f"📝 **Application Notes & Intelligence:**\n\n{notes_content}")

        if selected_app["Key Requirements"] and str(selected_app["Key Requirements"]).strip() != "None":
            with st.expander("📌 Key Requirements Recorded in Tracker", expanded=False):
                st.write(selected_app["Key Requirements"])

    with det_tab2:
        st.markdown("##### ✏️ Update Application in Master Tracker")
        st.caption(f"Changes will be written directly to `Final_Job_Application_Tracker-5.xlsx` (Row #{selected_app['_excel_row']}).")

        with st.form(f"update_app_row_form_{selected_app['_excel_row']}"):
            up_c1, up_c2 = st.columns(2)
            with up_c1:
                cur_stat = str(selected_app["Status"]).strip()
                stat_options = ["Applied", "Screening", "Interviewing", "Offer", "Rejected", "Ghosted (30d+)", "Closed"]
                stat_idx = stat_options.index(cur_stat) if cur_stat in stat_options else 0
                new_stat_val = st.selectbox("Status", stat_options, index=stat_idx)

                cur_resp_dt = selected_app["Response Date Clean"]
                new_resp_dt_val = st.date_input("Response Date", value=cur_resp_dt if cur_resp_dt else None)

            with up_c2:
                new_next_act_val = st.text_input("Next Action", value=selected_app["Next Action"] if selected_app["Next Action"] else "")
                new_interview_dates = st.text_input("Interview/Screen Date(s)", value=selected_app["Interview/Screen Date(s)"] if selected_app["Interview/Screen Date(s)"] else "")

            new_notes_val = st.text_area("Notes", value=selected_app["Notes"] if selected_app["Notes"] else "", height=120)

            save_up_btn = st.form_submit_button("💾 Save Updates to Excel Tracker", type="primary", use_container_width=True)

            if save_up_btn:
                try:
                    tracker_service.update_application_record(
                        excel_row=int(selected_app["_excel_row"]),
                        status=new_stat_val,
                        response_date=new_resp_dt_val,
                        next_action=new_next_act_val,
                        notes=new_notes_val,
                    )
                    # Also sync to SQLite if linked
                    if selected_app["sqlite_job_id"]:
                        try:
                            repo.update_application_status(
                                job_id=int(selected_app["sqlite_job_id"]),
                                status=new_stat_val.lower(),
                                notes=new_notes_val,
                                next_action=new_next_act_val,
                            )
                        except Exception as sq_err:
                            logger.debug(f"SQLite sync note: {sq_err}")

                    _get_cached_applications_df.clear()
                    st.success(f"🎉 Updated record for **{selected_app['Company']}** in `Final_Job_Application_Tracker-5.xlsx`!")
                    st.rerun()
                except Exception as up_err:
                    st.error(f"Failed to update spreadsheet: {up_err}. If the file is open in Microsoft Excel, please save and close it first.")

    with det_tab3:
        st.markdown("##### 🚀 Application Launchpad & Agent Integration")

        import urllib.parse
        comp_clean = str(selected_app["Company"]).strip()
        title_clean = str(selected_app["Role Title"]).strip()
        search_query = f"{comp_clean} {title_clean} careers apply"
        google_url = f"https://www.google.com/search?q={urllib.parse.quote_plus(search_query)}"
        company_careers_url = f"https://www.google.com/search?q={urllib.parse.quote_plus(f'{comp_clean} careers jobs')}"

        act_col1, act_col2 = st.columns(2)
        with act_col1:
            st.link_button(f"🔍 Search Job Posting Online", google_url, type="primary", use_container_width=True)
        with act_col2:
            st.link_button(f"🏢 Search {comp_clean} Careers Portal", company_careers_url, use_container_width=True)

        sqlite_id = selected_app["sqlite_job_id"]
        if sqlite_id:
            st.markdown("###### 🤖 Connected Job Search Agent Workflows")
            btn_col1, btn_col2 = st.columns(2)
            with btn_col1:
                if st.button("📄 View Tailored Resume & Fit Analysis", key=f"btn_res_jump_{sqlite_id}", use_container_width=True):
                    st.session_state["load_job_id"] = int(sqlite_id)
                    st.session_state["nav_screen"] = "🔍 Analyze Job"
                    st.rerun()
            with btn_col2:
                if st.button(f"👥 Open Hiring Team & Outreach for {comp_clean}", key=f"btn_out_jump_{sqlite_id}", use_container_width=True):
                    st.session_state["selected_outreach_job_id"] = int(sqlite_id)
                    st.session_state["nav_screen"] = "👥 People & Outreach"
                    st.rerun()
        else:
            st.caption(f"💡 This job is tracked from the master Excel tracker. To generate tailored resumes or discover hiring managers with Job Search Agent, paste the job posting into **🔍 Analyze Job**.")



# =============================================================================
# Screen 4: Dashboard
# =============================================================================
elif screen == "📊 Dashboard":
    st.title("📊 Dashboard")
    st.caption("Aggregate metrics across all analyzed jobs.")

    try:
        stats = repo.get_dashboard_stats()
    except Exception as exc:
        st.error(f"Could not load stats: {exc}")
        stats = {}

    if not stats or stats.get("total_jobs", 0) == 0:
        st.info("No jobs analyzed yet. Run the pipeline on the 'Analyze Job' screen.")
    else:
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total Jobs Analyzed", stats["total_jobs"])
        m2.metric("Avg ATS Readiness", f"{stats['avg_ats_readiness']:.1f}%")
        m3.metric("Outreach Pending Approval", stats["outreach_pending"])
        m4.metric("Sync Conflicts Pending", stats["conflicts_pending"])

        st.divider()
        st.subheader("Jobs by Pursuit Tier")
        tiers = stats.get("by_tier", {})
        tier_display = {
            "tier_1": "🟢 Tier 1 (≥80)",
            "tier_2": "🟡 Tier 2 (70–79)",
            "tier_3": "🟠 Tier 3 (60–69)",
            "do_not_pursue": "🔴 Do Not Pursue (<60)",
            "barrier": "⚫ Barrier",
        }
        if tiers:
            cols = st.columns(len(tiers))
            for idx, (tier_val, count) in enumerate(tiers.items()):
                cols[idx].metric(tier_display.get(tier_val, tier_val), count)
        else:
            st.info("No fit scores computed yet.")

        st.divider()
        st.subheader("Recent Jobs & Pursuit Tiers")
        jobs = repo.list_jobs(limit=50)
        if jobs:
            import pandas as pd

            tier_display_map = {
                "tier_1": "🟢 Tier 1",
                "tier_2": "🟡 Tier 2",
                "tier_3": "🟠 Tier 3",
                "barrier": "⚫ Barrier",
                "do_not_pursue": "🔴 Do Not Pursue",
            }

            rows = []
            for j in jobs:
                app_r = repo.get_application_for_job(j.id)
                status_display = j.status.value
                if app_r and app_r.status == "applied":
                    app_dt = app_r.applied_at.strftime("%b %d") if app_r.applied_at else ""
                    status_display = f"🟢 Applied ({app_dt})" if app_dt else "🟢 Applied"
                elif app_r and app_r.status != "draft":
                    status_display = f"🔵 {app_r.status.title()}"

                fit_info = repo.get_fit_for_job(j.id)
                ats_info = repo.get_ats_for_job(j.id)

                tier_raw = fit_info.get("tier") if fit_info else None
                tier_badge = tier_display_map.get(tier_raw, "⚪ Unassigned") if tier_raw else "⚪ Unassigned"
                score_str = f"{fit_info['weighted_score']:.1f}" if (fit_info and fit_info.get("weighted_score") is not None) else "—"
                ats_str = f"{ats_info['readiness']:.1f}%" if (ats_info and ats_info.get("readiness") is not None) else "—"

                rows.append({
                    "ID": j.id,
                    "Company": j.company.strip(),
                    "Title": j.title.strip(),
                    "Pursuit Tier": tier_badge,
                    "Fit Score": score_str,
                    "ATS Readiness": ats_str,
                    "Location": j.location or "—",
                    "Application Status": status_display,
                    "Added": j.created_at.strftime("%Y-%m-%d") if j.created_at else "—",
                })
            df = pd.DataFrame(rows)
            st.dataframe(
                df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Pursuit Tier": st.column_config.TextColumn("Pursuit Tier", help="Strategic pursuit priority: Tier 1 (≥80), Tier 2 (70–79), Tier 3 (60–69), Barrier"),
                    "Fit Score": st.column_config.TextColumn("Fit Score (0–100)"),
                    "ATS Readiness": st.column_config.TextColumn("ATS Readiness"),
                }
            )

            with st.expander("🎯 Quick Assign / Reassign Job Tier Level", expanded=False):
                st.caption("Manually adjust or assign the Pursuit Tier for any job:")
                tier_edit_col1, tier_edit_col2, tier_edit_col3 = st.columns([2.5, 2, 1.2])
                with tier_edit_col1:
                    job_map = {f"ID {j.id}: {j.company.strip()} — {j.title.strip()}": j.id for j in jobs}
                    sel_job_key = st.selectbox("Select Job to Assign Tier", list(job_map.keys()), key="dash_sel_job_tier")
                    sel_job_id = job_map[sel_job_key]
                    current_fit = repo.get_fit_for_job(sel_job_id)
                    curr_tier = current_fit.get("tier", "tier_3") if current_fit else "tier_3"
                with tier_edit_col2:
                    tier_options = ["tier_1", "tier_2", "tier_3", "barrier", "do_not_pursue"]
                    tier_labels = ["🟢 Tier 1 (Strong Pursue ≥80)", "🟡 Tier 2 (Pursue 70–79)", "🟠 Tier 3 (Selective Pursue 60–69)", "⚫ Barrier (Gate Obstacle)", "🔴 Do Not Pursue (<60)"]
                    curr_idx = tier_options.index(curr_tier) if curr_tier in tier_options else 2
                    chosen_tier_label = st.selectbox("Assign New Tier Level", tier_labels, index=curr_idx, key="dash_sel_tier_choice")
                    chosen_tier = tier_options[tier_labels.index(chosen_tier_label)]
                with tier_edit_col3:
                    st.write("")
                    st.write("")
                    if st.button("💾 Save Tier", key="btn_dash_save_tier", type="primary", use_container_width=True):
                        repo.update_job_tier(sel_job_id, chosen_tier)
                        st.success(f"✅ Assigned {chosen_tier_label.split(' ')[0]} {chosen_tier_label.split(' ')[1]} to Job ID {sel_job_id}!")
                        st.rerun()


# =============================================================================
# Screen 5: Master Resume
# =============================================================================
elif screen == "📄 Master Resume":
    st.title("📄 Master Resume")
    st.caption(
        "**Appendix · Supporting Tool** — Manage your canonical Master Resume. The ATS engine and Evidence Mapper evaluate all job descriptions against this version."
    )

    current_resume = load_master_resume()
    has_resume = bool(current_resume.strip())
    words = len(current_resume.split()) if has_resume else 0
    chars = len(current_resume) if has_resume else 0

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Word Count", f"{words:,}")
    m2.metric("Character Count", f"{chars:,}")
    m3.metric("Est. Pages", f"~{max(1, round(words / 450, 1))}" if has_resume else "0")
    m4.metric("Status", "Active" if has_resume else "Clean / No Resume")

    st.divider()

    tab_edit, tab_preview, tab_profile = st.tabs(
        ["✏️ Edit & Update Master Resume", "👁️ Formatted Preview", "🎯 Candidate Profile & Rules"]
    )

    with tab_edit:
        st.markdown("#### Upload or Paste Your Master Resume")
        st.caption("Upload your full resume (.docx, .pdf, .txt, .md) or paste directly below. All columns, text boxes, and tables will be extracted.")

        if st.session_state.pop("resume_just_saved", False):
            st.success("✅ Master Resume saved! All future job analyses and ATS evaluations will use this version.")
        if st.session_state.pop("resume_just_cleared", False):
            st.info("🧹 Master Resume cleared. The editor is now clean and blank.")

        editor_version = st.session_state.get("resume_editor_version", 0)

        uploaded_file = st.file_uploader(
            "Upload Master Resume (.docx, .pdf, .txt, .md)",
            type=["docx", "pdf", "txt", "md"],
            key="master_resume_uploader",
            help="Uploading a Word, PDF, or text file will automatically extract its full text into the editor below and save it as your master resume.",
        )
        if uploaded_file is not None:
            file_sig = f"{uploaded_file.name}_{uploaded_file.size}"
            if st.session_state.get("last_uploaded_sig") != file_sig:
                st.session_state["last_uploaded_sig"] = file_sig
                try:
                    file_bytes = uploaded_file.read()
                    uploaded_text = document_handler.extract_text(file_bytes, uploaded_file.name)
                    if uploaded_text.strip():
                        save_master_resume(uploaded_text)
                        st.session_state["resume_editor_version"] = editor_version + 1
                        st.session_state["resume_just_saved"] = True
                        st.rerun()
                    else:
                        st.warning(f"Could not extract readable text from '{uploaded_file.name}'.")
                except Exception as e:
                    st.error(f"Error parsing uploaded file: {e}")

        edited_resume = st.text_area(
            "Master Resume Text",
            value=current_resume,
            height=540,
            key=f"master_resume_editor_v{editor_version}",
            placeholder="No resume loaded. Paste your resume here, or drag and drop a Word (.docx) / PDF (.pdf) file above to get started...",
        )

        col_save, col_clear = st.columns([3, 1])
        with col_save:
            if st.button("💾 Save Master Resume", type="primary", use_container_width=True):
                if edited_resume.strip():
                    save_master_resume(edited_resume)
                    st.session_state["resume_editor_version"] = editor_version + 1
                    st.session_state["resume_just_saved"] = True
                    st.rerun()
                else:
                    st.error("Resume text cannot be empty.")
        with col_clear:
            if st.button("🧹 Clear Resume", use_container_width=True, help="Wipe the master resume and clean the screen"):
                clear_master_resume()
                st.session_state["resume_editor_version"] = editor_version + 1
                st.session_state["resume_just_cleared"] = True
                st.session_state.pop("last_uploaded_sig", None)
                st.rerun()

    with tab_preview:
        if has_resume:
            st.markdown("#### Formatted Resume Preview")
            pcol1, pcol2, pcol3 = st.columns(3)
            with pcol1:
                st.download_button(
                    "📄 Download Word (.docx)",
                    data=document_handler.create_docx(current_resume, "Master Resume"),
                    file_name="Elena_Shchetinina_Master_Resume.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    use_container_width=True,
                )
            with pcol2:
                st.download_button(
                    "📑 Download PDF (.pdf)",
                    data=document_handler.create_pdf(current_resume, "Master Resume"),
                    file_name="Elena_Shchetinina_Master_Resume.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                )
            with pcol3:
                st.download_button(
                    "📝 Download Text (.txt)",
                    data=current_resume,
                    file_name="Elena_Shchetinina_Master_Resume.txt",
                    mime="text/plain",
                    use_container_width=True,
                )
            st.divider()
            st.markdown(current_resume)
        else:
            st.info("ℹ️ No Master Resume is currently loaded. Upload a Word (.docx), PDF (.pdf), or paste your resume in the Edit tab above to see its formatted preview.")

    with tab_profile:
        st.markdown("#### Candidate Profile & Targeting Rules")
        st.caption("Rules defined in `data/candidate_profile.json` that guide the AI agent.")
        try:
            profile_path = Path(__file__).resolve().parent.parent.parent / "data" / "candidate_profile.json"
            if profile_path.exists():
                prof = json.loads(profile_path.read_text(encoding="utf-8"))
                col_p1, col_p2 = st.columns(2)
                with col_p1:
                    st.markdown(f"**Candidate:** {prof.get('name', 'Elena Shchetinina')}")
                    st.markdown(f"**Location:** {prof.get('location', '')}")
                    st.markdown(f"**Headline:** {prof.get('headline', '')}")
                    st.markdown("**Target Role Families:**")
                    for rf in prof.get("target_role_families", []):
                        st.markdown(f"- {rf}")
                with col_p2:
                    st.markdown("**Hard Constraints & Guardrails:**")
                    for c in prof.get("constraints", []):
                        st.markdown(f"- ⛔ {c}")
                    st.markdown("**Selective / Avoid:**")
                    for a in prof.get("avoid_or_selective", []):
                        st.markdown(f"- ⚠️ {a}")
        except Exception as e:
            st.error(f"Could not load candidate profile: {e}")


# =============================================================================
# Screen 6: Scout
# =============================================================================
elif screen == "🔭 Scout":
    import subprocess
    import sys

    st.title("🔭 Daily Job Scout")
    st.caption("Autonomous job discovery and suitability assessment across 26 company ATS boards + Adzuna. Filtered and scored against your profile, seniority, authorization, and verified evidence. Application tailoring and submission are managed downstream in the **🎯 Coordinator** pipeline.")

    SCOUT_STORE = Path(__file__).resolve().parent.parent.parent / "data" / "scout" / "jobs.json"

    # --- Run Scout button ---
    col_run, col_check = st.columns([2, 1])
    with col_run:
        if st.button("▶️ Run Scout Now", type="primary", use_container_width=True, key="btn_run_scout",
                     help="Fetches all 26 boards, filters by your profile, scores matches, updates jobs.json"):
            with st.spinner("🔭 Scanning 26 company boards… this takes ~15–30 seconds"):
                try:
                    result = subprocess.run(
                        [sys.executable, "-m", "app.scout", "run"],
                        capture_output=True, text=True,
                        cwd=str(Path(__file__).resolve().parent.parent.parent),
                        timeout=120,
                    )
                    if result.returncode == 0:
                        st.success(result.stdout.strip() or "✅ Scout completed!")
                    else:
                        st.error(f"Scout error:\n{result.stderr[:800]}")
                    st.rerun()
                except subprocess.TimeoutExpired:
                    st.error("Scout timed out after 2 minutes.")
                except Exception as exc:
                    st.error(f"Could not run scout: {exc}")
    with col_check:
        if st.button("🩺 Check Boards", use_container_width=True, key="btn_check_boards",
                     help="Verify all 26 board slugs are live"):
            with st.spinner("Checking boards…"):
                try:
                    result = subprocess.run(
                        [sys.executable, "-m", "app.scout", "check"],
                        capture_output=True, text=True,
                        cwd=str(Path(__file__).resolve().parent.parent.parent),
                        timeout=90,
                    )
                    lines = (result.stdout or "").strip().split("\n")
                    ok = sum(1 for l in lines if l.strip().startswith("ok"))
                    fail = sum(1 for l in lines if l.strip().startswith("FAIL"))
                    if fail == 0:
                        st.success(f"✅ All {ok} boards are live!")
                    else:
                        st.warning(f"{ok} ok · {fail} failed")
                        for l in lines:
                            if "FAIL" in l:
                                st.caption(l)
                except Exception as exc:
                    st.error(f"Check failed: {exc}")

    st.divider()

    # --- Load scout store ---
    if not SCOUT_STORE.exists():
        st.info("No scout results yet. Click **▶️ Run Scout Now** above to discover matching jobs.")
    else:
        try:
            sdata = json.loads(SCOUT_STORE.read_text(encoding="utf-8"))
        except Exception as e:
            st.error(f"Could not read scout store: {e}")
            sdata = {}

        all_jobs = list(sdata.get("jobs", {}).values())
        open_jobs = [j for j in all_jobs if j.get("status") == "open"]
        runs = sdata.get("runs", [])

        if not open_jobs:
            st.info("No open jobs in the store yet. Click **▶️ Run Scout Now** to fetch results.")
        else:
            # --- Top metrics ---
            t1 = [j for j in open_jobs if j.get("tier") == "tier_1"]
            t2 = [j for j in open_jobs if j.get("tier") == "tier_2"]
            t3 = [j for j in open_jobs if j.get("tier") == "tier_3"]
            barrier = [j for j in open_jobs if j.get("tier") == "barrier"]
            last_run = runs[-1]["started_at"][:10] if runs else "unknown"

            mc1, mc2, mc3, mc4, mc5 = st.columns(5)
            mc1.metric("Open Matches", len(open_jobs))
            mc2.metric("🟢 Tier 1", len(t1))
            mc3.metric("🟡 Tier 2", len(t2))
            mc4.metric("🟠 Tier 3", len(t3))
            mc5.metric("Last Scout", last_run)

            st.divider()

            # --- Filters ---
            filter_col1, filter_col2, filter_col3 = st.columns([2, 2, 2])
            with filter_col1:
                tier_filter = st.multiselect(
                    "Filter by Tier",
                    ["🟢 Tier 1", "🟡 Tier 2", "🟠 Tier 3", "⚫ Barrier"],
                    default=["🟢 Tier 1", "🟡 Tier 2"],
                    key="scout_tier_filter",
                )
            with filter_col2:
                companies = sorted(set(j.get("company", "") for j in open_jobs))
                co_filter = st.multiselect("Filter by Company", companies, default=[], key="scout_co_filter")
            with filter_col3:
                sort_by = st.selectbox("Sort by", ["Tier + Score", "Company A–Z", "Posted Date (newest)"], key="scout_sort")

            tier_map = {"🟢 Tier 1": "tier_1", "🟡 Tier 2": "tier_2", "🟠 Tier 3": "tier_3", "⚫ Barrier": "barrier"}
            selected_tiers = [tier_map[t] for t in tier_filter if t in tier_map]

            filtered = open_jobs
            if selected_tiers:
                filtered = [j for j in filtered if j.get("tier") in selected_tiers]
            if co_filter:
                filtered = [j for j in filtered if j.get("company") in co_filter]

            if sort_by == "Tier + Score":
                tier_order = {"tier_1": 0, "tier_2": 1, "tier_3": 2, "barrier": 3}
                filtered.sort(key=lambda j: (tier_order.get(j.get("tier", "tier_3"), 9), -j.get("fit_score", 0)))
            elif sort_by == "Company A–Z":
                filtered.sort(key=lambda j: j.get("company", "").lower())
            elif sort_by == "Posted Date (newest)":
                filtered.sort(key=lambda j: j.get("posted_date", ""), reverse=True)

            st.caption(f"Showing **{len(filtered)}** of **{len(open_jobs)}** open matches")
            st.divider()

            # --- Tier badge helper ---
            def _tier_badge(tier: str) -> str:
                return {"tier_1": "🟢 Tier 1", "tier_2": "🟡 Tier 2", "tier_3": "🟠 Tier 3",
                        "barrier": "⚫ Barrier", "do_not_pursue": "🔴 Do Not Pursue"}.get(tier, "⚪ Unscored")

            from app.coordinator import CoordinatorAgent
            coord = CoordinatorAgent()

            # --- Job cards ---
            for idx, job in enumerate(filtered):
                job_id = job.get("id", f"scout_{idx}")
                tier_badge = _tier_badge(job.get("tier", ""))
                fit_pct = job.get("fit_score", 0)
                fit_display = f"{fit_pct:.0f}%" if fit_pct <= 100 else f"{fit_pct:.0f}"
                ats_score = job.get("ats_readiness")
                comp = job.get("compensation", "")
                loc = job.get("location", "")
                work_model = job.get("work_model", "")
                posted = job.get("posted_date", "")
                url = job.get("url", "")
                desc = job.get("description", "")
                role_family = job.get("role_family", "")
                seniority = job.get("seniority", "")
                authorization = job.get("authorization", "")
                barriers = job.get("barriers", [])
                fit_notes = job.get("fit_notes", {})
                matched_kw = job.get("matched_keywords", [])
                missing_supp = job.get("missing_supported", [])
                missing_unsupp = job.get("missing_unsupported", [])

                with st.container():
                    header_col, badge_col, btn_col = st.columns([5, 2, 2.2])
                    with header_col:
                        st.markdown(f"### {job.get('company', '')} — {job.get('title', '')}")
                        meta_parts = []
                        if loc:
                            meta_parts.append(f"📍 {loc}")
                        if work_model:
                            meta_parts.append(f"🏢 {work_model.title()}")
                        if posted:
                            meta_parts.append(f"📅 Posted {posted}")
                        if comp:
                            meta_parts.append(f"💰 {comp}")
                        if meta_parts:
                            st.caption("   ·   ".join(meta_parts))

                        tag_parts = []
                        if role_family:
                            tag_parts.append(f"💼 **Role**: {role_family}")
                        if seniority:
                            tag_parts.append(f"🎖️ **Level**: {seniority.title()}")
                        if authorization:
                            tag_parts.append(f"🛂 **Auth**: {authorization.replace('_', ' ').title()}")
                        if tag_parts:
                            st.caption("   ·   ".join(tag_parts))

                    with badge_col:
                        st.markdown(f"**{tier_badge}**")
                        st.markdown(f"**Strategic Fit**: `{fit_display}`")
                        if ats_score is not None:
                            st.caption(f"ATS Readiness: {ats_score:.0f}%")

                    with btn_col:
                        in_queue = coord.queue.exists(job_id)
                        if in_queue:
                            q_entry = coord.queue.get(job_id)
                            status_label = q_entry.status.value.replace("_", " ").title() if q_entry else "In Queue"
                            if st.button(f"🎯 In Pipeline ({status_label})", key=f"scout_coord_{idx}", use_container_width=True,
                                         help="This role is in your Coordinator pipeline. Click to manage approvals, outreach, and tailoring."):
                                st.session_state["nav_screen"] = "🎯 Coordinator"
                                st.rerun()
                        else:
                            if st.button("➕ Send to Coordinator", key=f"scout_add_coord_{idx}", use_container_width=True,
                                         help="Add this job to your Coordinator pipeline for approval, contacts, and resume tailoring."):
                                coord.queue.upsert_from_scout(job)
                                coord.save()
                                st.toast(f"Queued {job.get('company', '')} for Coordinator pipeline!", icon="🎯")
                                st.rerun()

                        if url:
                            st.link_button("🔗 View Posting", url, use_container_width=True)

                    # ── Suitability Assessment Details ────────────────────
                    with st.expander("🔎 Suitability Assessment Details", expanded=False):
                        if fit_notes:
                            st.markdown("**📋 Suitability Rationale**")
                            rc1, rc2 = st.columns(2)
                            with rc1:
                                if fit_notes.get("functional"):
                                    st.caption(f"🎯 **Functional**: {fit_notes['functional']}")
                                if fit_notes.get("seniority"):
                                    st.caption(f"📈 **Seniority**: {fit_notes['seniority']}")
                            with rc2:
                                if fit_notes.get("location_auth"):
                                    st.caption(f"🌍 **Location & Auth**: {fit_notes['location_auth']}")
                                if fit_notes.get("evidence"):
                                    st.caption(f"🛡️ **Evidence**: {fit_notes['evidence']}")
                            st.divider()

                        if barriers:
                            st.warning("⚠️ **Suitability Barriers:**")
                            for b in barriers:
                                st.caption(f"• {b}")
                            st.divider()

                        kc1, kc2 = st.columns(2)
                        with kc1:
                            if matched_kw:
                                st.markdown(f"**✅ Matched Strengths ({len(matched_kw)})**")
                                st.caption(", ".join(matched_kw[:30]))
                            else:
                                st.caption("No strong keyword matches recorded.")
                        with kc2:
                            if missing_supp:
                                st.markdown(f"**➕ Addressable via Evidence ({len(missing_supp)})**")
                                st.caption(", ".join(missing_supp[:20]))
                            if missing_unsupp:
                                st.markdown(f"**❌ Gaps ({len(missing_unsupp)})**")
                                st.caption(", ".join(missing_unsupp[:20]))

                        if desc:
                            with st.expander("📄 View Job Description Preview"):
                                st.markdown(desc[:3000] + ("…" if len(desc) > 3000 else ""))

                    st.divider()


# =============================================================================
# Screen: Coordinator
# =============================================================================
elif screen == "🎯 Coordinator":
    import importlib
    import app.coordinator.queue
    import app.coordinator.coordinator
    importlib.reload(app.coordinator.queue)
    importlib.reload(app.coordinator.coordinator)
    from app.coordinator import CoordinatorAgent, JobStatus

    st.title("🎯 Coordinator")
    st.caption(
        "Human-in-the-loop pipeline: Approve jobs → Tailor resume → Approve resume → Submit. "
        "Nothing is submitted without your explicit confirmation."
    )

    coord = CoordinatorAgent()

    # ── Sidebar: Funnel summary ───────────────────────────────────────────
    counts = coord.funnel_counts()
    total = sum(counts.values())
    if total:
        with st.sidebar:
            st.markdown("**📊 Pipeline Funnel**")
            funnel_order = [
                ("discovered", "🔵 Discovered"),
                ("approved", "✅ Approved"),
                ("tailoring", "⚙️ Tailoring"),
                ("resume_ready", "📄 Resume Ready"),
                ("submission_approved", "🚀 Ready to Submit"),
                ("submitted", "✉️ Submitted"),
                ("interview", "🎉 Interview"),
            ]
            for key, label in funnel_order:
                n = counts.get(key, 0)
                if n:
                    st.caption(f"{label}: **{n}**")

    # ── Top action bar ────────────────────────────────────────────────────
    col_sync, col_info = st.columns([2, 4])
    with col_sync:
        if st.button("🔄 Sync from Scout", type="primary", use_container_width=True,
                     help="Pull new Tier 1 & 2 jobs from the Scout store into this queue"):
            with st.spinner("Syncing…"):
                added = coord.ingest_scout_results(min_tier="tier_2")
            if added:
                st.success(f"✅ Added **{added}** new job(s) to the queue.")
                st.rerun()
            else:
                st.info("No new jobs to add (all Tier 1/2 jobs already in queue).")
    with col_info:
        pending = coord.pending_approvals()
        resume_ready = coord.resume_ready_for_review()
        sub_ready = coord.approved_for_submission()
        badges = []
        if pending: badges.append(f"🔵 **{len(pending)}** awaiting approval")
        if resume_ready: badges.append(f"📄 **{len(resume_ready)}** resume(s) to review")
        if sub_ready: badges.append(f"🚀 **{len(sub_ready)}** ready to submit")
        if badges:
            st.info("  ·  ".join(badges))

    st.divider()

    # ═══════════════════════════════════════════════════════════════════
    # GATE 1 — Approve discovered jobs
    # ═══════════════════════════════════════════════════════════════════
    if pending:
        st.subheader(f"🔵 Gate 1 — Approve for Resume Tailoring ({len(pending)} jobs)")
        st.caption("Analyze suitability and review match details before deciding whether to approve for resume tailoring or skip.")

        for entry in sorted(pending, key=lambda e: (-e.fit_score)):
            tier_badge = {"tier_1": "🟢 Tier 1", "tier_2": "🟡 Tier 2", "tier_3": "🟠 Tier 3"}.get(entry.tier, entry.tier)
            analysis_open_key = f"coord_show_analysis_{entry.id}"
            is_analysis_open = st.session_state.get(analysis_open_key, False)

            with st.container(border=True):
                hc1, hc2, hc3 = st.columns([4.2, 1.8, 4.0])
                with hc1:
                    st.markdown(f"**{entry.company} — {entry.title}**")
                    loc = getattr(entry, "location", "") or "Unknown"
                    fit = getattr(entry, "fit_score", 0)
                    ats_r = getattr(entry, "ats_readiness", 0)
                    st.caption(f"📍 {loc}  ·  Fit: {fit:.0f}/100  ·  ATS: {ats_r:.0f}%")
                with hc2:
                    st.markdown(f"**{tier_badge}**")
                    if entry.url:
                        st.markdown(
                            f'<a href="{entry.url}" target="_blank" style="font-size:0.82rem">🔗 View Posting</a>',
                            unsafe_allow_html=True,
                        )
                with hc3:
                    bc1, bc2, bc3 = st.columns([1.3, 1.1, 0.9])
                    with bc1:
                        analyze_btn_label = "Hide Analysis" if is_analysis_open else "🔍 Analyze Job"
                        if st.button(analyze_btn_label, key=f"btn_analyze_{entry.id}", use_container_width=True,
                                     help="Run deep qualification analysis (Strategic Fit, ATS Keywords, Evidence Mapping) before approving"):
                            st.session_state[analysis_open_key] = not is_analysis_open
                            st.rerun()
                    with bc2:
                        if st.button("✅ Approve", key=f"approve_{entry.id}", use_container_width=True, type="primary",
                                     help="Approve for Contacts verification and Resume tailoring"):
                            coord.approve_job(entry.id)
                            st.session_state.pop(analysis_open_key, None)
                            st.rerun()
                    with bc3:
                        if st.button("⏭ Skip", key=f"skip_{entry.id}", use_container_width=True,
                                     help="Skip this job"):
                            coord.skip_job(entry.id, "Skipped by user")
                            st.session_state.pop(analysis_open_key, None)
                            st.rerun()

                # If analysis is opened by the user
                if is_analysis_open:
                    # Safe JD extraction
                    jd_text = ""
                    if hasattr(coord, "get_jd"):
                        jd_text = coord.get_jd(entry.id)
                    elif hasattr(coord, "_get_jd"):
                        jd_text = coord._get_jd(entry.id)
                    if not jd_text:
                        s_store_file = Path(__file__).resolve().parent.parent.parent / "data" / "scout" / "jobs.json"
                        if s_store_file.exists():
                            try:
                                s_data = json.loads(s_store_file.read_text(encoding="utf-8"))
                                jd_text = s_data.get("jobs", {}).get(entry.id, {}).get("description", "")
                            except Exception:
                                pass
                    if not jd_text:
                        jd_text = getattr(entry, "description", "")
                    brief_cache_key = f"brief_cache_{entry.id}"
                    brief = st.session_state.get(brief_cache_key)

                    if not brief:
                        dup_id = repo.find_duplicate_job(entry.company, entry.title)
                        if dup_id:
                            brief = repo.get_brief_for_job(dup_id)
                        if not brief and jd_text:
                            with st.spinner(f"Running full qualification analysis for {entry.company}…"):
                                try:
                                    brief = process_job(
                                        jd_text=jd_text,
                                        company=entry.company,
                                        title=entry.title,
                                        location=getattr(entry, "location", None),
                                        url=entry.url or None,
                                    )
                                    st.session_state[brief_cache_key] = brief
                                except Exception as e:
                                    st.error(f"Analysis failed: {e}")

                    if brief:
                        _render_brief(brief, in_coordinator=True)
                    elif not jd_text:
                        st.warning("No full job description found in Scout store. You can open the Analyze Job screen to paste the JD.")
                        if st.button("📝 Open Analyze Job Screen to Paste JD", key=f"paste_jd_{entry.id}"):
                            st.session_state["form_company"] = entry.company
                            st.session_state["form_title"] = entry.title
                            st.session_state["form_location"] = getattr(entry, "location", "")
                            st.session_state["form_url"] = entry.url or ""
                            st.session_state["coordinator_active_job_id"] = entry.id
                            st.session_state["nav_screen"] = "🔍 Analyze Job"
                            st.rerun()
                else:
                    m_kw = getattr(entry, "matched_keywords", [])
                    e_notes = getattr(entry, "notes", "")
                    if m_kw or e_notes:
                        with st.expander("Quick Details"):
                            if m_kw:
                                st.caption("✅ Keywords already matched: " + ", ".join(m_kw[:8]))
        st.divider()

    # ═══════════════════════════════════════════════════════════════════
    # ═══════════════════════════════════════════════════════════════════
    # Gate 1.5 + Tailor: Contacts verification + Resume tailoring
    # ═══════════════════════════════════════════════════════════════════
    approved_jobs = coord.queue.by_status(JobStatus.approved)
    if approved_jobs:
        st.subheader(f"⚙️ Approved Jobs — Contacts & Resume Tailoring ({len(approved_jobs)} jobs)")
        st.caption("Step 1: Find & verify hiring contacts. Step 2: Tailor your resume.")

        for entry in approved_jobs:
            contacts_found = entry.as_dict().get("contacts_found", 0)
            contacts_icon = "✅" if contacts_found else "🔍"

            with st.container(border=True):
                # Header
                hdr1, hdr2 = st.columns([7, 3])
                with hdr1:
                    st.markdown(f"**{entry.company} — {entry.title}**")
                    appr_loc = getattr(entry, "location", "") or "Unknown"
                    appr_fit = getattr(entry, "fit_score", 0)
                    st.caption(f"📍 {appr_loc}  ·  Fit: {appr_fit:.0f}/100")
                with hdr2:
                    if entry.url:
                        st.markdown(
                            f'<a href="{entry.url}" target="_blank" style="font-size:0.85rem">🔗 View Job Posting</a>',
                            unsafe_allow_html=True,
                        )

                # ── Gate 1.5: Contacts ─────────────────────────────────
                with st.expander(
                    f"{contacts_icon} Hiring Contacts"
                    f"{' — ' + str(contacts_found) + ' found' if contacts_found else ' — Not yet verified'}",
                    expanded=not contacts_found,
                ):
                    cc1, cc2 = st.columns([3, 5])
                    with cc1:
                        if st.button(
                            "🔍 Find & Verify Contacts",
                            key=f"contacts_{entry.id}",
                            use_container_width=True,
                            type="primary" if not contacts_found else "secondary",
                            help="Scrape ATS metadata + generate LinkedIn/X-Ray search URLs",
                        ):
                            with st.spinner(f"Searching for contacts at {entry.company}…"):
                                cr = coord.verify_contacts(entry.id)
                            if cr:
                                st.rerun()
                            else:
                                st.error("Contact search failed.")
                    with cc2:
                        st.caption(
                            "Scrapes public ATS job metadata · Generates LinkedIn & Google X-Ray search links · No login required"
                        )

                    # Show results if already run
                    cr = coord.load_contacts(entry.id)
                    if cr:
                        all_contacts = cr.all_contacts()
                        if all_contacts:
                            st.markdown("**✅ Verified Contacts**")
                            for c in all_contacts:
                                confidence = c.get("confidence", "")
                                badge = {"high": "🟢", "medium": "🟡", "low": "🟠"}.get(str(confidence), "⚪")
                                ptype = str(c.get("person_type", "")).replace("_", " ").title()
                                col_a, col_b = st.columns([4, 2])
                                with col_a:
                                    st.markdown(
                                        f"{badge} **{c.get('name', '—')}** · {c.get('current_title', '')} · _{ptype}_"
                                    )
                                    if c.get("relationship_to_job"):
                                        st.caption(c["relationship_to_job"][:120])
                                with col_b:
                                    if c.get("source_url"):
                                        st.markdown(
                                            f'<a href="{c["source_url"]}" target="_blank" style="font-size:0.82rem">🔗 LinkedIn Profile</a>',
                                            unsafe_allow_html=True,
                                        )
                        else:
                            st.info("No confirmed contacts found automatically. Use the search links below to find contacts manually.")

                        if cr.quick_links:
                            st.markdown("**🔎 Find Contacts Manually**")
                            for lnk in cr.quick_links:
                                st.markdown(
                                    f'<a href="{lnk["url"]}" target="_blank" style="font-size:0.85rem">{lnk["label"]}</a>'
                                    f'<span style="color:#888;font-size:0.78rem;margin-left:8px">{lnk["purpose"]}</span>',
                                    unsafe_allow_html=True,
                                )

                # ── Resume Tailoring ───────────────────────────────────
                st.markdown("---")
                rc1, rc2 = st.columns([5, 3])
                with rc1:
                    st.caption("Resume tailoring uses your master resume + evidence library to inject missing keywords.")
                with rc2:
                    if st.button("⚙️ Tailor Resume", key=f"tailor_{entry.id}", use_container_width=True, type="primary"):
                        with st.spinner(f"Tailoring resume for {entry.company}…"):
                            path = coord.run_tailoring(entry.id)
                        if path:
                            st.success(f"✅ Resume saved to `{path}`")
                            st.rerun()
                        else:
                            st.error("Tailoring failed — check logs.")
        st.divider()

    in_progress = coord.queue.by_status(JobStatus.tailoring)
    if in_progress:
        st.info(f"⚙️ **{len(in_progress)}** resume(s) currently being tailored…")
        st.divider()

    # ═══════════════════════════════════════════════════════════════════
    # GATE 2 — Review tailored resumes
    # ═══════════════════════════════════════════════════════════════════
    if resume_ready:
        st.subheader(f"📄 Gate 2 — Review Tailored Resumes ({len(resume_ready)} jobs)")
        st.caption("Review each tailored resume. Approve to proceed to submission, or reject to re-tailor.")

        for entry in resume_ready:
            with st.container(border=True):
                st.markdown(f"**{entry.company} — {entry.title}**")
                resume_path = entry.tailored_resume_path
                if resume_path and Path(resume_path).exists():
                    with st.expander("📄 Preview Tailored Resume", expanded=True):
                        try:
                            content = Path(resume_path).read_text(encoding="utf-8")
                            st.text_area("Tailored Resume", value=content[:4000], height=300,
                                         key=f"preview_{entry.id}", label_visibility="collapsed")
                        except Exception:
                            st.info(f"Resume at: `{resume_path}`")

                rc1, rc2, rc3 = st.columns(3)
                with rc1:
                    if st.button("✅ Approve & Proceed", key=f"apprsub_{entry.id}",
                                 use_container_width=True, type="primary"):
                        coord.approve_resume(entry.id)
                        st.success("Resume approved — ready for submission!")
                        st.rerun()
                with rc2:
                    feedback = st.text_input("Rejection reason", key=f"feedback_{entry.id}",
                                             placeholder="e.g. missing AI keywords")
                with rc3:
                    if st.button("🔄 Re-tailor", key=f"retailor_{entry.id}", use_container_width=True):
                        coord.reject_resume(entry.id, feedback)
                        st.rerun()
        st.divider()

    # ═══════════════════════════════════════════════════════════════════
    # GATE 3 — Confirm & Submit
    # ═══════════════════════════════════════════════════════════════════
    if sub_ready:
        st.subheader(f"🚀 Gate 3 — Confirm & Submit ({len(sub_ready)} jobs)")
        st.warning(
            "⚠️ **Final human gate.** Clicking Submit will open the job URL in a visible "
            "browser window, fill the form, and upload your resume. You must watch the browser "
            "and confirm the final submit click yourself."
        )

        from app.agents.submission_agent import SubmissionAgent, detect_ats
        sub_agent = SubmissionAgent()
        playwright_ok, playwright_msg = sub_agent.is_available()

        if not playwright_ok:
            st.error(f"🔴 Submission Agent not available: {playwright_msg}")

        for entry in sub_ready:
            with st.container(border=True):
                st.markdown(f"**{entry.company} — {entry.title}**")
                ats_detected = detect_ats(entry.url) if entry.url else "unknown"
                st.caption(
                    f"ATS: **{ats_detected.title()}**  ·  "
                    f"Resume: `{Path(entry.tailored_resume_path).name if entry.tailored_resume_path else '—'}`"
                )
                if entry.url:
                    st.markdown(
                        f'<a href="{entry.url}" target="_blank" style="font-size:0.85rem">🔗 Review Job Posting First</a>',
                        unsafe_allow_html=True,
                    )

                g3c1, g3c2, g3c3 = st.columns(3)
                with g3c1:
                    if playwright_ok and st.button(
                        "👁 Dry Run (fill, no submit)",
                        key=f"dryrun_{entry.id}",
                        use_container_width=True,
                    ):
                        with st.spinner("Opening browser and filling form…"):
                            result = sub_agent.prefill_preview(
                                url=entry.url,
                                resume_path=Path(entry.tailored_resume_path),
                                company=entry.company,
                                title=entry.title,
                            )
                        if result.get("screenshot"):
                            st.image(result["screenshot"], caption="Form pre-filled (not submitted)")
                        st.info(f"Fields filled: {', '.join(result.get('fields_filled', []))}")
                        if result.get("fields_skipped"):
                            st.caption(f"Skipped: {', '.join(result.get('fields_skipped', []))}")

                with g3c2:
                    confirm_key = f"confirm_{entry.id}"
                    confirmed = st.checkbox(
                        "☑️ I have reviewed the job posting and my resume",
                        key=confirm_key,
                    )

                with g3c3:
                    if playwright_ok and confirmed:
                        if st.button(
                            "🚀 SUBMIT APPLICATION",
                            key=f"submit_{entry.id}",
                            type="primary",
                            use_container_width=True,
                        ):
                            with st.spinner("Submitting application…"):
                                result = coord.submit_job(entry.id, dry_run=False)
                            if result.get("success"):
                                st.balloons()
                                st.success(f"✅ Application submitted to {entry.company}!")
                                if result.get("confirmation_screenshot"):
                                    st.image(result["confirmation_screenshot"], caption="Submission confirmation")
                                st.rerun()
                            else:
                                st.error(f"Submission failed: {result.get('error', 'Unknown error')}")
                    elif not confirmed:
                        st.caption("☝️ Check the confirmation box first")
        st.divider()

    # ═══════════════════════════════════════════════════════════════════
    # ═══════════════════════════════════════════════════════════════════
    # Submitted jobs + Interview tracking
    # ═══════════════════════════════════════════════════════════════════
    submitted_jobs = coord.submitted()
    if submitted_jobs:
        st.subheader(f"✉️ Submitted Applications & Interview Tracker ({len(submitted_jobs)})")

        from app.agents.interview_agent import (
            InterviewAgent, RoundType, RoundOutcome, verify_record
        )
        iv_agent = InterviewAgent()

        for entry in submitted_jobs:
            status_icon = {"submitted": "✉️", "interview": "🎉", "rejected": "❌"}.get(entry.status.value, "✉️")
            submitted_at = entry.as_dict().get("submitted_at", "")

            with st.container(border=True):
                hdr_a, hdr_b = st.columns([6, 4])
                with hdr_a:
                    st.markdown(f"{status_icon} **{entry.company} — {entry.title}**")
                    if submitted_at:
                        st.caption(f"Applied: {submitted_at[:10]}")
                with hdr_b:
                    oc1, oc2, oc3 = st.columns(3)
                    for col, (outcome, label) in zip([oc1, oc2, oc3], [
                        ("interview", "🎉 Interview"),
                        ("rejected", "❌ Rejected"),
                        ("no_response", "💤 No Response"),
                    ]):
                        with col:
                            if st.button(label, key=f"outcome_{entry.id}_{outcome}", use_container_width=True):
                                entry.mark_outcome(outcome)
                                coord.queue.update(entry)
                                coord.save()
                                st.rerun()

                iv_record = iv_agent.get_or_create(
                    job_id=entry.id, company=entry.company,
                    title=entry.title, url=entry.url,
                )

                tabs = st.tabs(["📋 Rounds", "➕ Log Round", "🔍 Verify", "🧠 AI Assessment"])

                with tabs[0]:
                    if not iv_record.rounds:
                        st.info("No interview rounds logged yet. Use the **➕ Log Round** tab.")
                    else:
                        for r in iv_record.rounds:
                            ob = {"passed": "🟢", "rejected": "🔴", "pending": "🟡", "unknown": "⚪"}.get(r.outcome, "⚪")
                            with st.expander(f"{ob} Round {r.round_number} — {r.round_type.replace('_',' ').title()} ({r.date or 'date unknown'})"):
                                c1, c2 = st.columns(2)
                                with c1:
                                    st.markdown(f"**Interviewer:** {r.interviewer_name or '—'}")
                                    st.markdown(f"**Title:** {r.interviewer_title or '—'}")
                                    st.markdown(f"**Format:** {r.format or '—'}  ·  **Duration:** {r.duration_minutes or '?'} min")
                                with c2:
                                    st.markdown(f"**Outcome:** {ob} {r.outcome.title()}")
                                    if r.outcome_notes: st.caption(r.outcome_notes)
                                if r.topics_covered:
                                    st.markdown(f"**Topics:** {', '.join(r.topics_covered)}")
                                if r.questions_asked:
                                    st.markdown("**Questions asked:**")
                                    for q in r.questions_asked: st.markdown(f"  - {q}")
                                if r.candidate_notes:
                                    st.markdown("**Your notes:**")
                                    st.markdown(r.candidate_notes)
                                new_outcome = st.selectbox(
                                    "Update outcome",
                                    options=[o.value for o in RoundOutcome],
                                    index=next((i for i, o in enumerate(RoundOutcome) if o.value == r.outcome), 0),
                                    key=f"outcome_upd_{entry.id}_{r.round_number}",
                                )
                                if st.button("Save outcome", key=f"save_out_{entry.id}_{r.round_number}"):
                                    iv_agent.update_round(iv_record, r.round_number, {"outcome": new_outcome})
                                    st.rerun()

                with tabs[1]:
                    st.markdown("**Log a new interview round**")
                    rtype = st.selectbox("Round type", options=[t.value for t in RoundType],
                                         format_func=lambda x: x.replace("_", " ").title(),
                                         key=f"rtype_{entry.id}")
                    rc1, rc2 = st.columns(2)
                    with rc1:
                        r_date = st.date_input("Interview date", key=f"rdate_{entry.id}")
                        r_interviewer = st.text_input("Interviewer name", key=f"rint_{entry.id}")
                        r_int_title = st.text_input("Interviewer title", key=f"rtitle_{entry.id}")
                    with rc2:
                        r_duration = st.number_input("Duration (minutes)", 0, 480, 60, key=f"rdur_{entry.id}")
                        r_format = st.selectbox("Format", ["video", "phone", "on-site", "async", "other"], key=f"rfmt_{entry.id}")
                        r_outcome = st.selectbox("Outcome", options=[o.value for o in RoundOutcome],
                                                  format_func=lambda x: x.title(), key=f"routcome_{entry.id}")
                    r_topics = st.text_area("Topics covered (one per line)",
                                            placeholder="Portfolio governance\nAI program delivery",
                                            key=f"rtopics_{entry.id}", height=70)
                    r_questions = st.text_area("Questions asked (one per line)",
                                               placeholder="Tell me about a complex program you managed...",
                                               key=f"rquestions_{entry.id}", height=70)
                    r_notes = st.text_area("Your notes & impressions ✍️",
                                           placeholder="How did it go? What felt uncertain? Any red flags?",
                                           key=f"rnotes_{entry.id}", height=100)
                    r_out_notes = st.text_input("Outcome notes (optional)",
                                                placeholder="Recruiter said they'll follow up in 3 days",
                                                key=f"routnotes_{entry.id}")
                    if st.button("💾 Save Round", key=f"save_round_{entry.id}", type="primary", use_container_width=True):
                        if not r_notes.strip():
                            st.warning("Please add at least some notes before saving.")
                        else:
                            iv_agent.add_round(iv_record, {
                                "round_type": rtype, "date": r_date.isoformat() if r_date else "",
                                "interviewer_name": r_interviewer, "interviewer_title": r_int_title,
                                "duration_minutes": r_duration, "format": r_format,
                                "topics_covered": [t.strip() for t in r_topics.splitlines() if t.strip()],
                                "questions_asked": [q.strip() for q in r_questions.splitlines() if q.strip()],
                                "candidate_notes": r_notes.strip(), "outcome": r_outcome,
                                "outcome_notes": r_out_notes.strip(),
                            })
                            st.success(f"✅ Round {len(iv_record.rounds) + 1} saved!")
                            st.rerun()

                with tabs[2]:
                    vr = verify_record(iv_record)
                    st.metric("Record Completeness", f"{vr.completeness_pct}%",
                              delta="Ready" if vr.is_valid else "Needs more data")
                    st.progress(vr.completeness_pct / 100)
                    for e in vr.errors: st.error(f"❌ {e}")
                    for w in vr.warnings: st.warning(f"⚠️ {w}")
                    if vr.is_valid and not vr.warnings:
                        st.success("✅ Record looks complete — run the AI Assessment!")

                with tabs[3]:
                    cached = iv_record.last_assessment
                    if iv_record.last_assessed_at:
                        st.caption(f"Last assessed: {iv_record.last_assessed_at[:10]}")
                    ac1, ac2 = st.columns(2)
                    with ac1:
                        if st.button("🧠 Run AI Assessment", key=f"assess_{entry.id}", type="primary",
                                     use_container_width=True):
                            if not iv_record.rounds:
                                st.warning("Log at least one round first.")
                            else:
                                with st.spinner("Analyzing with Claude…"):
                                    coord.run_interview_assessment(entry.id, force_refresh=True)
                                iv_record = iv_agent.load(entry.id) or iv_record
                                cached = iv_record.last_assessment
                                st.rerun()
                    with ac2:
                        if cached and st.button("🔄 Refresh", key=f"reassess_{entry.id}", use_container_width=True):
                            with st.spinner("Re-analyzing…"):
                                coord.run_interview_assessment(entry.id, force_refresh=True)
                            iv_record = iv_agent.load(entry.id) or iv_record
                            cached = iv_record.last_assessment
                            st.rerun()

                    if cached:
                        if cached.get("_placeholder"):
                            st.info(cached.get("overall_impression", ""))
                        else:
                            st.markdown("### 🎯 Overall Assessment")
                            st.markdown(cached.get("overall_impression", ""))
                            likelihood = cached.get("likelihood_to_proceed", "uncertain")
                            lmap = {"very_likely": ("🟢", "Very Likely"), "likely": ("🟢", "Likely"),
                                    "uncertain": ("🟡", "Uncertain"), "unlikely": ("🔴", "Unlikely"),
                                    "very_unlikely": ("🔴", "Very Unlikely")}
                            licon, ltext = lmap.get(likelihood, ("⚪", likelihood.title()))
                            st.markdown(f"**Likelihood to Proceed:** {licon} **{ltext}**")
                            st.caption(cached.get("likelihood_rationale", ""))
                            st.markdown("---")
                            dims = cached.get("dimension_scores", {})
                            if dims:
                                st.markdown("### 📊 Dimension Scores")
                                for key, label in [("communication", "💬 Communication"),
                                                    ("technical_fit", "⚙️ Technical Fit"),
                                                    ("leadership_fit", "🏆 Leadership Fit"),
                                                    ("cultural_fit", "🤝 Cultural Fit"),
                                                    ("candidate_preparedness", "📚 Preparedness")]:
                                    if key in dims:
                                        score = dims[key].get("score", 0)
                                        sc1, sc2 = st.columns([3, 5])
                                        with sc1:
                                            color = "🟢" if score >= 7 else ("🟡" if score >= 5 else "🔴")
                                            st.markdown(f"{color} **{label}**: {score}/10")
                                        with sc2:
                                            st.caption(dims[key].get("rationale", ""))
                            st.markdown("---")
                            sig_c1, sig_c2 = st.columns(2)
                            with sig_c1:
                                for s in cached.get("positive_signals", []): st.markdown(f"✅ {s}")
                                for s in cached.get("strengths_demonstrated", []): st.markdown(f"💪 {s}")
                            with sig_c2:
                                for s in cached.get("concerning_signals", []): st.markdown(f"⚠️ {s}")
                                for g in cached.get("gaps_identified", []): st.markdown(f"❌ {g}")
                            st.markdown("---")
                            for a in cached.get("follow_up_actions", []): st.markdown(f"  - {a}")
                            if cached.get("next_round_prep"):
                                st.markdown("**📚 Next Round Preparation**")
                                for p in cached["next_round_prep"]: st.markdown(f"  - {p}")
                            with st.expander("✉️ Thank-You Note Points"):
                                for tp in cached.get("thank_you_note_points", []): st.markdown(f"  - {tp}")
                            stage = cached.get("process_stage", "")
                            timeline = cached.get("estimated_timeline", "")
                            if stage or timeline:
                                st.caption(f"📍 Stage: {stage}  ·  ⏱ Timeline: {timeline}")
                    elif iv_record.rounds:
                        st.info("Click 🧠 **Run AI Assessment** to analyze your interview performance.")
                    else:
                        st.info("Log interview rounds first, then run the AI Assessment.")

    if not total:
        st.info(
            "No jobs in the coordinator queue yet. "
            "Click **🔄 Sync from Scout** to pull your Tier 1 & 2 matches."
        )
