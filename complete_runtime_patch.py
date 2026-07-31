from __future__ import annotations

import json
from uuid import uuid4


PATCH_VERSION = "complete-v1-audit-20260731"


def install() -> None:
    """Apply small production-safe corrections to Complete Runtime V1."""
    import complete_runtime_v1 as runtime

    def corrected_audit(c, pid, actor, action, entity_type, entity_id, detail=None):
        c.execute(
            "INSERT INTO audit_events(id,project_id,actor,action,entity_type,entity_id,detail,created) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (
                uuid4().hex,
                pid,
                actor,
                action,
                entity_type,
                entity_id,
                json.dumps(detail or {}, ensure_ascii=False),
                runtime.now(),
            ),
        )

    runtime.audit = corrected_audit
