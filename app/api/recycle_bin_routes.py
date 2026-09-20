from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.db import User
from app.services.audit_service import log_audit
from app.services.path_security import configured_library_roots
from app.services.recycle_bin import (
    find_recycled_media,
    list_recycled_media,
    purge_expired_recycled_media,
    purge_recycled_media,
    restore_recycled_media,
)
from app.services.settings_service import get_or_create_settings
from app.services.user_service import get_current_user, require_permission


router = APIRouter(prefix="/api/v1/recycle-bin", tags=["recycle-bin"])


def _roots(db: Session):
    return configured_library_roots(get_or_create_settings(db))


@router.get("", summary="Содержимое корзины медиатеки")
def list_recycle_bin(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return [entry.__dict__ for entry in list_recycled_media(_roots(db))]


@router.get("/{entry_id}", summary="Элемент корзины медиатеки")
def get_recycle_bin_entry(
    entry_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return find_recycled_media(entry_id, _roots(db)).__dict__
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/{entry_id}/restore", summary="Восстановить элемент корзины")
def restore_recycle_bin_entry(
    entry_id: str,
    overwrite: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_library")),
):
    try:
        restored = restore_recycled_media(
            entry_id,
            library_roots=_roots(db),
            overwrite=overwrite,
        )
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except FileExistsError as exc:
        raise HTTPException(409, str(exc)) from exc
    log_audit(
        db,
        action="recycle_bin.restore",
        description=f"Восстановлен элемент корзины: {restored}",
        username=current_user.username,
    )
    db.commit()
    return {"success": True, "path": str(restored)}


@router.delete("/{entry_id}", status_code=204, summary="Удалить элемент корзины безвозвратно")
def delete_recycle_bin_entry(
    entry_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_library")),
):
    try:
        entry = find_recycled_media(entry_id, _roots(db))
        purge_recycled_media(entry_id, library_roots=_roots(db))
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    log_audit(
        db,
        action="recycle_bin.purge",
        description=f"Безвозвратно удалён элемент корзины: {entry.original_path}",
        username=current_user.username,
    )
    db.commit()


@router.post("/cleanup", summary="Очистить просроченные элементы корзины")
def cleanup_recycle_bin(
    retention_days: int = Query(30, ge=0, le=3650),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_library")),
):
    removed = purge_expired_recycled_media(
        library_roots=_roots(db),
        retention_days=retention_days,
    )
    if removed:
        log_audit(
            db,
            action="recycle_bin.cleanup",
            description=f"Очищено элементов корзины: {len(removed)}",
            username=current_user.username,
        )
        db.commit()
    return {"success": True, "removed": len(removed), "entry_ids": removed}
