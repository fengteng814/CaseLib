from typing import List, Optional, Dict, Any, Tuple
import json
import logging
import re
from datetime import datetime

from sqlalchemy.orm import Session
from sqlalchemy import or_

import models
import schemas
from favorites_models import Collection, CollectionItem  # ★ 新增：收藏夹模型

# MEDIA_ROOT 用于文件系统路径；MEDIA_ROOT_RAW 用于拼 UNC 路径给前端复制
try:
    from config import MEDIA_ROOT, MEDIA_ROOT_RAW
except ImportError:
    # 兼容旧版 config.py 没有 MEDIA_ROOT_RAW 的情况
    from config import MEDIA_ROOT
    MEDIA_ROOT_RAW = str(MEDIA_ROOT)

from indexer import ensure_thumb_for_image
from sorting import apply_project_sort

logger = logging.getLogger(__name__)


def _build_fs_path(folder_path: str) -> str:
    """
    根据 config.ini 中的 media_root 原始字符串 + folder_path
    拼出一个 Windows UNC 路径，供前端复制。

    - MEDIA_ROOT_RAW：例如 "\\\\10.0.96.80\\ALXGNew01\\A04资源\\A04.6 案例库\\A04.6.1 项目案例"
    - folder_path：  例如 "体育建筑/某项目/子项"

    返回：
    "\\\\10.0.96.80\\ALXGNew01\\A04资源\\A04.6 案例库\\A04.6.1 项目案例\\体育建筑\\某项目\\子项"
    """
    base = MEDIA_ROOT_RAW.rstrip("\\/")

    # folder_path 内部统一用 "/"，这里转成 Windows 风格的 "\"
    sub = (folder_path or "").replace("/", "\\").lstrip("\\/")

    if sub:
        return base + "\\" + sub
    else:
        return base


# ========== 全站搜索热词相关 ==========


def _split_query_to_words(raw: str) -> List[str]:
    """
    把原始搜索字符串拆成若干词：
    - 用空格 / 逗号 / 中文逗号等分隔
    - 去掉空串
    - 忽略大小写去重
    """
    if not raw:
        return []

    text = (
        raw.replace("，", " ")
        .replace(",", " ")
        .replace("；", " ")
        .replace(";", " ")
    )
    parts = text.split()
    words: List[str] = []
    seen = set()

    for part in parts:
        w = part.strip()
        if not w:
            continue
        key = w.lower()
        if key in seen:
            continue
        seen.add(key)
        words.append(w)

    return words


def record_search_keywords(db: Session, raw_query: str) -> None:
    """
    将一次搜索的关键词记录到全站热词表中。
    - 由 /api/search_keywords 调用
    - 失败时记录日志但不抛异常，避免影响正常请求
    """
    words = _split_query_to_words(raw_query)
    if not words:
        return

    now = datetime.utcnow()

    try:
        for w in words:
            kw = (
                db.query(models.SearchKeyword)
                .filter(models.SearchKeyword.keyword == w)
                .first()
            )
            if kw is None:
                kw = models.SearchKeyword(
                    keyword=w,
                    count=1,
                    last_used_at=now,
                )
                db.add(kw)
            else:
                kw.count = (kw.count or 0) + 1
                kw.last_used_at = now

        db.commit()
    except Exception as e:
        logger.warning("记录搜索热词失败：%s", e)
        db.rollback()


def get_hot_keywords(db: Session, limit: int = 20) -> List[Dict[str, Any]]:
    """
    读取全站热词，按使用次数和最近时间倒序。
    """
    if not limit:
        limit = 20
    limit = max(1, min(int(limit), 100))

    rows = (
        db.query(models.SearchKeyword)
        .order_by(
            models.SearchKeyword.count.desc(),
            models.SearchKeyword.last_used_at.desc(),
        )
        .limit(limit)
        .all()
    )

    result: List[Dict[str, Any]] = []
    for r in rows:
        result.append(
            {
                "keyword": r.keyword,
                "count": r.count or 0,
                "last_used_at": r.last_used_at.isoformat()
                if r.last_used_at
                else None,
            }
        )
    return result

# ========== 项目标签相关 ==========


