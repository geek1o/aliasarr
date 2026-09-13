import os
import io
import shutil
import base64
import logging
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


def get_media_cover_dir() -> str:
    """
    Возвращает базовую директорию для хранения обложек MediaCover.
    В Docker-окружении: /config/MediaCover
    В локальном окружении: ./config/MediaCover
    """
    env_dir = os.getenv("ALIASARR_MEDIA_COVER_DIR") or os.getenv("MEDIA_COVER_DIR")
    if env_dir:
        return os.path.abspath(env_dir)

    is_docker = os.path.exists("/.dockerenv") or os.getenv("ALIASARR_DOCKER") == "true"
    base_config = "/config" if (is_docker or os.path.exists("/config")) else os.path.abspath("./config")
    return os.path.join(base_config, "MediaCover")


def get_show_poster_dir(show_id: int) -> str:
    return os.path.join(get_media_cover_dir(), "shows", str(show_id))


def get_show_poster_path(show_id: int) -> str:
    return os.path.join(get_show_poster_dir(show_id), "poster.jpg")


def get_collection_poster_dir(collection_id: int) -> str:
    return os.path.join(get_media_cover_dir(), "collections", str(collection_id))


def get_collection_poster_path(collection_id: int) -> str:
    return os.path.join(get_collection_poster_dir(collection_id), "poster.jpg")


def optimize_image(
    image_bytes: bytes,
    max_width: int = 600,
    max_height: int = 900,
    quality: int = 85,
) -> bytes:
    """
    Оптимизирует изображение постера:
    - Масштабирует до стандартного размера (ширина до max_width, высота до max_height);
    - Приводит альфа-канал к нейтральному темному фону (для PNG/WebP с прозрачностью);
    - Сжимает в формате JPEG с progressive=True, optimize=True и качеством quality;
    - При отсутствии Pillow или ошибке декодирования сохраняет исходные байты без сбоя.
    """
    if not image_bytes or not HAS_PIL:
        return image_bytes

    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            # 1. Приведение цветового режима к RGB (удаление альфа-канала)
            if img.mode in ("RGBA", "LA", "P"):
                bg = Image.new("RGB", img.size, (20, 24, 33))  # нейтральный темный фон под стиль интерфейса
                if img.mode == "P":
                    img = img.convert("RGBA")
                mask = img.split()[-1] if len(img.split()) == 4 else None
                bg.paste(img, (0, 0), mask)
                img = bg
            elif img.mode != "RGB":
                img = img.convert("RGB")

            # 2. Пропорциональное масштабирование
            w, h = img.size
            if w > max_width or h > max_height:
                img.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)

            # 3. Сохранение в буфер JPEG
            out_buf = io.BytesIO()
            img.save(out_buf, format="JPEG", quality=quality, optimize=True, progressive=True)
            return out_buf.getvalue()
    except Exception as e:
        logger.debug("Image optimization fallback to raw bytes: %s", e)
        return image_bytes


async def save_show_poster(show_id: int, image_bytes: bytes) -> str:
    """
    Оптимизирует и сохраняет постер тайтла на диск в /config/MediaCover/shows/{show_id}/poster.jpg.
    Возвращает локальный URL эндпоинта /api/v1/shows/{show_id}/poster.
    """
    opt_bytes = optimize_image(image_bytes)
    poster_dir = get_show_poster_dir(show_id)
    os.makedirs(poster_dir, exist_ok=True)
    poster_path = get_show_poster_path(show_id)
    with open(poster_path, "wb") as f:
        f.write(opt_bytes)
    return f"/api/v1/shows/{show_id}/poster"


async def save_collection_poster(collection_id: int, image_bytes: bytes) -> str:
    """
    Оптимизирует и сохраняет постер коллекции на диск в /config/MediaCover/collections/{collection_id}/poster.jpg.
    Возвращает локальный URL эндпоинта /api/v1/collections/{collection_id}/poster.
    """
    opt_bytes = optimize_image(image_bytes)
    poster_dir = get_collection_poster_dir(collection_id)
    os.makedirs(poster_dir, exist_ok=True)
    poster_path = get_collection_poster_path(collection_id)
    with open(poster_path, "wb") as f:
        f.write(opt_bytes)
    return f"/api/v1/collections/{collection_id}/poster"


