import os
import re
import time
from collections import OrderedDict
from contextlib import contextmanager

from flask import current_app, g, has_app_context, has_request_context, request
from werkzeug.exceptions import HTTPException


DISABLED_VALUES = {"0", "false", "no", "off"}


def performance_timing_enabled():
    configured = os.environ.get(
        "PERFORMANCE_TIMING_ENABLED",
        os.environ.get("AUTH_TIMING_ENABLED", "1"),
    )
    return str(configured).strip().lower() not in DISABLED_VALUES


def request_label():
    if not has_request_context():
        return "no-request"
    return f"{request.method} {request.path} endpoint={request.endpoint or '-'}"


def timing_start(step, detail=""):
    started_at = time.perf_counter()
    if performance_timing_enabled() and has_app_context():
        current_app.logger.info(
            "PERF_TIMING START step=%s at=%.6f request=%s%s",
            step,
            started_at,
            request_label(),
            f" detail={detail}" if detail else "",
        )
    return started_at


def timing_end(step, started_at, detail=""):
    ended_at = time.perf_counter()
    duration_ms = (ended_at - started_at) * 1000
    if performance_timing_enabled() and has_app_context():
        record_timing(step, duration_ms, detail=detail)
        current_app.logger.info(
            "PERF_TIMING END step=%s at=%.6f duration_ms=%.2f request=%s%s",
            step,
            ended_at,
            duration_ms,
            request_label(),
            f" detail={detail}" if detail else "",
        )
    return ended_at


def timing_error(step, started_at, error):
    ended_at = time.perf_counter()
    duration_ms = (ended_at - started_at) * 1000
    if not (performance_timing_enabled() and has_app_context()):
        return ended_at

    detail = f"error={error}"
    if isinstance(error, HTTPException):
        detail = f"status={error.code} error={error}"
        record_timing(step, duration_ms, detail=detail, errored=True)
        current_app.logger.info(
            "PERF_TIMING HTTP_EXCEPTION step=%s at=%.6f duration_ms=%.2f request=%s status=%s error=%s",
            step,
            ended_at,
            duration_ms,
            request_label(),
            error.code,
            error,
        )
        return ended_at

    record_timing(step, duration_ms, detail=detail, errored=True)
    current_app.logger.warning(
        "PERF_TIMING ERROR step=%s at=%.6f duration_ms=%.2f request=%s error=%s",
        step,
        ended_at,
        duration_ms,
        request_label(),
        error,
    )
    return ended_at


@contextmanager
def performance_span(step, detail=""):
    started_at = timing_start(step, detail=detail)
    try:
        yield
    except Exception as error:
        timing_error(step, started_at, error)
        raise
    else:
        timing_end(step, started_at, detail=detail)


def record_timing(step, duration_ms, detail="", errored=False):
    if not has_request_context():
        return
    if not hasattr(g, "_performance_timings"):
        g._performance_timings = OrderedDict()
    summary = g._performance_timings.setdefault(
        step,
        {
            "count": 0,
            "total_ms": 0.0,
            "max_ms": 0.0,
            "details": [],
            "errors": 0,
        },
    )
    summary["count"] += 1
    summary["total_ms"] += duration_ms
    summary["max_ms"] = max(summary["max_ms"], duration_ms)
    if errored:
        summary["errors"] += 1
    if detail and len(summary["details"]) < 4:
        summary["details"].append(str(detail)[:180])


def timing_summary(status="-"):
    if not (performance_timing_enabled() and has_request_context()):
        return
    timings = getattr(g, "_performance_timings", None)
    request_started_at = getattr(g, "_performance_request_started_at", None)
    if not timings and request_started_at is None:
        return

    total_ms = None
    if request_started_at is not None:
        total_ms = (time.perf_counter() - request_started_at) * 1000

    lines = [f"PERF SUMMARY {request_label()} status={status}"]
    for step, values in (timings or {}).items():
        label = step[:28].ljust(28, ".")
        count = values["count"]
        suffix = f" ({count}x, max {values['max_ms']:.1f} ms)" if count > 1 else ""
        if values["errors"]:
            suffix += f" errors={values['errors']}"
        lines.append(f"{label} {values['total_ms']:.1f} ms{suffix}")
    if total_ms is not None:
        lines.append(f"{'TOTAL'.ljust(28, '.')} {total_ms:.1f} ms")
    current_app.logger.info("\n".join(lines))


def sql_preview(statement):
    return re.sub(r"\s+", " ", statement or "").strip()[:240]
