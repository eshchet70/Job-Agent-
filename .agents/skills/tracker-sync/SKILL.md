---
name: tracker-sync
description: Synchronize analyzed jobs, ATS data, people/outreach and status fields with the Excel tracker without damaging formatting.
---
Treat SQLite as canonical MVP state and Excel as human-facing tracker. Preserve existing sheets, formulas, formatting and user-entered values. Use explicit field mappings. Never silently overwrite ambiguous values; create a conflict record. Maintain application-to-outreach linkage.
