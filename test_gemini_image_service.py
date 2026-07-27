import base64
import os
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from services import gemini_image_service


class FakeInteractions:
    def __init__(self, response=None, error=None, delay=0):
        self.response = response
        self.error = error
        self.delay = delay
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.delay:
            time.sleep(self.delay)
        if self.error:
            raise self.error
        return self.response


class FakeClient:
    def __init__(self, interactions):
        self.interactions = interactions


class GeminiImageServiceTests(unittest.TestCase):
    def test_build_diagram_prompt_contains_required_educational_constraints(self):
        prompt = gemini_image_service.build_diagram_prompt(
            "CBSE",
            "8",
            "Science",
            "NCERT",
            "Crop Production",
            "Irrigation methods",
        )

        self.assertIn("Board: CBSE", prompt)
        self.assertIn("Class: 8", prompt)
        self.assertIn("Subject: Science", prompt)
        self.assertIn("Textbook: NCERT", prompt)
        self.assertIn("Chapter: Crop Production", prompt)
        self.assertIn("Topic: Irrigation methods", prompt)
        self.assertIn("White background only.", prompt)
        self.assertIn("Flat vector-style appearance", prompt)
        self.assertIn("Clearly labeled parts", prompt)
        self.assertIn("No watermark", prompt)
        self.assertIn("Suitable for CBSE students", prompt)

    def test_generate_diagram_image_returns_raw_bytes_from_mocked_gemini_response(self):
        image_bytes = b"generated-webp-bytes"
        response = SimpleNamespace(
            output_image=SimpleNamespace(
                data=base64.b64encode(image_bytes).decode("ascii"),
                mime_type="image/webp",
            )
        )
        interactions = FakeInteractions(response=response)
        client = FakeClient(interactions)

        with patch.dict(
            os.environ,
            {
                "GEMINI_API_KEY": "test-key",
                "GEMINI_IMAGE_MODEL": "gemini-3.1-flash-image",
            },
        ), patch(
            "services.gemini_image_service._create_genai_client",
            return_value=client,
        ) as create_client:
            result = gemini_image_service.generate_diagram_image("Draw photosynthesis.")

        self.assertEqual(result, image_bytes)
        self.assertEqual(result.mime_type, "image/webp")
        create_client.assert_called_once_with("test-key")
        self.assertEqual(
            interactions.calls,
            [
                {
                    "model": "gemini-3.1-flash-image",
                    "input": "Draw photosynthesis.",
                    "response_format": {
                        "type": "image",
                        "aspect_ratio": "4:3",
                        "image_size": "1K",
                    },
                }
            ],
        )

    def test_generate_diagram_image_handles_timeout_without_real_network_call(self):
        interactions = FakeInteractions(
            response=SimpleNamespace(output_image=SimpleNamespace(data="")),
            delay=0.1,
        )
        client = FakeClient(interactions)

        with patch.dict(
            os.environ,
            {
                "GEMINI_API_KEY": "test-key",
                "GEMINI_IMAGE_TIMEOUT_SECONDS": "0.01",
            },
        ), patch(
            "services.gemini_image_service._create_genai_client",
            return_value=client,
        ):
            with self.assertRaises(gemini_image_service.GeminiImageTimeoutError):
                gemini_image_service.generate_diagram_image("Draw a water cycle.")

    def test_generate_diagram_image_wraps_api_errors_without_real_network_call(self):
        interactions = FakeInteractions(error=RuntimeError("API unavailable"))
        client = FakeClient(interactions)

        with patch.dict(
            os.environ,
            {"GEMINI_API_KEY": "test-key"},
        ), patch(
            "services.gemini_image_service._create_genai_client",
            return_value=client,
        ):
            with self.assertRaises(gemini_image_service.GeminiImageGenerationError) as context:
                gemini_image_service.generate_diagram_image("Draw a plant cell.")

        self.assertIn("Gemini image generation failed", str(context.exception))

    def test_image_generation_timeout_reads_diagram_specific_environment_alias(self):
        with patch.dict(
            os.environ,
            {
                "DIAGRAM_IMAGE_GENERATION_TIMEOUT_SECONDS": "12.5",
                "GEMINI_IMAGE_TIMEOUT_SECONDS": "0.01",
            },
        ):
            self.assertEqual(gemini_image_service._gemini_image_timeout_seconds(), 12.5)


if __name__ == "__main__":
    unittest.main()