async def download_and_store_show_cover(show_id: int, remote_url_or_data: str) -> Optional[str]:
    """
    Скачивает постер по внешнему URL (CDN) или декодирует Base64 DataURL,
    сохраняет оптимизированный файл на диск и возвращает локальный URL.
    """
    if not remote_url_or_data or not str(remote_url_or_data).strip():
        return None

    raw_val = str(remote_url_or_data).strip()

    # 1. Если это уже локальный эндпоинт и файл существует на диске
    if raw_val.startswith(f"/api/v1/shows/{show_id}/poster") or raw_val.startswith(f"/api/v1/shows/{show_id}/poster?"):
        if os.path.isfile(get_show_poster_path(show_id)):
            return raw_val

    # 2. Если это DataURL Base64 (ручная загрузка пользователем)
    if raw_val.startswith("data:image/"):
        try:
            _, encoded = raw_val.split(",", 1)
            image_bytes = base64.b64decode(encoded)
            if image_bytes:
                return await save_show_poster(show_id, image_bytes)
        except Exception as e:
            logger.debug("Failed to decode base64 cover for show %s: %s", show_id, e)
        return None

    # 3. Если это внешняя HTTP/HTTPS ссылка на CDN
    if raw_val.startswith(("http://", "https://")):
        try:
            import httpx
            async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers={"User-Agent": "Aliasarr/1.0.0"}) as client:
                resp = await client.get(raw_val)
                if resp.status_code == 200 and resp.content:
                    return await save_show_poster(show_id, resp.content)
                logger.debug("Failed to download cover from %s: HTTP %s", raw_val, resp.status_code)
        except Exception as e:
            logger.debug("Error downloading cover for show %s from %s: %s", show_id, raw_val, e)

    return None


async def download_and_store_collection_cover(collection_id: int, remote_url_or_data: str) -> Optional[str]:
    """
    Скачивает постер коллекции по внешнему URL (TMDb) или декодирует Base64,
    сохраняет файл на диск и возвращает локальный URL.
    """
    if not remote_url_or_data or not str(remote_url_or_data).strip():
        return None

    raw_val = str(remote_url_or_data).strip()

    if raw_val.startswith(f"/api/v1/collections/{collection_id}/poster"):
        if os.path.isfile(get_collection_poster_path(collection_id)):
            return raw_val

    if raw_val.startswith("data:image/"):
        try:
            _, encoded = raw_val.split(",", 1)
            image_bytes = base64.b64decode(encoded)
            if image_bytes:
                return await save_collection_poster(collection_id, image_bytes)
        except Exception as e:
            logger.debug("Failed to decode base64 cover for collection %s: %s", collection_id, e)
        return None

    if raw_val.startswith(("http://", "https://")):
        try:
            import httpx
            async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers={"User-Agent": "Aliasarr/1.0.0"}) as client:
                resp = await client.get(raw_val)
                if resp.status_code == 200 and resp.content:
                    return await save_collection_poster(collection_id, resp.content)
        except Exception as e:
            logger.debug("Error downloading cover for collection %s from %s: %s", collection_id, raw_val, e)

    return None


def delete_show_cover(show_id: int) -> bool:
    """Удаляет директорию с локальными обложками тайтла при удалении карточки."""
    poster_dir = get_show_poster_dir(show_id)
    if os.path.exists(poster_dir):
        try:
            shutil.rmtree(poster_dir, ignore_errors=True)
            return True
        except Exception as e:
            logger.debug("Failed to delete cover dir for show %s: %s", show_id, e)
    return False


def delete_collection_cover(collection_id: int) -> bool:
    """Удаляет директорию с локальными обложками коллекции при удалении."""
    poster_dir = get_collection_poster_dir(collection_id)
    if os.path.exists(poster_dir):
        try:
            shutil.rmtree(poster_dir, ignore_errors=True)
            return True
        except Exception as e:
            logger.debug("Failed to delete cover dir for collection %s: %s", collection_id, e)
    return False


def get_cover_etag(file_path: str) -> Optional[str]:
    """Генерирует ETag для заголовков HTTP-кэширования."""
    if os.path.isfile(file_path):
        try:
            st = os.stat(file_path)
            return f'"{int(st.st_mtime)}-{st.st_size}"'
        except Exception:
            return None
    return None


async def backfill_existing_covers(db) -> dict:
    """
    Фоновая миграция существующих тайтлов:
    - Находит тайтлы, у которых poster_url начинается с http или data:image;
    - Скачивает/декодирует их и сохраняет в /config/MediaCover/shows/{id}/poster.jpg;
    - Сохраняет оригинальную ссылку в poster_source_url и переключает poster_url на локальный эндпоинт.
    """
    from app.models.db import Show
    try:
        shows = db.query(Show).all()
    except Exception as e:
        logger.debug("backfill_existing_covers query failed: %s", e)
        return {"total": 0, "migrated": 0}

    migrated = 0
    for show in shows:
        target_path = get_show_poster_path(show.id)
        needs_migration = False
        url = show.poster_url or getattr(show, "poster_source_url", None)
        if not url:
            continue
        raw_url = str(url).strip()
        if raw_url.startswith(("http://", "https://", "data:image/")):
            needs_migration = True
        elif not os.path.isfile(target_path) and getattr(show, "poster_source_url", None):
            needs_migration = True
            raw_url = str(show.poster_source_url).strip()

        if needs_migration and raw_url:
            if raw_url.startswith(("http://", "https://")):
                show.poster_source_url = raw_url
            res = await download_and_store_show_cover(show.id, raw_url)
            if res:
                show.poster_url = res
                migrated += 1

    if migrated:
        try:
            db.commit()
        except Exception as e:
            logger.debug("backfill_existing_covers commit error: %s", e)

    return {"total": len(shows), "migrated": migrated}
