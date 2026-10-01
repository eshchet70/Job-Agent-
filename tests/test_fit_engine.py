"""Tests for fit_engine — weighted formula and tier boundaries."""
import pytest

from app.models import DimensionScore, PursuitTier
from app.services.fit_engine import calculate, WEIGHTS


def test_weights_sum_to_one():
    total = sum(WEIGHTS.values())
    assert abs(total - 1.0) < 1e-9


def test_tier1(tier1_scores):
    result = calculate(tier1_scores)
    assert result.tier == PursuitTier.tier1
    assert result.weighted_score >= 80


def test_tier2(minimal_scores):
    result = calculate(minimal_scores)
    assert result.tier == PursuitTier.tier2
    assert 70 <= result.weighted_score < 80


def test_tier3():
    keys = ["functional", "seniority", "domain", "evidence",
            "location_auth", "competitive", "relationship"]
    scores = {k: DimensionScore(score=65, rationale="moderate") for k in keys}
    result = calculate(scores)
    assert result.tier == PursuitTier.tier3
    assert 60 <= result.weighted_score < 70


def test_do_not_pursue(no_pursue_scores):
    result = calculate(no_pursue_scores)
    assert result.tier == PursuitTier.do_not_pursue
    assert result.weighted_score < 60


def test_barrier_overrides_high_score(tier1_scores):
    result = calculate(tier1_scores, barriers=["Company exclusion: Amazon"])
    assert result.tier == PursuitTier.barrier
    # Score can still be high; barrier flag overrides tier
    assert result.weighted_score >= 80


def test_barriers_from_gate(tier1_scores):
    from app.models import HardGateResult
    # calculate() takes barriers= directly, not gate=
    result = calculate(tier1_scores, barriers=["U.S. authorization barrier"])
    assert result.tier == PursuitTier.barrier
    assert len(result.barriers) == 1


def test_weighted_score_formula():
    keys = ["functional", "seniority", "domain", "evidence",
            "location_auth", "competitive", "relationship"]
    raw = dict(zip(keys, [80, 70, 90, 60, 100, 50, 40]))
    scores = {k: DimensionScore(score=v, rationale="test") for k, v in raw.items()}
    result = calculate(scores)
    expected = sum(raw[k] * WEIGHTS[k] for k in keys)
    assert abs(result.weighted_score - round(expected, 1)) < 0.01


def test_missing_dimension_raises():
    with pytest.raises(ValueError, match="Missing dimension"):
        calculate({"functional": DimensionScore(score=80, rationale="x")})
