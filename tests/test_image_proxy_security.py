from __future__ import annotations

import asyncio
import unittest

from fastapi import HTTPException

from app.api.metadata_routes import _read_limited_image_response, _validate_proxy_image_url
from app.api.shows import _read_upload_with_limit


class FakeUpload:
    def __init__(self, data: bytes):
        self.data = data
        self.offset = 0

    async def read(self, size: int = -1) -> bytes:
        if self.offset >= len(self.data):
            return b""
        end = len(self.data) if size < 0 else min(len(self.data), self.offset + size)
        chunk = self.data[self.offset:end]
        self.offset = end
        return chunk


class FakeResponse:
    def __init__(self, chunks: list[bytes], headers: dict[str, str]):
        self.chunks = chunks
        self.headers = headers

    async def aiter_bytes(self):
        for chunk in self.chunks:
            yield chunk


class TestImageProxySecurity(unittest.TestCase):
    def test_allowlist_matches_parsed_hostname(self):
        self.assertEqual(
            _validate_proxy_image_url("https://artworks.thetvdb.com/banner.jpg"),
            "https://artworks.thetvdb.com/banner.jpg",
        )
        with self.assertRaises(HTTPException):
            _validate_proxy_image_url("http://thetvdb.com@127.0.0.1/private")
        with self.assertRaises(HTTPException):
            _validate_proxy_image_url("https://thetvdb.com.attacker.example/image.jpg")

    def test_remote_image_stream_has_hard_limit(self):
        response = FakeResponse(
            [b"1234", b"5678"],
            {"content-type": "image/jpeg"},
        )
        with self.assertRaises(HTTPException) as raised:
            asyncio.run(_read_limited_image_response(response, max_bytes=7))
        self.assertEqual(raised.exception.status_code, 413)

    def test_remote_response_must_be_image(self):
        response = FakeResponse([b"not an image"], {"content-type": "text/html"})
        with self.assertRaises(HTTPException) as raised:
            asyncio.run(_read_limited_image_response(response))
        self.assertEqual(raised.exception.status_code, 415)

    def test_cover_upload_has_hard_limit(self):
        upload = FakeUpload(b"123456")
        with self.assertRaises(HTTPException) as raised:
            asyncio.run(_read_upload_with_limit(upload, max_bytes=5))
        self.assertEqual(raised.exception.status_code, 413)


if __name__ == "__main__":
    unittest.main()
