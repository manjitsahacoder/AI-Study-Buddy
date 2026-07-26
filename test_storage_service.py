import os
import unittest
from unittest.mock import patch

from services import storage_service


class FakeSupabaseStorageClient:
    def __init__(self):
        self.uploads = []
        self.deletions = []

    def upload(self, bucket, storage_path, image_bytes, *, content_type, upsert=True):
        self.uploads.append(
            {
                "bucket": bucket,
                "storage_path": storage_path,
                "image_bytes": image_bytes,
                "content_type": content_type,
                "upsert": upsert,
            }
        )

    def delete(self, bucket, storage_path):
        self.deletions.append({"bucket": bucket, "storage_path": storage_path})


class StorageServiceTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeSupabaseStorageClient()
        self.env_patch = patch.dict(
            os.environ,
            {
                "SUPABASE_URL": "https://study-buddy.supabase.co/",
                "SUPABASE_SERVICE_ROLE_KEY": "test-service-role-key",
            },
        )
        self.client_patch = patch(
            "services.storage_service._storage_client",
            return_value=self.client,
        )
        self.env_patch.start()
        self.client_patch.start()

    def tearDown(self):
        self.client_patch.stop()
        self.env_patch.stop()

    def test_upload_diagram_image_generates_structured_path_and_public_url(self):
        result = storage_service.upload_diagram_image(
            b"webp-bytes",
            "8/Science/NCERT Biology/Chapter 5 - Plants/Photosynthesis Diagram.png",
        )

        expected_path = (
            "class_8/science/ncert-biology/"
            "chapter-5-plants/photosynthesis-diagram.webp"
        )
        self.assertEqual(result["storage_path"], expected_path)
        self.assertEqual(
            result["public_url"],
            "https://study-buddy.supabase.co/storage/v1/object/public/"
            f"diagrams/{expected_path}",
        )
        self.assertEqual(
            self.client.uploads,
            [
                {
                    "bucket": "diagrams",
                    "storage_path": expected_path,
                    "image_bytes": b"webp-bytes",
                    "content_type": "image/webp",
                    "upsert": True,
                }
            ],
        )

    def test_delete_diagram_image_deletes_from_diagrams_bucket(self):
        storage_service.delete_diagram_image("class_8/science/ncert/chapter-1/topic.webp")

        self.assertEqual(
            self.client.deletions,
            [
                {
                    "bucket": "diagrams",
                    "storage_path": "class_8/science/ncert/chapter-1/topic.webp",
                }
            ],
        )

    def test_filename_sanitization_for_upload_path(self):
        result = storage_service.upload_diagram_image(
            b"image",
            "Class 10/Social Science/India & The World/Chapter: 2/Water Cycle!!.jpeg",
        )

        self.assertEqual(
            result["storage_path"],
            "class_10/social-science/india-and-the-world/chapter-2/water-cycle.webp",
        )

    def test_get_public_diagram_url_uses_configured_supabase_url(self):
        public_url = storage_service.get_public_diagram_url(
            "class_9/science/ncert/chapter 1/cell division.webp"
        )

        self.assertEqual(
            public_url,
            "https://study-buddy.supabase.co/storage/v1/object/public/"
            "diagrams/class_9/science/ncert/chapter-1/cell-division.webp",
        )


if __name__ == "__main__":
    unittest.main()
