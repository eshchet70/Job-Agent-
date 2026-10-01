"""
Unit tests for app.services.email_service.
Tests SMTP dispatch, inference, test connection, mailto links, and validation.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from app.services import email_service


def test_is_valid_email():
    assert email_service.is_valid_email("derek.smockum@lightspeedhq.com") is True
    assert email_service.is_valid_email("vera.arkhipova@lightspeedhq.com") is True
    assert email_service.is_valid_email("elena@test.org") is True
    assert email_service.is_valid_email("invalid-email") is False
    assert email_service.is_valid_email("@missinguser.com") is False
    assert email_service.is_valid_email("missingdomain@") is False
    assert email_service.is_valid_email("") is False


def test_suggest_email_for_contact():
    # Lightspeed Commerce
    email = email_service.suggest_email_for_contact("Derek Smockum", "Lightspeed Commerce")
    assert email == "derek.smockum@lightspeedhq.com"

    email2 = email_service.suggest_email_for_contact("Vera Arkhipova", "Lightspeed")
    assert email2 == "vera.arkhipova@lightspeedhq.com"

    # CRA
    email3 = email_service.suggest_email_for_contact("John Doe", "Charles River Associates")
    assert email3 == "john.doe@crai.com"

    # Generic company fallback
    email4 = email_service.suggest_email_for_contact("Jane Smith", "Acme Corporation")
    assert email4 == "jane.smith@acme.com"


def test_generate_email_subject():
    subj = email_service.generate_email_subject(
        job_title="Staff Technical Program Manager - PDLC",
        candidate_name="Elena Shchetinina",
    )
    assert "Staff Technical Program Manager - PDLC" in subj
    assert "Elena Shchetinina" in subj


def test_generate_mailto_link():
    link = email_service.generate_mailto_link(
        to_email="derek.smockum@lightspeedhq.com",
        subject="Introduction - Elena",
        body="Hello Derek, reaching out regarding the role.",
    )
    assert link.startswith("mailto:derek.smockum@lightspeedhq.com?")
    assert "subject=" in link
    assert "body=" in link


def test_send_email_simulated():
    result = email_service.send_email(
        to_email="vera.arkhipova@lightspeedhq.com",
        subject="Introduction",
        body="Hello Vera, I am excited about the role.",
        simulated=True,
    )
    assert result.success is True
    assert result.simulated is True
    assert "vera.arkhipova@lightspeedhq.com" in result.message


def test_send_email_validation_errors():
    # Invalid email
    res1 = email_service.send_email("bad-email", "Subj", "Body", simulated=True)
    assert res1.success is False
    assert "Invalid recipient" in res1.message

    # Empty subject
    res2 = email_service.send_email("user@example.com", "", "Body", simulated=True)
    assert res2.success is False
    assert "subject cannot be empty" in res2.message

    # Empty body
    res3 = email_service.send_email("user@example.com", "Subj", "   ", simulated=True)
    assert res3.success is False
    assert "body cannot be empty" in res3.message


@patch("smtplib.SMTP")
def test_send_email_smtp_success(mock_smtp_cls):
    mock_server = MagicMock()
    mock_smtp_cls.return_value = mock_server

    smtp_config = {
        "smtp_host": "smtp.example.com",
        "smtp_port": 587,
        "smtp_username": "elena@example.com",
        "smtp_password": "secretpassword",
        "smtp_sender_email": "elena@example.com",
        "smtp_sender_name": "Elena Shchetinina",
        "smtp_use_tls": True,
        "smtp_use_ssl": False,
    }

    result = email_service.send_email(
        to_email="derek.smockum@lightspeedhq.com",
        subject="Application: Staff TPM",
        body="Dear Derek,\n\nI am writing to apply...",
        smtp_config=smtp_config,
        simulated=False,
    )

    assert result.success is True
    assert result.simulated is False
    mock_server.starttls.assert_called_once()
    mock_server.login.assert_called_once_with("elena@example.com", "secretpassword")
    mock_server.send_message.assert_called_once()
    mock_server.quit.assert_called_once()


@patch("smtplib.SMTP")
def test_test_smtp_connection_success(mock_smtp_cls):
    mock_server = MagicMock()
    mock_smtp_cls.return_value = mock_server

    success, msg = email_service.test_smtp_connection(
        host="smtp.gmail.com",
        port=587,
        username="user@gmail.com",
        password="app_password",
        use_tls=True,
    )
    assert success is True
    assert "Successfully connected" in msg


def test_send_email_blocked_when_not_approved():
    result = email_service.send_email(
        to_email="derek.smockum@lightspeedhq.com",
        subject="Intro",
        body="Message body",
        simulated=True,
        is_approved=False,
    )
    assert result.success is False
    assert "has not been approved" in result.message


def test_send_outreach_email_rejects_pending():
    from app.models import OutreachApproval, OutreachRecord

    pending_outreach = OutreachRecord(
        job_id=4,
        person_name="Duncan Wannamaker",
        recipient_email="duncan.wannamaker@lightspeedhq.com",
        subject="Introduction",
        draft="Reaching out...",
        approval_status=OutreachApproval.pending,
    )

    result = email_service.send_outreach_email(
        outreach=pending_outreach,
        simulated=True,
    )
    assert result.success is False
    assert "in 'pending' status" in result.message
    assert "must be approved" in result.message


def test_send_outreach_email_allows_approved():
    from app.models import OutreachApproval, OutreachRecord

    approved_outreach = OutreachRecord(
        job_id=4,
        person_name="Derek Smockum",
        recipient_email="derek.smockum@lightspeedhq.com",
        subject="Introduction",
        draft="Reaching out...",
        approval_status=OutreachApproval.approved,
    )

    result = email_service.send_outreach_email(
        outreach=approved_outreach,
        simulated=True,
    )
    assert result.success is True
    assert "derek.smockum@lightspeedhq.com" in result.message