def _split_tags_text(raw: Optional[str]) -> List[str]:
    """
    把用户输入的标签字符串拆成若干标签：
    - 使用空格 / 中英文逗号 / 分号 / 顿号 等分隔
    - 统一转为小写
    - 去重
    """
    if not raw:
        return []

    text = (
        raw.replace("，", " ")
        .replace(",", " ")
        .replace("；", " ")
        .replace(";", " ")
        .replace("、", " ")
    )

    parts = text.split()
    tags: List[str] = []
    seen = set()

    for part in parts:
        tag = part.strip().lower()
        if not tag:
            continue
        if tag in seen:
            continue
        seen.add(tag)
        tags.append(tag)

    return tags


def set_project_tags_from_text(
    db: Session,
    project: models.Project,
    tags_text: Optional[str],
) -> List[str]:
    """
    根据用户输入的 tags_text 更新项目的标签（多对多）：
    - tags_text 为 None：由调用方决定是否调用本函数；
    - tags_text 为空字符串：清空标签；
    - 其它：按分隔规则解析并覆盖原有标签。
    返回最新的标签名称列表（小写）。
    """
    new_names = _split_tags_text(tags_text)

    if not new_names:
        # 清空标签
        project.tags = []
        return []

    # 已存在的 Tag
    existing_tags = (
        db.query(models.Tag)
        .filter(models.Tag.name.in_(new_names))
        .all()
    )
    by_name = {t.name: t for t in existing_tags}

    tags_for_project: List[models.Tag] = []
    for name in new_names:
        tag_obj = by_name.get(name)
        if tag_obj is None:
            tag_obj = models.Tag(name=name)
            db.add(tag_obj)
            by_name[name] = tag_obj
        tags_for_project.append(tag_obj)

    # 覆盖项目的标签集合
    project.tags = tags_for_project
    return [t.name for t in tags_for_project]


# ========== 项目 & 图片相关原有逻辑 ==========

def get_projects(
    db: Session,
    q: Optional[str],
    limit: int,
    offset: int,
    sort: str = "heat",
) -> List[schemas.ProjectOut]:
    """
    项目列表：
    - 支持按名称 / 建筑师模糊搜索
    - 支持多种排序方式（总热度 / 近期热度 / 加入时间 / 名称 / 地点 / 建筑师）
    - 每个项目带：
      · 封面缩略图 URL cover_url（如果有封面的话，形如 /thumbs/...）
      · 复制用文件系统路径 fs_path（UNC）
      · 项目标签 tags（小写字符串列表）
    """
    query = db.query(models.Project)

    if q:
        like = f"%{q}%"
        # 名称 或 建筑师 命中即可
        query = query.filter(
            or_(
                models.Project.name.ilike(like),
                models.Project.architect.ilike(like),
            )
        )

    # === 排序逻辑 ===
    if sort in ("updated", "time", "updated_desc"):
        # 按“加入案例库时间”理解，用 id 代表加入时间
        query = query.order_by(models.Project.id.desc())
    else:
        query = apply_project_sort(query, sort)

    # 分页
    projects = query.offset(offset).limit(limit).all()
    if not projects:
        return []

    result: List[schemas.ProjectOut] = []

    for p in projects:
        # 1) 封面：只要有 cover_rel_path，就交给 /thumbs 路由处理
        if getattr(p, "cover_rel_path", None):
            cover_url: Optional[str] = f"/thumbs/{p.cover_rel_path}"
        else:
            cover_url = None

        # 2) 复制用 UNC 路径
        fs_path = _build_fs_path(p.folder_path)

        # 3) 项目标签（小写字符串列表）
        try:
            tags = [t.name for t in getattr(p, "tags", [])] if p.tags else []
        except Exception:
            tags = []

        # 4) 组装返回模型
        result.append(
            schemas.ProjectOut(
                id=p.id,
                name=p.name,
                folder_path=p.folder_path,
                cover_url=cover_url,
                architect=p.architect,
                description=p.description,
                location=p.location,
                category=p.category,
                year=p.year,
                display_order=p.display_order,
                tags=tags,
                fs_path=fs_path,
            )
        )

    return result


