"""Теги и профили задержки автоматического захвата."""

from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.db import DelayProfile, Indexer, Show, Tag, User
from app.services.user_service import get_current_user, require_any_permission


router = APIRouter(prefix="/api/v1", tags=["release_policies"])


class TagPayload(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class TagOut(BaseModel):
    id: int
    name: str
    show_ids: list[int] = Field(default_factory=list)
    indexer_ids: list[int] = Field(default_factory=list)


class DelayProfilePayload(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    tag_id: Optional[int] = None
    preferred_protocol: Literal["torrent", "usenet", "either"] = "torrent"
    usenet_delay_minutes: int = Field(default=0, ge=0, le=525600)
    torrent_delay_minutes: int = Field(default=0, ge=0, le=525600)
    bypass_if_highest_quality: bool = False
    bypass_custom_format_score: Optional[int] = None
    enabled: bool = True


class DelayProfileOut(DelayProfilePayload):
    model_config = ConfigDict(from_attributes=True)

    id: int


def _tag_out(tag: Tag) -> TagOut:
    return TagOut(
        id=tag.id,
        name=tag.name,
        show_ids=sorted(show.id for show in tag.shows),
        indexer_ids=sorted(indexer.id for indexer in tag.indexers),
    )


def _clean_tag_name(name: str) -> str:
    clean = name.strip()
    if not clean:
        raise HTTPException(422, "Название метки не может быть пустым")
    return clean


def _clean_profile_name(name: str) -> str:
    clean = name.strip()
    if not clean:
        raise HTTPException(422, "Название профиля не может быть пустым")
    return clean


def _validate_profile_scope(db: Session, tag_id: Optional[int], *, exclude_id: Optional[int] = None) -> None:
    if tag_id is not None and db.get(Tag, tag_id) is None:
        raise HTTPException(404, "Tag not found")
    query = db.query(DelayProfile).filter(
        DelayProfile.tag_id == tag_id if tag_id is not None else DelayProfile.tag_id.is_(None),
    )
    if exclude_id is not None:
        query = query.filter(DelayProfile.id != exclude_id)
    if query.first():
        scope = f"метки {tag_id}" if tag_id is not None else "без метки"
        raise HTTPException(409, f"Профиль задержки для области {scope} уже существует")


@router.get("/tags", response_model=list[TagOut])
def list_tags(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return [_tag_out(tag) for tag in db.query(Tag).order_by(func.lower(Tag.name), Tag.id).all()]


@router.post("/tags", response_model=TagOut, status_code=201)
def create_tag(
    payload: TagPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_permission("manage_library", "manage_indexers", "manage_settings")),
):
    name = _clean_tag_name(payload.name)
    duplicate = db.query(Tag).filter(func.lower(Tag.name) == name.lower()).first()
    if duplicate:
        raise HTTPException(409, "Метка с таким названием уже существует")
    tag = Tag(name=name)
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return _tag_out(tag)


@router.put("/tags/{tag_id}", response_model=TagOut)
def update_tag(
    tag_id: int,
    payload: TagPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_permission("manage_library", "manage_indexers", "manage_settings")),
):
    tag = db.get(Tag, tag_id)
    if not tag:
        raise HTTPException(404, "Tag not found")
    name = _clean_tag_name(payload.name)
    duplicate = db.query(Tag).filter(func.lower(Tag.name) == name.lower(), Tag.id != tag_id).first()
    if duplicate:
        raise HTTPException(409, "Метка с таким названием уже существует")
    tag.name = name
    db.commit()
    db.refresh(tag)
    return _tag_out(tag)


@router.delete("/tags/{tag_id}", status_code=204)
def delete_tag(
    tag_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_permission("manage_library", "manage_indexers", "manage_settings")),
):
    tag = db.get(Tag, tag_id)
    if not tag:
        raise HTTPException(404, "Tag not found")
    db.delete(tag)
    db.commit()
    return Response(status_code=204)


@router.post("/tags/{tag_id}/shows/{show_id}", response_model=TagOut)
def assign_tag_to_show(
    tag_id: int,
    show_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_permission("manage_library", "manage_settings")),
):
    tag = db.get(Tag, tag_id)
    show = db.get(Show, show_id)
    if not tag or not show:
        raise HTTPException(404, "Tag or show not found")
    if show not in tag.shows:
        tag.shows.append(show)
        db.commit()
    db.refresh(tag)
    return _tag_out(tag)


@router.delete("/tags/{tag_id}/shows/{show_id}", response_model=TagOut)
def unassign_tag_from_show(
    tag_id: int,
    show_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_permission("manage_library", "manage_settings")),
):
    tag = db.get(Tag, tag_id)
    show = db.get(Show, show_id)
    if not tag or not show:
        raise HTTPException(404, "Tag or show not found")
    if show in tag.shows:
        tag.shows.remove(show)
        db.commit()
    db.refresh(tag)
    return _tag_out(tag)


@router.post("/tags/{tag_id}/indexers/{indexer_id}", response_model=TagOut)
def assign_tag_to_indexer(
    tag_id: int,
    indexer_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_permission("manage_indexers", "manage_settings")),
):
    tag = db.get(Tag, tag_id)
    indexer = db.get(Indexer, indexer_id)
    if not tag or not indexer:
        raise HTTPException(404, "Tag or indexer not found")
    if indexer not in tag.indexers:
        tag.indexers.append(indexer)
        db.commit()
    db.refresh(tag)
    return _tag_out(tag)


@router.delete("/tags/{tag_id}/indexers/{indexer_id}", response_model=TagOut)
def unassign_tag_from_indexer(
    tag_id: int,
    indexer_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_permission("manage_indexers", "manage_settings")),
):
    tag = db.get(Tag, tag_id)
    indexer = db.get(Indexer, indexer_id)
    if not tag or not indexer:
        raise HTTPException(404, "Tag or indexer not found")
    if indexer in tag.indexers:
        tag.indexers.remove(indexer)
        db.commit()
    db.refresh(tag)
    return _tag_out(tag)


@router.get("/delay-profiles", response_model=list[DelayProfileOut])
def list_delay_profiles(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return db.query(DelayProfile).order_by(DelayProfile.id).all()


@router.post("/delay-profiles", response_model=DelayProfileOut, status_code=201)
def create_delay_profile(
    payload: DelayProfilePayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_permission("manage_quality_profiles", "manage_settings")),
):
    _validate_profile_scope(db, payload.tag_id)
    profile = DelayProfile(**payload.model_dump())
    profile.name = _clean_profile_name(profile.name)
    db.add(profile)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Профиль задержки для этой метки уже существует") from exc
    db.refresh(profile)
    return profile


@router.put("/delay-profiles/{profile_id}", response_model=DelayProfileOut)
def update_delay_profile(
    profile_id: int,
    payload: DelayProfilePayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_permission("manage_quality_profiles", "manage_settings")),
):
    profile = db.get(DelayProfile, profile_id)
    if not profile:
        raise HTTPException(404, "Delay profile not found")
    _validate_profile_scope(db, payload.tag_id, exclude_id=profile_id)
    for field, value in payload.model_dump().items():
        setattr(profile, field, _clean_profile_name(value) if field == "name" else value)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Профиль задержки для этой метки уже существует") from exc
    db.refresh(profile)
    return profile


@router.delete("/delay-profiles/{profile_id}", status_code=204)
def delete_delay_profile(
    profile_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_permission("manage_quality_profiles", "manage_settings")),
):
    profile = db.get(DelayProfile, profile_id)
    if not profile:
        raise HTTPException(404, "Delay profile not found")
    db.delete(profile)
    db.commit()
    return Response(status_code=204)
