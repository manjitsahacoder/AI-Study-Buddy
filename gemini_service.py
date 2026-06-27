import re
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class GeminiErrorInfo:
    code: str
    title: str
    message: str
    status_code: int = 503


class GeminiRequestError(Exception):
    def __init__(self, error_info, original_error):
        super().__init__(error_info.message)
        self.error_info = error_info
        self.original_error = original_error


def estimate_tokens(text):
    return max(1, (len(text or "") + 3) // 4)


def sanitize_error_text(error):
    text = str(error)
    text = re.sub(r"AIza[0-9A-Za-z_\-]{20,}", "[REDACTED_API_KEY]", text)
    text = re.sub(
        r"(?i)(api[_\s-]?key\s*[=:]\s*)[^\s,;]+",
        r"\1[REDACTED]",
        text,
    )
    return text


def classify_gemini_exception(error):
    error_type = type(error).__name__
    error_text = sanitize_error_text(error).lower()
    combined = f"{error_type.lower()} {error_text}"

    if "timeout" in combined or "timed out" in combined or "deadline" in combined:
        return GeminiErrorInfo(
            code="timeout",
            title="AI Timeout",
            message="The AI is taking longer than expected.\n\nPlease try again in a moment.",
            status_code=503,
        )

    if (
        "invalid api key" in combined
        or "api key not valid" in combined
        or "invalid_api_key" in combined
        or "unauthenticated" in combined
        or "permission_denied" in combined
        or "401" in combined
        or "403" in combined
    ):
        return GeminiErrorInfo(
            code="invalid_api_key",
            title="AI Configuration Issue",
            message="The AI service is temporarily unavailable because of a configuration issue.",
            status_code=503,
        )

    quota_terms = ("quota exhausted", "quota has been reached", "quota reached", "quota exceeded")
    if "resource_exhausted" in combined or any(term in combined for term in quota_terms):
        return GeminiErrorInfo(
            code="quota_exhausted",
            title="AI Quota Reached",
            message="The project's free AI quota has been reached.\n\nPlease try again later.",
            status_code=503,
        )

    if "429" in combined or "rate limit" in combined or "ratelimit" in combined:
        return GeminiErrorInfo(
            code="rate_limit",
            title="Rate Limit Reached",
            message=(
                "The free Gemini API allows only a limited number of requests per minute.\n\n"
                "Please wait about one minute before trying again.\n\n"
                "Your work has already been saved."
            ),
            status_code=429,
        )

    network_terms = (
        "network",
        "connection",
        "connect",
        "dns",
        "unreachable",
        "temporary failure",
        "connection reset",
        "connection aborted",
    )
    if any(term in combined for term in network_terms):
        return GeminiErrorInfo(
            code="network_error",
            title="AI Network Error",
            message="Unable to contact the AI service.\n\nPlease check your internet connection and try again.",
            status_code=503,
        )

    return GeminiErrorInfo(
        code="unknown",
        title="AI Service Unavailable",
        message="The AI service is temporarily unavailable. Please try again in a moment.",
        status_code=503,
    )


def log_gemini_request(
    logger,
    feature_name,
    prompt,
    response_text="",
    started_at=None,
    exception=None,
    user_id=None,
    lesson_id=None,
):
    exception_type = type(exception).__name__ if exception else "None"
    fields = {
        "feature": feature_name,
        "prompt_length": len(prompt or ""),
        "estimated_tokens": estimate_tokens(prompt),
        "response_length": len(response_text or ""),
        "execution_time_seconds": round(time.perf_counter() - started_at, 3)
        if started_at is not None
        else 0,
        "exception_type": exception_type,
        "user_id": user_id if user_id is not None else "anonymous",
        "lesson_id": lesson_id if lesson_id is not None else "none",
    }
    details = " ".join(f"{key}={value}" for key, value in fields.items())
    logger.info("gemini_request %s", details)


def handle_gemini_exception(
    error,
    logger,
    feature_name,
    prompt,
    started_at=None,
    user_id=None,
    lesson_id=None,
):
    error_info = classify_gemini_exception(error)
    log_gemini_request(
        logger,
        feature_name,
        prompt,
        started_at=started_at,
        exception=error,
        user_id=user_id,
        lesson_id=lesson_id,
    )
    safe_error_text = sanitize_error_text(error)
    if error_info.code == "unknown":
        sanitized_error = RuntimeError(f"{type(error).__name__}: {safe_error_text}")
        logger.error(
            "Unknown Gemini exception feature=%s user_id=%s lesson_id=%s",
            feature_name,
            user_id if user_id is not None else "anonymous",
            lesson_id if lesson_id is not None else "none",
            exc_info=(RuntimeError, sanitized_error, error.__traceback__),
        )
    else:
        logger.warning(
            "Handled Gemini exception feature=%s code=%s exception_type=%s user_id=%s lesson_id=%s error=%s",
            feature_name,
            error_info.code,
            type(error).__name__,
            user_id if user_id is not None else "anonymous",
            lesson_id if lesson_id is not None else "none",
            safe_error_text,
        )
    return error_info
