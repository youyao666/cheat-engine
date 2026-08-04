from __future__ import annotations

import traceback


def error_payload(exc: Exception, debug: bool = False) -> dict[str, object]:
    payload: dict[str, object] = {
        "ok": False,
        "error": str(exc),
        "type": exc.__class__.__name__,
    }
    if debug:
        payload["traceback"] = traceback.format_exc()
    return payload
