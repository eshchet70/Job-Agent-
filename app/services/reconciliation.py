"""
Reconciliation service — conflict detection between external providers and local SQLite.
Creates SyncConflict records rather than silently overwriting divergent values.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.db import repository
from app.models import ConflictResolution, SyncConflict


def detect_and_record_conflicts(
    provider: str,
    external_id: str,
    local_record_id: int | None,
    local_fields: dict[str, Any],
    provider_fields: dict[str, Any],
) -> list[SyncConflict]:
    """
    Compare field-by-field. For each divergence, create a SyncConflict record.
    Returns the list of conflicts created.
    """
    conflicts: list[SyncConflict] = []
    for field, provider_value in provider_fields.items():
        local_value = local_fields.get(field)
        # Normalize to string for comparison
        lv_str = str(local_value).strip() if local_value is not None else ""
        pv_str = str(provider_value).strip() if provider_value is not None else ""

        if lv_str and pv_str and lv_str.lower() != pv_str.lower():
            conflict = SyncConflict(
                provider=provider,
                external_id=external_id,
                local_record_id=local_record_id,
                field=field,
                local_value=lv_str,
                provider_value=pv_str,
                detected_at=datetime.utcnow(),
                resolution_status=ConflictResolution.pending,
            )
            conflict_id = repository.save_conflict(conflict)
            conflict = conflict.model_copy(update={"id": conflict_id})
            conflicts.append(conflict)

    return conflicts


def resolve(conflict_id: int, accept_local: bool = True, note: str = "") -> None:
    """Resolve a conflict by accepting local or provider value."""
    resolution = (
        ConflictResolution.accepted_local.value
        if accept_local
        else ConflictResolution.accepted_provider.value
    )
    repository.resolve_conflict(conflict_id, resolution, note)
