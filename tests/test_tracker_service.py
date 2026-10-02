"""Tests for the Tracker Service and Master Application Tracker."""
import pytest
from datetime import date
from pathlib import Path

from app.services.tracker_service import (
    EXPECTED_COLUMNS,
    get_tracker_file_path,
    load_applications_data,
    get_tracker_kpis,
)


def test_tracker_path_resolution():
    p = get_tracker_file_path()
    assert p is not None
    assert p.exists()
    assert "Tracker" in p.name or "tracker" in p.name


def test_load_applications_data():
    df = load_applications_data()
    assert not df.empty
    assert len(df) >= 300
    for col in ["Date Applied", "Company", "Role Title", "Status", "Fit Score (%)"]:
        assert col in df.columns
    assert "_excel_row" in df.columns
    # Check that sorting is descending by Date Applied
    valid_dates = df["Date Applied Clean"].dropna().tolist()
    assert len(valid_dates) > 100
    assert valid_dates[0] >= valid_dates[-1]


def test_tracker_kpis():
    df = load_applications_data()
    kpis = get_tracker_kpis(df)
    assert kpis["total"] >= 300
    assert kpis["applied"] > 0
    assert kpis["rejected"] > 0
    assert kpis["active_pipeline"] >= kpis["applied"]
    assert kpis["avg_response_days"] > 0
