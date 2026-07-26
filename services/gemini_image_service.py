"""Gemini native image generation helpers for educational diagrams."""

from __future__ import annotations

import base64
import os
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

from config import GEMINI_API_KEY


DEFAULT_GEMINI_IMAGE_MODEL = "gemini-3.1-flash-image"
DEFAULT_IMAGE_TIMEOUT_SECONDS = 60.0


class GeminiImageConfigurationError(RuntimeError):
    """Raised when Gemini image generation is not configured."""


class GeminiImageGenerationError(RuntimeError):
    """Raised when Gemini image generation fails."""


class GeminiImageTimeoutError(GeminiImageGenerationError):
    """Raised when Gemini image generation exceeds the configured timeout."""


def build_diagram_prompt(board, student_class, subject, textbook, chapter, topic):
    """Build a CBSE-focused prompt for a clean textbook diagram."""
    return "\n".join(
        (
            "Create one clean educational textbook diagram for AI Study Buddy.",
            f"Board: {board or 'CBSE'}",
            f"Class: {student_class or 'unspecified'}",
            f"Subject: {subject or 'unspecified'}",
            f"Textbook: {textbook or 'unspecified'}",
            f"Chapter: {chapter or 'unspecified'}",
            f"Topic: {topic or 'unspecified'}",
            "",
            "Diagram requirements:",
            "- White background only.",
            "- Flat vector-style appearance with crisp outlines and simple colors.",
            "- Clearly labeled parts using short, readable English labels.",
            "- Use arrows, callouts, and spacing appropriate for school textbook diagrams.",
            "- No watermark, no logo, no decorative border, no photorealistic rendering.",
            "- Suitable for CBSE students and accurate for the stated class level.",
            "- Return only the finished diagram image.",
        )
    )


def generate_diagram_image(prompt):
    """Generate a diagram image with Gemini and return raw image bytes only."""
    if not prompt or not str(prompt).strip():
        raise ValueError("prompt is required")

    api_key = _gemini_api_key()
    model_name = _gemini_image_model()
    timeout_seconds = _gemini_image_timeout_seconds()
    client = _create_genai_client(api_key)

    try:
        response = _run_with_timeout(
            lambda: _run_image_generation(client, model_name, str(prompt)),
            timeout_seconds,
        )
        return _extract_image_bytes(response)
    except GeminiImageTimeoutError:
        raise
    except GeminiImageGenerationError:
        raise
    except Exception as error:
        raise GeminiImageGenerationError(
            f"Gemini image generation failed: {error}"
        ) from error


def _run_image_generation(client, model_name, prompt):
    return client.interactions.create(
        model=model_name,
        input=prompt,
        response_format={
            "type": "image",
            "aspect_ratio": "4:3",
            "image_size": "1K",
        },
    )


def _run_with_timeout(factory, timeout_seconds):
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(factory)
    try:
        return future.result(timeout=timeout_seconds)
    except FutureTimeoutError as error:
        future.cancel()
        raise GeminiImageTimeoutError(
            f"Gemini image generation exceeded {timeout_seconds:g} seconds."
        ) from error
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def _extract_image_bytes(response):
    output_image = getattr(response, "output_image", None)
    encoded_image = getattr(output_image, "data", None)
    if not encoded_image:
        raise GeminiImageGenerationError("Gemini response did not include an image.")

    if isinstance(encoded_image, bytes):
        return encoded_image

    try:
        return base64.b64decode(encoded_image)
    except Exception as error:
        raise GeminiImageGenerationError("Gemini response image data was invalid.") from error


def _create_genai_client(api_key):
    try:
        from google import genai
    except ImportError as error:
        raise GeminiImageConfigurationError(
            "google-genai is required for Gemini image generation."
        ) from error

    return genai.Client(api_key=api_key)


def _gemini_api_key():
    api_key = os.environ.get("GEMINI_API_KEY") or GEMINI_API_KEY
    if not api_key:
        raise GeminiImageConfigurationError("GEMINI_API_KEY is required.")
    return api_key


def _gemini_image_model():
    configured_model = os.environ.get(
        "GEMINI_IMAGE_MODEL",
        DEFAULT_GEMINI_IMAGE_MODEL,
    ).strip()
    return configured_model or DEFAULT_GEMINI_IMAGE_MODEL


def _gemini_image_timeout_seconds():
    raw_timeout = (
        os.environ.get("DIAGRAM_IMAGE_GENERATION_TIMEOUT_SECONDS", "")
        or os.environ.get("GEMINI_IMAGE_TIMEOUT_SECONDS", "")
    )
    if not raw_timeout:
        return DEFAULT_IMAGE_TIMEOUT_SECONDS
    try:
        timeout_seconds = float(raw_timeout)
    except ValueError as error:
        raise GeminiImageConfigurationError(
            "GEMINI_IMAGE_TIMEOUT_SECONDS must be a number."
        ) from error
    if timeout_seconds <= 0:
        raise GeminiImageConfigurationError(
            "GEMINI_IMAGE_TIMEOUT_SECONDS must be greater than 0."
        )
    return timeout_seconds
