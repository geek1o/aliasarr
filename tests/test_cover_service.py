from __future__ import annotations

import asyncio
import base64
import io
import os
import shutil
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.cover_service import (
    get_media_cover_dir,
    get_show_poster_dir,
    get_show_poster_path,
    get_collection_poster_dir,
    get_collection_poster_path,
    optimize_image,
    save_show_poster,
    save_collection_poster,
    delete_show_cover,
    delete_collection_cover,
    get_cover_etag,
    download_and_store_show_cover,
    download_and_store_collection_cover,
    backfill_existing_covers,
)

try:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from fastapi import HTTPException
    from fastapi.responses import Response
    from app.models.db import Base, Show, MovieCollection, User, UserRole
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False


class TestCoverServiceFilesystem(unittest.TestCase):
    """Тестирование файловых операций, путей, ETag и конвертации без обязательных внешних библиотек."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.orig_env = os.environ.get("MEDIA_COVER_DIR")
        os.environ["MEDIA_COVER_DIR"] = self.temp_dir

    def tearDown(self):
        if self.orig_env is not None:
            os.environ["MEDIA_COVER_DIR"] = self.orig_env
        else:
            os.environ.pop("MEDIA_COVER_DIR", None)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_paths_resolution(self):
        self.assertEqual(get_media_cover_dir(), self.temp_dir)
        show_dir = get_show_poster_dir(42)
        self.assertEqual(show_dir, os.path.join(self.temp_dir, "shows", "42"))
        show_path = get_show_poster_path(42)
        self.assertEqual(show_path, os.path.join(self.temp_dir, "shows", "42", "poster.jpg"))

        coll_dir = get_collection_poster_dir(99)
        self.assertEqual(coll_dir, os.path.join(self.temp_dir, "collections", "99"))
        coll_path = get_collection_poster_path(99)
        self.assertEqual(coll_path, os.path.join(self.temp_dir, "collections", "99", "poster.jpg"))

    def test_optimize_image_fallback(self):
        raw_bytes = b"fake_image_bytes_12345"
        out = optimize_image(raw_bytes)
        self.assertEqual(out, raw_bytes)

    def test_save_and_etag_show_poster(self):
        sample_bytes = b"\xff\xd8\xff\xe0sample_jpeg_content"
        url = asyncio.run(save_show_poster(10, sample_bytes))
        self.assertEqual(url, "/api/v1/shows/10/poster")

        target_file = get_show_poster_path(10)
        self.assertTrue(os.path.isfile(target_file))
        with open(target_file, "rb") as f:
            self.assertEqual(f.read(), sample_bytes)

        etag = get_cover_etag(target_file)
        self.assertIsNotNone(etag)
        self.assertTrue(etag.startswith('"') and etag.endswith('"'))

        # Non-existent file etag
        self.assertIsNone(get_cover_etag(os.path.join(self.temp_dir, "non_existent.jpg")))

    def test_save_and_delete_collection_poster(self):
        sample_bytes = b"collection_sample_bytes"
        url = asyncio.run(save_collection_poster(20, sample_bytes))
        self.assertEqual(url, "/api/v1/collections/20/poster")

        target_file = get_collection_poster_path(20)
        self.assertTrue(os.path.isfile(target_file))

        # Delete collection cover
        deleted = delete_collection_cover(20)
        self.assertTrue(deleted)
        self.assertFalse(os.path.exists(get_collection_poster_dir(20)))

        # Deleting again returns False
        self.assertFalse(delete_collection_cover(20))

    def test_delete_show_cover(self):
        asyncio.run(save_show_poster(77, b"sample_show_cover"))
        self.assertTrue(os.path.exists(get_show_poster_dir(77)))

        self.assertTrue(delete_show_cover(77))
        self.assertFalse(os.path.exists(get_show_poster_dir(77)))
        self.assertFalse(delete_show_cover(77))

    def test_download_and_store_show_cover_base64(self):
        raw = b"hello_base64_image"
        b64_str = f"data:image/jpeg;base64,{base64.b64encode(raw).decode('ascii')}"

        res = asyncio.run(download_and_store_show_cover(55, b64_str))
        self.assertEqual(res, "/api/v1/shows/55/poster")
        self.assertTrue(os.path.isfile(get_show_poster_path(55)))
        with open(get_show_poster_path(55), "rb") as f:
            self.assertEqual(f.read(), raw)

    def test_download_and_store_show_cover_http(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"downloaded_http_bytes"

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_httpx = MagicMock()
        mock_httpx.AsyncClient.return_value = mock_client

        with patch.dict("sys.modules", {"httpx": mock_httpx}):
            res = asyncio.run(download_and_store_show_cover(88, "https://cdn.example.com/poster.jpg"))
            self.assertEqual(res, "/api/v1/shows/88/poster")
            self.assertTrue(os.path.isfile(get_show_poster_path(88)))

    def test_download_and_store_collection_cover_http(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"collection_downloaded_bytes"

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_httpx = MagicMock()
        mock_httpx.AsyncClient.return_value = mock_client

        with patch.dict("sys.modules", {"httpx": mock_httpx}):
            res = asyncio.run(download_and_store_collection_cover(99, "https://image.tmdb.org/t/p/original/coll.jpg"))
            self.assertEqual(res, "/api/v1/collections/99/poster")
            self.assertTrue(os.path.isfile(get_collection_poster_path(99)))


@unittest.skipUnless(HAS_DEPS, "Requires sqlalchemy, fastapi, and pydantic")
class TestCoverServiceEndpointsAndDb(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.orig_env = os.environ.get("MEDIA_COVER_DIR")
        os.environ["MEDIA_COVER_DIR"] = self.temp_dir

        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()

        self.user = User(
            id=1,
            username="admin",
            role=UserRole.ADMIN,
            is_active=True,
            password_hash="hash",
        )
        self.db.add(self.user)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        if self.orig_env is not None:
            os.environ["MEDIA_COVER_DIR"] = self.orig_env
        else:
            os.environ.pop("MEDIA_COVER_DIR", None)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_backfill_existing_covers(self):
        s1 = Show(
            title="Show CDN",
            poster_url="https://image.tmdb.org/t/p/original/show1.jpg",
        )
        raw_b64 = base64.b64encode(b"show2_bytes").decode("ascii")
        s2 = Show(
            title="Show Base64",
            poster_url=f"data:image/jpeg;base64,{raw_b64}",
        )
        s3 = Show(
            title="Show No Poster",
            poster_url=None,
        )
        self.db.add_all([s1, s2, s3])
        self.db.commit()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"show1_downloaded_bytes"

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_httpx = MagicMock()
        mock_httpx.AsyncClient.return_value = mock_client

        with patch.dict("sys.modules", {"httpx": mock_httpx}):
            res = asyncio.run(backfill_existing_covers(self.db))
            self.assertEqual(res["total"], 3)
            self.assertEqual(res["migrated"], 2)

            self.db.refresh(s1)
            self.db.refresh(s2)
            self.assertEqual(s1.poster_url, f"/api/v1/shows/{s1.id}/poster")
            self.assertEqual(s1.poster_source_url, "https://image.tmdb.org/t/p/original/show1.jpg")
            self.assertTrue(os.path.isfile(get_show_poster_path(s1.id)))

            self.assertEqual(s2.poster_url, f"/api/v1/shows/{s2.id}/poster")
            self.assertTrue(os.path.isfile(get_show_poster_path(s2.id)))

    def test_get_show_poster_endpoint_and_caching(self):
        from app.api.shows import get_show_poster

        s = Show(title="Test Endpoint Show", poster_url=None)
        self.db.add(s)
        self.db.commit()

        req_mock = MagicMock()
        req_mock.headers = {}

        # 1. 404 when file and source url not present
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(get_show_poster(s.id, req_mock, db=self.db))
        self.assertEqual(ctx.exception.status_code, 404)

        # 2. Save file and get 200 FileResponse with ETag
        sample_img = b"endpoint_test_jpeg"
        asyncio.run(save_show_poster(s.id, sample_img))

        resp = asyncio.run(get_show_poster(s.id, req_mock, db=self.db))
        self.assertEqual(resp.media_type, "image/jpeg")
        self.assertIn("Cache-Control", resp.headers)
        etag = resp.headers.get("ETag")
        self.assertIsNotNone(etag)

        # 3. 304 Not Modified when If-None-Match matches ETag
        req_mock_cached = MagicMock()
        req_mock_cached.headers = {"if-none-match": etag}
        resp304 = asyncio.run(get_show_poster(s.id, req_mock_cached, db=self.db))
        self.assertEqual(resp304.status_code, 304)

    def test_upload_show_cover_endpoint(self):
        from app.api.shows import upload_show_cover
        from starlette.datastructures import UploadFile

        s = Show(title="Upload Show", poster_url=None)
        self.db.add(s)
        self.db.commit()

        file_bytes = b"manual_uploaded_poster_data"
        upload_obj = UploadFile(filename="poster.jpg", file=io.BytesIO(file_bytes))

        resp = asyncio.run(upload_show_cover(s.id, file=upload_obj, db=self.db, current_user=self.user))
        self.assertTrue(resp["success"])
        self.assertEqual(resp["poster_url"], f"/api/v1/shows/{s.id}/poster")

        self.db.refresh(s)
        self.assertEqual(s.poster_url, f"/api/v1/shows/{s.id}/poster")
        self.assertTrue(os.path.isfile(get_show_poster_path(s.id)))
        with open(get_show_poster_path(s.id), "rb") as f:
            self.assertEqual(f.read(), file_bytes)

    def test_get_collection_poster_endpoint(self):
        from app.api.collections_routes import get_collection_poster

        coll = MovieCollection(title="Test Coll", tmdb_collection_id=12345)
        self.db.add(coll)
        self.db.commit()

        req_mock = MagicMock()
        req_mock.headers = {}

        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(get_collection_poster(coll.id, req_mock, db=self.db))
        self.assertEqual(ctx.exception.status_code, 404)

        asyncio.run(save_collection_poster(coll.id, b"coll_image_content"))
        resp = asyncio.run(get_collection_poster(coll.id, req_mock, db=self.db))
        self.assertEqual(resp.media_type, "image/jpeg")
        etag = resp.headers.get("ETag")
        self.assertIsNotNone(etag)

        req_cached = MagicMock()
        req_cached.headers = {"if-none-match": etag}
        resp304 = asyncio.run(get_collection_poster(coll.id, req_cached, db=self.db))
        self.assertEqual(resp304.status_code, 304)

    def test_delete_show_deletes_cover_folder(self):
        from app.schemas import DeleteContentPayload
        from app.api.shows import delete_content

        s = Show(title="Show To Delete", poster_url=None)
        self.db.add(s)
        self.db.commit()

        asyncio.run(save_show_poster(s.id, b"show_cover_data"))
        self.assertTrue(os.path.isfile(get_show_poster_path(s.id)))

        payload = DeleteContentPayload(delete_mode="show", delete_files=False)
        res = asyncio.run(delete_content(s.id, payload, db=self.db, current_user=self.user))
        self.assertTrue(res.success)
        self.assertFalse(os.path.exists(get_show_poster_dir(s.id)))

    def test_delete_collection_deletes_cover_folder(self):
        from app.api.collections_routes import delete_collection

        coll = MovieCollection(title="Coll To Delete", tmdb_collection_id=54321)
        self.db.add(coll)
        self.db.commit()

        asyncio.run(save_collection_poster(coll.id, b"coll_cover_data"))
        self.assertTrue(os.path.isfile(get_collection_poster_path(coll.id)))

        res = delete_collection(coll.id, db=self.db, current_user=self.user)
        self.assertTrue(res.get("success", False))
        self.assertFalse(os.path.exists(get_collection_poster_dir(coll.id)))
