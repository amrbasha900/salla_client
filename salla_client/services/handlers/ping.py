from __future__ import annotations

from typing import Any, Dict


def ping(store_id: str | None, payload: Dict[str, Any]) -> Dict[str, Any]:
    # Non-mutating connectivity check
    return {
        "status": "applied",
        "message": "pong",
        "erp_doctype": None,
        "erp_doc": None,
        "warnings": [],
        "errors": [],
        "echo": {"store_id": store_id, "payload": payload},
    }


