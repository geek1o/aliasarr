from __future__ import annotations

import logging
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger("aliasarr.collections")


def cleanup_empty_collections(db: Session, collection_id: Optional[int] = None) -> list[int]:
    """
    Автоматически удаляет карточки коллекций, в которых не осталось ни одного фильма в библиотеке,
    а также стирает локальные обложки и бэкдропы с диска.
    """
    deleted_ids: list[int] = []
    try:
        from app.models.db import MovieCollection, Show
        from app.services.cover_service import delete_collection_cover

        if collection_id is not None:
            coll = db.get(MovieCollection, collection_id)
            if coll:
                has_shows = db.query(Show.id).filter(Show.collection_id == collection_id).first() is not None
                if not has_shows:
                    c_id = coll.id
                    c_title = getattr(coll, "title", str(c_id))
                    db.delete(coll)
                    db.commit()
                    delete_collection_cover(c_id)
                    deleted_ids.append(c_id)
                    logger.info("Коллекция #%s «%s» автоматически удалена, так как в ней не осталось фильмов в библиотеке", c_id, c_title)
        else:
            colls = db.query(MovieCollection).all()
            for coll in colls:
                has_shows = db.query(Show.id).filter(Show.collection_id == coll.id).first() is not None
                if not has_shows:
                    c_id = coll.id
                    c_title = getattr(coll, "title", str(c_id))
                    db.delete(coll)
                    delete_collection_cover(c_id)
                    deleted_ids.append(c_id)
                    logger.info("Коллекция #%s «%s» автоматически удалена, так как в ней не осталось фильмов в библиотеке", c_id, c_title)
            if deleted_ids:
                db.commit()
    except Exception as e:
        logger.warning("Ошибка при очистке пустых коллекций: %s", e)
    return deleted_ids
