from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.db import ImportList, User
from app.services.import_list_runtime import run_import_list
from app.services.task_manager import task_manager
from app.services.user_service import get_current_user, require_permission


router = APIRouter(prefix="/api/v1/import-lists", tags=["import-lists"])


class ImportListPayload(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    source: Literal["tmdb_list", "tmdb_person", "trakt_list"]
    source_id: str = Field(min_length=1, max_length=500)
    api_key: Optional[str] = None
    username: Optional[str] = None
    access_token: Optional[str] = None
    enabled: bool = True
    interval_minutes: int = Field(default=360, ge=1, le=525600)
    include_movies: bool = True
    include_series: bool = True
    include_crew: bool = False
    language: Optional[str] = None
    monitored: bool = True
    search_on_add: bool = False
    quality_profile_id: Optional[int] = None
    root_folder: Optional[str] = None
    tag_ids: list[int] = Field(default_factory=list)


class ImportListOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    source: str
    source_id: str
    username: Optional[str] = None
    enabled: bool
    interval_minutes: int
    include_movies: bool
    include_series: bool
    include_crew: bool
    language: Optional[str] = None
    monitored: bool
    search_on_add: bool
    quality_profile_id: Optional[int] = None
    root_folder: Optional[str] = None
    tag_ids: list[int]
    last_synced_at: Optional[str] = None
    last_error: Optional[str] = None
    last_result: Optional[dict] = None
    has_api_key: bool = False
    has_access_token: bool = False


def _out(row: ImportList) -> dict:
    return {
        **{field: getattr(row, field) for field in ImportListOut.model_fields if hasattr(row, field)},
        "last_synced_at": row.last_synced_at.isoformat() if row.last_synced_at else None,
        "has_api_key": bool(row.api_key),
        "has_access_token": bool(row.access_token),
    }


def _apply(row: ImportList, payload: ImportListPayload, *, preserve_secrets: bool) -> None:
    values = payload.model_dump()
    values["name"] = values["name"].strip()
    values["source_id"] = values["source_id"].strip()
    if values["source"] == "trakt_list" and not (values.get("username") or "").strip():
        raise HTTPException(422, "Для списка Trakt требуется username")
    for field, value in values.items():
        if preserve_secrets and field in {"api_key", "access_token"} and value is None:
            continue
        setattr(row, field, value)


@router.get("", response_model=list[ImportListOut], summary="Списки автоматического импорта")
def list_import_lists(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return [_out(row) for row in db.query(ImportList).order_by(ImportList.id).all()]


@router.post("", response_model=ImportListOut, status_code=201, summary="Добавить список импорта")
def create_import_list(
    payload: ImportListPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_library")),
):
    row = ImportList()
    _apply(row, payload, preserve_secrets=False)
    db.add(row)
    db.commit()
    db.refresh(row)
    return _out(row)


@router.put("/{list_id}", response_model=ImportListOut, summary="Обновить список импорта")
def update_import_list(
    list_id: int,
    payload: ImportListPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_library")),
):
    row = db.get(ImportList, list_id)
    if row is None:
        raise HTTPException(404, "Import list not found")
    _apply(row, payload, preserve_secrets=True)
    db.commit()
    db.refresh(row)
    return _out(row)


@router.delete("/{list_id}", status_code=204, summary="Удалить список импорта")
def delete_import_list(
    list_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_library")),
):
    row = db.get(ImportList, list_id)
    if row is None:
        raise HTTPException(404, "Import list not found")
    db.delete(row)
    db.commit()
    return Response(status_code=204)


@router.post("/{list_id}/preview", summary="Предпросмотр списка импорта")
async def preview_import_list(
    list_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_library")),
):
    row = db.get(ImportList, list_id)
    if row is None:
        raise HTTPException(404, "Import list not found")
    return await run_import_list(db, row, dry_run=True)


@router.post("/{list_id}/sync", summary="Синхронизировать список импорта")
def sync_import_list(
    list_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_library")),
):
    row = db.get(ImportList, list_id)
    if row is None:
        raise HTTPException(404, "Import list not found")
    task = task_manager.enqueue(
        "import_list_sync",
        f"Синхронизация списка «{row.name}»",
        {"list_id": row.id},
        active_key=f"import_list:{row.id}",
        max_attempts=3,
        resumable=True,
    )
    return {"success": True, "task_id": task.id, "status": task.status}
