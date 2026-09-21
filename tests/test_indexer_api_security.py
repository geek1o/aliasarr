from __future__ import annotations

import logging
import unittest
from unittest.mock import MagicMock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.download_clients import DownloadClientIn, DownloadClientOut, update_download_client
from app.api.indexers import _indexer_out, update_indexer
from app.models.db import Base, DownloadClient, Indexer
from app.schemas import IndexerCreate
from app.services.log_safety import redact_sensitive_data


class IndexerApiSecurityTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_output_reports_presence_without_exposing_api_key(self):
        indexer = Indexer(
            name="Kinozal",
            type="torznab",
            base_url="http://indexer.invalid",
            api_key="secret-value",
        )
        self.db.add(indexer)
        self.db.commit()
        self.db.refresh(indexer)

        payload = _indexer_out(indexer).model_dump()

        self.assertTrue(payload["has_api_key"])
        self.assertNotIn("api_key", payload)
        self.assertNotIn("secret-value", repr(payload))

    def test_http_transport_info_logs_are_suppressed(self):
        import app.main  # noqa: F401

        self.assertGreaterEqual(logging.getLogger("httpx").getEffectiveLevel(), logging.WARNING)
        self.assertGreaterEqual(logging.getLogger("httpcore").getEffectiveLevel(), logging.WARNING)

    def test_http_exception_urls_are_redacted_before_logging(self):
        secret = "do-not-leak"
        message = (
            "Client error for url "
            f"'https://indexer.test/api?t=search&apikey={secret}&q=example'"
        )

        sanitized = redact_sensitive_data(message)

        self.assertNotIn(secret, sanitized)
        self.assertIn("apikey=<redacted>", sanitized)
        self.assertIn("q=example", sanitized)

    def test_blank_key_on_update_preserves_stored_secret(self):
        indexer = Indexer(
            name="Kinozal",
            type="torznab",
            base_url="http://indexer.invalid",
            api_key="secret-value",
        )
        self.db.add(indexer)
        self.db.commit()

        result = update_indexer(
            indexer.id,
            IndexerCreate(
                name="Kinozal updated",
                type="torznab",
                base_url="http://indexer.invalid",
                api_key=None,
            ),
            db=self.db,
            current_user=MagicMock(),
        )

        self.db.refresh(indexer)
        self.assertEqual(indexer.api_key, "secret-value")
        self.assertTrue(result.has_api_key)
        self.assertNotIn("api_key", result.model_dump())

    def test_download_client_output_and_blank_update_do_not_expose_or_clear_password(self):
        client = DownloadClient(
            name="Transmission",
            type="transmission",
            host="download-client.invalid",
            port=9091,
            password="secret-password",
        )
        self.db.add(client)
        self.db.commit()
        self.db.refresh(client)

        before = DownloadClientOut.model_validate(client).model_dump()
        result = update_download_client(
            client.id,
            DownloadClientIn(
                name="Transmission updated",
                type="transmission",
                host="download-client.invalid",
                port=9091,
                password=None,
            ),
            db=self.db,
            current_user=MagicMock(),
        )

        self.db.refresh(client)
        self.assertNotIn("password", before)
        self.assertNotIn("secret-password", repr(before))
        self.assertEqual(client.password, "secret-password")
        self.assertNotIn("password", DownloadClientOut.model_validate(result).model_dump())


if __name__ == "__main__":
    unittest.main()
