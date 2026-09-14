from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

try:
    import sqlalchemy  # noqa: F401
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.api.shows import delete_show
    from app.api.collections_routes import list_collections
    from app.models.db import Base, Show, MovieCollection, User
    from app.services.collection_service import cleanup_empty_collections
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False


@unittest.skipUnless(HAS_DEPS, "SQLAlchemy / FastAPI not installed in host runner")
class TestCollectionsCleanup(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)
        self.db = self.SessionLocal()
        self.user = User(username="admin", password_hash="hash", is_admin=True, is_owner=True)
        self.db.add(self.user)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    @patch("app.services.collection_service.delete_collection_cover")
    def test_collection_deleted_when_last_movie_deleted(self, mock_delete_cover):
        # 1. Создаем коллекцию и 2 фильма
        coll = MovieCollection(title="Франшиза Джокер", tmdb_collection_id=12345)
        self.db.add(coll)
        self.db.flush()

        movie1 = Show(title="Джокер", content_type="movie", collection_id=coll.id)
        movie2 = Show(title="Джокер: Безумие на двоих", content_type="movie", collection_id=coll.id)
        self.db.add_all([movie1, movie2])
        self.db.commit()

        coll_id = coll.id
        movie1_id = movie1.id
        movie2_id = movie2.id

        # 2. Удаляем первый фильм
        asyncio.run(delete_show(movie1_id, delete_files=False, db=self.db, current_user=self.user))

        # Проверяем, что коллекция все еще существует, так как в ней остался movie2
        self.assertIsNotNone(self.db.get(MovieCollection, coll_id))
        self.assertFalse(mock_delete_cover.called)

        # 3. Удаляем второй (последний) фильм
        asyncio.run(delete_show(movie2_id, delete_files=False, db=self.db, current_user=self.user))

        # Проверяем, что коллекция автоматически удалилась из БД и вызвана очистка обложек
        self.assertIsNone(self.db.get(MovieCollection, coll_id))
        mock_delete_cover.assert_called_once_with(coll_id)

    @patch("app.services.collection_service.delete_collection_cover")
    def test_cleanup_empty_collections_bulk(self, mock_delete_cover):
        # Создаем пустую коллекцию без фильмов и коллекцию с фильмом
        empty_coll = MovieCollection(title="Пустая Сага", tmdb_collection_id=999)
        active_coll = MovieCollection(title="Активная Сага", tmdb_collection_id=888)
        self.db.add_all([empty_coll, active_coll])
        self.db.flush()

        active_movie = Show(title="Активный фильм", content_type="movie", collection_id=active_coll.id)
        self.db.add(active_movie)
        self.db.commit()

        empty_id = empty_coll.id
        active_id = active_coll.id

        # Запуск массовой очистки
        deleted_ids = cleanup_empty_collections(self.db)
        self.assertIn(empty_id, deleted_ids)
        self.assertNotIn(active_id, deleted_ids)

        self.assertIsNone(self.db.get(MovieCollection, empty_id))
        self.assertIsNotNone(self.db.get(MovieCollection, active_id))
        mock_delete_cover.assert_called_once_with(empty_id)

    @patch("app.services.collection_service.delete_collection_cover")
    def test_list_collections_cleans_up_orphans(self, mock_delete_cover):
        empty_coll = MovieCollection(title="Одинокая Сага", tmdb_collection_id=777)
        self.db.add(empty_coll)
        self.db.commit()
        empty_id = empty_coll.id

        result = list_collections(db=self.db, current_user=self.user)
        self.assertEqual(len(result), 0)
        self.assertIsNone(self.db.get(MovieCollection, empty_id))