def get_images(
    db: Session,
    q: Optional[str],
    project_id: Optional[int],
    limit: int,
    offset: int,
) -> List[schemas.ImageOut]:
    """
    图片列表：
    - 可按项目过滤
    - 可按文件名 / 标签 / 项目名模糊搜索
    - 同时返回：
      · 原图 URL（/media/...）
      · 缩略图 URL（/thumbs/...）
    """
    query = (
        db.query(
            models.Image,
            models.Project.name.label("project_name"),
        )
        .join(models.Project, models.Image.project_id == models.Project.id)
    )

    if project_id is not None:
        query = query.filter(models.Image.project_id == project_id)

    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                models.Image.file_name.ilike(like),
                models.Image.tags.ilike(like),
                models.Project.name.ilike(like),
            )
        )

    rows = (
        query.order_by(models.Image.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    images: List[schemas.ImageOut] = []
    for img, project_name in rows:
        original_url = f"/media/{img.file_rel_path}"
        thumb_url = f"/thumbs/{img.file_rel_path}"

        images.append(
            schemas.ImageOut(
                id=img.id,
                project_id=img.project_id,
                project_name=project_name,
                url=original_url,
                thumb_url=thumb_url,
            )
        )

    return images


def get_project_by_id(db: Session, project_id: int) -> Optional[models.Project]:
    """按 id 获取单个项目"""
    return db.query(models.Project).filter(models.Project.id == project_id).first()


def increment_project_heat(
    db: Session,
    project_id: int,
) -> Optional[models.Project]:
    """
    将指定项目的热度 +1 并保存，同时写入一条点击记录，返回最新的 Project。
    """
    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if project is None:
        return None

    # 总热度 +1
    project.heat = (project.heat or 0) + 1
    db.add(project)

    # 记录一条点击日志（用于“近期热度”统计）
    click = models.ProjectClick(
        project_id=project.id,
        clicked_at=datetime.utcnow(),
    )
    db.add(click)

    db.commit()
    db.refresh(project)
    return project


def update_project(
    db: Session,
    project: models.Project,
    update: schemas.ProjectUpdate,
) -> models.Project:
    """
    更新单个项目的 meta 字段，并标记 is_meta_locked = True，
    然后写回对应的 project.json。
    """
    data = update.dict(exclude_unset=True)

    for attr in [
        "name",
        "architect",
        "description",
        "location",
        "category",
        "year",
        "display_order",
    ]:
        if attr in data:
            setattr(project, attr, data[attr])
    # 处理标签（如果有传 tags_text）

    if "tags_text" in data:
        # 空字符串会在 set_project_tags_from_text 内转成“清空标签”
        set_project_tags_from_text(db, project, data["tags_text"])

    # 标记为手动编辑，索引器不再覆盖 meta / 封面
    project.is_meta_locked = True

    db.add(project)
    db.commit()
    db.refresh(project)

    # 同步写回 project.json（失败只打日志，不回滚 DB）
    try:
        save_project_meta_to_json(db, project)
    except Exception as e:
        logger.warning(
            "写入 project.json 失败 (project_id=%s): %s",
            project.id,
            e,
        )

    return project


def set_project_cover(
    db: Session,
    project_id: int,
    file_rel_path: str,
) -> Optional[models.Project]:
    """
    将某张图片设为指定项目的封面，并锁定 meta（避免被 sync_from_fs 覆盖）。

    约定：
    - file_rel_path 必须是相对 MEDIA_ROOT 的路径；
    - 且这张图片必须属于该项目（Image.project_id == project.id）。
    """
    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if project is None:
        return None

    # 校验该图片是否属于该项目
    image = (
        db.query(models.Image)
        .filter(
            models.Image.project_id == project.id,
            models.Image.file_rel_path == file_rel_path,
        )
        .first()
    )
    if image is None:
        # 找不到对应图片，返回 None 交给上层处理 404 / 400
        return None

    # 更新封面并锁定 meta
    now = datetime.utcnow()
    project.cover_rel_path = file_rel_path
    project.is_meta_locked = True
    project.updated_at = now

    db.add(project)
    db.commit()
    db.refresh(project)

    # 为新封面生成缩略图
    project_dir = (MEDIA_ROOT / project.folder_path).resolve()
    abs_image_path = (MEDIA_ROOT / project.cover_rel_path).resolve()
    try:
        ensure_thumb_for_image(abs_image_path, project_dir)
    except Exception as e:
        logger.warning(
            "生成封面缩略图失败 (project_id=%s, path=%s): %s",
            project.id,
            project.cover_rel_path,
            e,
        )

    return project


def save_project_meta_to_json(db: Session, project: models.Project) -> None:
    """
    将项目的 meta 信息写回对应目录下的 project.json。

    结构（子集）：
    {
        "version": 1,
        "meta": {
            "name": ...,
            "architect": ...,
            "location": ...,
            "category": ...,
            "year": ...,
            "description": ...
        },
        "display": {
            "order": ...
        },
        ...
    }
    """
    project_dir = (MEDIA_ROOT / project.folder_path).resolve()
    if not project_dir.exists() or not project_dir.is_dir():
        return

    meta_path = project_dir / "project.json"

    data: Dict[str, Any] = {}

    if meta_path.is_file():
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                data = loaded
        except Exception as e:
            logger.warning(
                "读取 project.json 失败 (project_id=%s): %s",
                project.id,
                e,
            )

    # 版本号
    data["version"] = 1

    # --- meta ---
    meta_section = data.get("meta")
    if not isinstance(meta_section, dict):
        meta_section = {}

    # 项目标签列表（小写）
    try:
        tags = [t.name for t in getattr(project, "tags", [])] if project.tags else []
    except Exception:
        tags = []

    meta_section.update(
        {
            "name": project.name,
            "architect": project.architect or "",
            "location": project.location or "",
            "category": project.category or "",
            "year": project.year,
            "description": project.description or "",
            "tags": tags,
        }
    )

    data["meta"] = meta_section

    # --- display ---
    display_section = data.get("display")
    if not isinstance(display_section, dict):
        display_section = {}

    display_section["order"] = project.display_order
    data["display"] = display_section

    # 原子写入：先写临时文件，再覆盖
    tmp_path = meta_path.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp_path.replace(meta_path)


# ========== 新增：合并项目 ==========

def merge_projects(
    db: Session,
    target: models.Project,
    sources: List[models.Project],
) -> Tuple[models.Project, List[int]]:
    """
    合并多个项目到一个目标项目（仅数据库层面，不移动文件系统目录）：

    - 源项目的图片（Image）全部改为指向目标项目；
    - 源项目的点击记录（ProjectClick）全部改为指向目标项目；
    - 收藏夹条目（CollectionItem）中涉及源项目的，改为指向目标项目；
      如同一收藏夹中已包含目标项目，则删除重复项；
    - 标签（Tag）做并集合并到目标项目；
    - 全站热度 heat 相加；
    - 如果目标项目尚无封面，则尝试使用源项目的封面；
    - 最后删除源项目记录。
    """
    if not sources:
        return target, []

    removed_ids = [p.id for p in sources]
    source_ids = [p.id for p in sources]

    # 合并图片
    for src in sources:
        for img in list(src.images):
            img.project = target

    # 合并点击记录
    for src in sources:
        for click in list(src.clicks):
            click.project = target

    # 合并标签（做并集）
    existing_tag_ids = {t.id for t in target.tags} if target.tags else set()
    for src in sources:
        for tag in src.tags:
            if tag.id not in existing_tag_ids:
                target.tags.append(tag)
                existing_tag_ids.add(tag.id)

    # 合并热度
    total_heat = (target.heat or 0) + sum((s.heat or 0) for s in sources)
    target.heat = total_heat

    # 如果目标还没有封面，则尝试用源项目封面
    if not target.cover_rel_path:
        for src in sources:
            if src.cover_rel_path:
                target.cover_rel_path = src.cover_rel_path
                break

    # 收藏夹条目 & 收藏夹封面
    try:
        # 所有涉及源项目的条目
        items = (
            db.query(CollectionItem)
            .filter(CollectionItem.project_id.in_(source_ids))
            .all()
        )
        for item in items:
            # 如果当前收藏夹里已经有目标项目，则删除重复条目
            exists = (
                db.query(CollectionItem)
                .filter(
                    CollectionItem.collection_id == item.collection_id,
                    CollectionItem.project_id == target.id,
                )
                .first()
            )
            if exists:
                db.delete(item)
            else:
                item.project_id = target.id

        # 收藏夹封面：如果封面项目是源项目，则改成目标项目
        collections_to_update = (
            db.query(Collection)
            .filter(Collection.cover_project_id.in_(source_ids))
            .all()
        )
        for c in collections_to_update:
            c.cover_project_id = target.id
    except Exception as e:
        logger.warning("合并项目时更新收藏夹信息失败：%s", e)

    # 删除源项目
    for src in sources:
        db.delete(src)

    # 标记为手动编辑 & 更新时间
    target.is_meta_locked = True
    target.updated_at = datetime.utcnow()

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    db.refresh(target)

    # 更新一次 project.json（只针对目标项目）
    try:
        save_project_meta_to_json(db, target)
    except Exception as e:
        logger.warning(
            "合并项目后写入 project.json 失败 (project_id=%s): %s",
            target.id,
            e,
        )

    return target, removed_ids
