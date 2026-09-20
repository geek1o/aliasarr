from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.db import Show, User
from app.schemas import ReleaseInspectorRequest, ReleaseInspectorResponse
from app.services.release_inspector import inspect_release
from app.services.user_service import require_permission

router = APIRouter(prefix="/api/v1/release-inspector", tags=["release-inspector"])


@router.post("", response_model=ReleaseInspectorResponse)
def inspect_release_title(
    payload: ReleaseInspectorRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manual_search")),
):
    """Разбирает релиз текущими parser/matcher/DecisionEngine без побочных действий."""
    show = None
    if payload.show_id is not None:
        show = db.get(Show, payload.show_id)
        if show is None:
            raise HTTPException(status_code=404, detail="Тайтл не найден")

    return inspect_release(
        db,
        title=payload.title,
        show=show,
        season=payload.season,
        episode=payload.episode,
        size_bytes=payload.size_bytes,
        seeders=payload.seeders,
        categories=payload.categories,
        torrent_hash=payload.torrent_hash,
        guid=payload.guid,
        download_url=payload.download_url,
    )
