"""Gemini native image generation helpers for educational diagrams."""

from __future__ import annotations

import base64
import os
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

from config import GEMINI_API_KEY


DEFAULT_GEMINI_IMAGE_MODEL = "gemini-3.1-flash-lite-image"
DEFAULT_IMAGE_TIMEOUT_SECONDS = 60.0
SUPPORTED_IMAGE_MIME_TYPES = {
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/gif",
    "image/bmp",
    "image/tiff",
    "image/heic",
    "image/heif",
}


class GeminiImageConfigurationError(RuntimeError):
    """Raised when Gemini image generation is not configured."""


class GeminiImageGenerationError(RuntimeError):
    """Raised when Gemini image generation fails."""


class GeminiImageTimeoutError(GeminiImageGenerationError):
    """Raised when Gemini image generation exceeds the configured timeout."""


class GeneratedDiagramImage(bytes):
    """Generated image bytes with MIME metadata from Gemini or byte detection."""

    def __new__(cls, data, mime_type):
        value = super().__new__(cls, data)
        value.mime_type = mime_type
        return value


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
    """Generate a diagram image with Gemini and return bytes with MIME metadata."""
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
            # Nano Banana 2 Lite supports 1K image generation.
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
    encoded_image = _image_field(output_image, "data")
    if not encoded_image:
        raise GeminiImageGenerationError("Gemini response did not include an image.")

    if isinstance(encoded_image, bytes):
        image_bytes = encoded_image
    else:
        try:
            image_bytes = base64.b64decode(encoded_image)
        except Exception as error:
            raise GeminiImageGenerationError("Gemini response image data was invalid.") from error

    mime_type = _resolved_image_mime_type(output_image, image_bytes)
    return GeneratedDiagramImage(image_bytes, mime_type)


def _image_field(output_image, field_name):
    if isinstance(output_image, dict):
        return output_image.get(field_name)
    return getattr(output_image, field_name, None)


def _resolved_image_mime_type(output_image, image_bytes):
    sdk_mime_type = _normalize_image_mime_type(_image_field(output_image, "mime_type"))
    detected_mime_type = _detect_image_mime_type(image_bytes)
    mime_type = detected_mime_type or sdk_mime_type
    if not mime_type:
        raise GeminiImageGenerationError(
            "Gemini response did not include a supported image MIME type."
        )
    return mime_type


def _normalize_image_mime_type(value):
    mime_type = str(value or "").split(";")[0].strip().lower()
    return mime_type if mime_type in SUPPORTED_IMAGE_MIME_TYPES else ""


def _detect_image_mime_type(data):
    if not data:
        return ""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data.startswith(b"BM"):
        return "image/bmp"
    if data.startswith((b"II*\x00", b"MM\x00*")):
        return "image/tiff"
    if len(data) >= 12 and data[4:8] == b"ftyp":
        brand = data[8:12].lower()
        if brand in {b"heic", b"heix", b"hevc", b"hevx"}:
            return "image/heic"
        if brand in {b"heif", b"heim", b"mif1", b"msf1"}:
            return "image/heif"
    return ""


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
