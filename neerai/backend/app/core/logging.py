"""Logging with redaction of secrets (AWS keys, bearer tokens, API keys, emails, phone numbers)."""
from __future__ import annotations

import contextvars
import json
import logging
import re
import sys
import time

_PATTERNS = [
    (re.compile(r"AKIA[0-9A-Z]{16}"), "[REDACTED_AWS_KEY]"),
    (re.compile(r"(?i)(aws_secret_access_key|secret|token|api[_-]?key|authorization|password)(\"?\s*[:=]\s*\"?)([^\s\",;]+)"), r"\1\2[REDACTED]"),
    (re.compile(r"(?i)bearer\s+[a-z0-9._\-]+"), "Bearer [REDACTED]"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[REDACTED_EMAIL]"),
    (re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{9}(?!\d)"), "[REDACTED_PHONE]"),
]


def redact(text: str) -> str:
    for pat, rep in _PATTERNS:
        text = pat.sub(rep, text)
    return text


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = redact(record.getMessage())
            record.args = ()
        except Exception:  # never break logging
            pass
        return True


request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


class JsonFormatter(logging.Formatter):
    """One JSON object per line (CloudWatch Logs Insights friendly). Messages are redacted by RedactingFilter first."""

    def format(self, record: logging.LogRecord) -> str:
        out = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + f".{int(record.msecs):03d}Z",
               "level": record.levelname, "logger": record.name, "msg": record.getMessage(), "request_id": request_id_var.get()}
        if record.exc_info:
            out["exc_type"] = record.exc_info[0].__name__ if record.exc_info[0] else None
        return json.dumps(out, ensure_ascii=False)


def emit_metric(name: str, value: float, unit: str = "Count", **dimensions: str) -> None:
    """CloudWatch Embedded Metric Format line on stdout (no PutMetricData permission or extra API calls needed)."""
    dims = {k: str(v) for k, v in dimensions.items()}
    doc = {"_aws": {"Timestamp": int(time.time() * 1000), "CloudWatchMetrics": [
        {"Namespace": "NeerAI", "Dimensions": [list(dims)] if dims else [[]], "Metrics": [{"Name": name, "Unit": unit}]}]},
        name: value, **dims}
    sys.stdout.write(json.dumps(doc) + chr(10))
    sys.stdout.flush()


def configure_logging(level: int | str = logging.INFO, fmt: str = "text") -> None:
    root = logging.getLogger()
    if not any(isinstance(f, RedactingFilter) for h in root.handlers for f in h.filters):
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter() if fmt == "json" else logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        handler.addFilter(RedactingFilter())
        root.addHandler(handler)
    root.setLevel(level)
