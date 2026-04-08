from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ExecutionLogger:
    """Write standard YSocial-compatible JSONL execution logs for plugin clients."""

    def __init__(self, log_path: str | os.PathLike[str] | None = None) -> None:
        resolved_path = log_path or os.environ.get("YAGENTS_CLIENT_LOG_FILE")
        self.path = Path(resolved_path).expanduser() if resolved_path else None
        self._handle = None
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._handle = self.path.open("a", encoding="utf-8", buffering=1)

    def log_execution(
        self,
        *,
        agent_name: str,
        method_name: str,
        execution_time: float,
        tid: Any,
        day: Any,
        hour: Any,
        success: bool = True,
        error: str | None = None,
    ) -> None:
        if self._handle is None:
            return

        payload = {
            "time": datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S"),
            "agent_name": agent_name,
            "method_name": method_name,
            "execution_time_seconds": round(float(execution_time), 4),
            "success": bool(success),
            "tid": tid,
            "day": day,
            "hour": hour,
        }
        if error:
            payload["error"] = str(error)

        self._handle.write(json.dumps(payload, ensure_ascii=True) + "\n")

    def close(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None
