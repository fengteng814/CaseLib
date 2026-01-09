from pathlib import Path
from typing import List, Optional
import json
import logging
import shutil
from urllib.parse import urlparse

from fastapi import FastAPI, Depends, HTTPException, Query, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from favorites_api import router as collections_router
import favorites_models  # ✅ 新增：让 SQLAlchemy 知道有这两张表
from pydantic import BaseModel

from database import SessionLocal, engine
import models
import schemas
import crud
from indexer import sync_from_fs, ensure_thumb_for_image
from config import (
    MEDIA_ROOT,
    FRONTEND_DIR,
    FRONTEND_INDEX,
    INITIAL_PROJECT_LIMIT,
    PROJECT_PAGE_SIZE,
    HOT_TAG_LIMIT,
    FIXED_HOT_TAGS,
)

from web_import import router as web_import_router  # “从网站导入”相关路由
import requests

logger = logging.getLogger(__name__)

# ========== 数据库初始化 ==========
models.Base.metadata.create_all(bind=engine)

# ========== FastAPI 应用 ==========
app = FastAPI(title="CaseLib Backend")

# CORS（方便以后前后端拆开部署）
app.add_middleware(
  CORSMiddleware,
  allow_origins=["*"],  # 本地开发简单起见先放开
  allow_credentials=True,
  allow_methods=["*"],
  allow_headers=["*"],
)

# 挂载“从网站导入”相关 API
app.include_router(web_import_router)
app.include_router(collections_router)


@app.get("/web-import", include_in_schema=False)
def read_web_import():
    html_path = FRONTEND_DIR / "web-import.html"
    if not html_path.exists():
        raise HTTPException(status_code=500, detail="web-import.html not found")
    return FileResponse(str(html_path), media_type="text/html")


# ========== 依赖：数据库 Session ==========
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ========== 启动时自动同步一次 ==========
@app.on_event("startup")
def on_startup():
    """
    服务启动时执行一次全量 sync_from_fs。
    之后不再在每个请求里自动同步。
    """
    db = SessionLocal()
    try:
        sync_from_fs(db)
    finally:
        db.close()


# ========== 挂载静态资源 ==========
# 1) 媒体文件（原图）：/media/...
app.mount("/media", StaticFiles(directory=str(MEDIA_ROOT)), name="media")

# 2) 前端静态资源（css / js / 额外 html）：/static/...
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


# ========== 前端入口 ==========
@app.get("/", include_in_schema=False)
def read_root():
    """
    返回前端页面：frontend/index.html
    """
    if not FRONTEND_INDEX.exists():
        # 如果文件不存在，抛个错误方便排查
        raise HTTPException(status_code=500, detail="frontend/index.html not found")
    return FileResponse(str(FRONTEND_INDEX), media_type="text/html")


# ========== 工具：根据后缀猜测 mime ==========
def _guess_mime(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".png":
        return "image/png"
    if suffix == ".gif":
        return "image/gif"
    if suffix == ".webp":
        return "image/webp"
    if suffix in {".tif", ".tiff"}:
        return "image/tiff"
    return "application/octet-stream"


# ========== 缩略图路由：/thumbs/{path} ==========
@app.get("/thumbs/{path:path}")
def get_thumbnail(
    path: str,
    db: Session = Depends(get_db),
):
    """
    缩略图获取：
    - path 为 Image.file_rel_path（相对 MEDIA_ROOT）
    - 内部会：
      1）从 DB 找到对应 Image + Project
      2）按项目目录生成/读取 _thumbs 下的缩略图
      3）如果缩略图失败，则回退到原图
    """
    # 找到这张图
    image = (
        db.query(models.Image)
        .filter(models.Image.file_rel_path == path)
        .first()
    )
    if image is None:
        raise HTTPException(status_code=404, detail="Image not found")

    project = image.project
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found for image")

    project_dir = (MEDIA_ROOT / project.folder_path).resolve()
    abs_image_path = (MEDIA_ROOT / image.file_rel_path).resolve()

    # 尝试生成/获取缩略图
    thumb_path = ensure_thumb_for_image(abs_image_path, project_dir)

    # 优先返回缩略图，失败则回退原图
    target_path: Optional[Path] = None
    if thumb_path is not None and thumb_path.is_file():
        target_path = thumb_path
    elif abs_image_path.is_file():
        target_path = abs_image_path

    if target_path is None:
        raise HTTPException(status_code=404, detail="Image file not found on disk")

    return FileResponse(
        str(target_path),
        media_type=_guess_mime(target_path),
    )


# ========== 工具：项目目录 & 保存图片到项目 ==========
def _get_project_dir(project: models.Project) -> Path:
    """
    根据 Project.folder_path 计算项目在磁盘上的目录（位于 MEDIA_ROOT 下）。
    """
    project_dir = (MEDIA_ROOT / project.folder_path).resolve()
    try:
        # 简单防御：不允许跑到 MEDIA_ROOT 之外
        project_dir.relative_to(MEDIA_ROOT.resolve())
    except ValueError:
        raise HTTPException(status_code=500, detail="Invalid project folder path")
    return project_dir


def _make_unique_filename(folder: Path, filename: str) -> Path:
    """
    在给定目录下生成不重名的文件名。
    """
    filename = Path(filename).name or "image"
    if "." not in filename:
        filename = filename + ".jpg"
    dest = folder / filename
    stem = dest.stem
    suffix = dest.suffix
    i = 1
    while dest.exists():
        dest = folder / f"{stem}_{i}{suffix}"
        i += 1
    return dest


def _save_upload_file_to_project(project: models.Project, file: UploadFile) -> str:
    """
    把前端上传的图片文件保存到项目目录下，并生成缩略图。
    返回值为 file_rel_path（相对 MEDIA_ROOT）。
    """
    project_dir = _get_project_dir(project)
    project_dir.mkdir(parents=True, exist_ok=True)

    dest = _make_unique_filename(project_dir, file.filename or "image.jpg")

    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    # 生成缩略图（失败不抛错）
    try:
        ensure_thumb_for_image(dest, project_dir)
    except Exception:
        logger.exception("生成缩略图失败（拖拽上传）: %s", dest)

    rel_path = dest.relative_to(MEDIA_ROOT.resolve())
    return str(rel_path).replace("\\", "/")


def _download_image_to_project(project: models.Project, url: str) -> Optional[str]:
    """
    从远程 URL 下载图片到项目目录。
    返回值为 file_rel_path（相对 MEDIA_ROOT），失败返回 None。
    """
    url = (url or "").strip()
    if not url:
        return None

    project_dir = _get_project_dir(project)
    project_dir.mkdir(parents=True, exist_ok=True)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0 Safari/537.36"
        )
    }

    # 针对微信公众号 / mmbiz 之类的域名补一个 Referer，提升成功率
    try:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        if "weixin.qq.com" in host or "wechat" in host or "mmbiz" in host or "qpic.cn" in host:
            headers["Referer"] = "https://mp.weixin.qq.com/"
    except Exception:
        pass

    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code != 200:
            logger.warning("下载图片失败 %s: status=%s", url, resp.status_code)
            return None

        # 从 URL 推断文件名
        name_part = url.split("?", 1)[0]
        name = Path(name_part).name or "image"
        if "." not in name:
            name = name + ".jpg"

        dest = _make_unique_filename(project_dir, name)

        with dest.open("wb") as f:
            f.write(resp.content)

        # 生成缩略图（失败不抛错）
        try:
            ensure_thumb_for_image(dest, project_dir)
        except Exception:
            logger.exception("生成缩略图失败（下载图片）: %s", dest)

        rel_path = dest.relative_to(MEDIA_ROOT.resolve())
        return str(rel_path).replace("\\", "/")
    except Exception as e:
        logger.exception("下载图片异常 %s: %s", url, e)
        return None


# ========== API：拖拽到项目卡片上传图片 ==========
@app.post("/api/projects/{project_id}/images/drop-upload")
async def drop_upload_images_to_project(
    project_id: int,
    db: Session = Depends(get_db),
    files: Optional[List[UploadFile]] = File(None),
    urls: Optional[str] = Form(None),
):
    """
    支持两种来源：
    1) 本地图片文件（从资源管理器拖拽过来），通过 files 上传；
    2) 浏览器/微信网页里的图片（拖拽时前端拿到的是图片 URL），通过 urls(JSON 数组) 上传，
       由后端负责下载。
    """
    project = crud.get_project_by_id(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    saved_rel_paths: List[str] = []

    # 1) 本地文件
    for f in files or []:
        try:
            # 只接受图片类型；有些浏览器可能不带 content_type，宽松一点按扩展名兜底
            is_image_type = f.content_type and f.content_type.startswith("image/")
            has_image_ext = Path(f.filename or "").suffix.lower() in {
                ".jpg", ".jpeg", ".png", ".gif", ".webp", ".tif", ".tiff"
            }
            if not is_image_type and not has_image_ext:
                continue
            rel_path = _save_upload_file_to_project(project, f)
            saved_rel_paths.append(rel_path)
        except Exception:
            logger.exception("保存上传图片失败（项目 %s）", project_id)

    # 2) 远程图片 URL
    if urls:
        try:
            url_list = json.loads(urls)
            if not isinstance(url_list, list):
                url_list = []
        except Exception:
            logger.warning("解析 urls 字段失败: %s", urls)
            url_list = []

        for u in url_list:
            if not isinstance(u, str):
                continue
            rel_path = _download_image_to_project(project, u)
            if rel_path:
                saved_rel_paths.append(rel_path)

    if not saved_rel_paths:
        # 没任何图片成功
        return {
            "ok": False,
            "count": 0,
            "files": [],
            "message": "没有成功保存的图片（可能拖入的不是图片，或下载失败）",
        }

    # 不修改封面 / 不立即更新 Image 表，只是纯粹写入磁盘并生成缩略图
    return {
        "ok": True,
        "count": len(saved_rel_paths),
        "files": saved_rel_paths,
    }


# ========== API：项目列表 ==========
@app.get("/api/projects", response_model=List[schemas.ProjectOut])
def list_projects(
    q: Optional[str] = Query(None, description="搜索关键词（按名称 / 建筑师）"),
    sort: Optional[str] = Query(
        "heat",
        description="排序方式：heat / recent / updated / name / location / architect",
    ),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    # 不再每次请求都 sync，只用 DB 中已有索引
    projects = crud.get_projects(
        db,
        q=q,
        limit=limit,
        offset=offset,
        sort=sort or "heat",
    )
    return projects


# ========== API：前端配置（分页 / 标签等） ==========
@app.get("/api/frontend-config")
def get_frontend_config():
    """
    提供给前端用的分页等配置参数，来源于 config.ini 的 [frontend]。
    """
    return {
        "project_initial_limit": INITIAL_PROJECT_LIMIT,
        "project_page_size": PROJECT_PAGE_SIZE,
        "hot_tag_limit": HOT_TAG_LIMIT,
        "fixed_hot_tags": FIXED_HOT_TAGS,  # ← 固定标签数组
    }


# ========== API：全站热词 ==========
class SearchKeywordIn(BaseModel):
    query: str


@app.post("/api/search_keywords")
def record_search_keyword_api(
    payload: SearchKeywordIn,
    db: Session = Depends(get_db),
):
    """
    记录一次搜索关键词（只做热词统计，不影响搜索结果）。
    前端在用户点击“搜索”按钮 / 点击热词标签时调用。
    """
    crud.record_search_keywords(db, payload.query or "")
    return {"status": "ok"}


@app.get("/api/hot_keywords")
def list_hot_keywords(
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """
    返回全站热词列表，按出现次数 + 最近时间排序。
    """
    return crud.get_hot_keywords(db, limit=limit)


# ========== API：更新单个项目（meta） ==========
@app.put("/api/projects/{project_id}", response_model=schemas.ProjectOut)
def update_project(
    project_id: int,
    payload: schemas.ProjectUpdate,
    db: Session = Depends(get_db),
):
    project = crud.get_project_by_id(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    updated = crud.update_project(db, project, payload)

    # 计算 cover_url（和列表逻辑保持一致：优先使用 cover_rel_path + /thumbs）
    cover_url: Optional[str] = None
    if getattr(updated, "cover_rel_path", None):
        project_dir = (MEDIA_ROOT / updated.folder_path).resolve()
        abs_image_path = (MEDIA_ROOT / updated.cover_rel_path).resolve()
        try:
            ensure_thumb_for_image(abs_image_path, project_dir)
        except Exception:
            # 失败不影响 API 返回
            pass
        cover_url = f"/thumbs/{updated.cover_rel_path}"

    # 复制用 UNC 路径
    fs_path = crud._build_fs_path(updated.folder_path)

    # 项目标签（小写字符串列表）
    try:
        tags = [t.name for t in getattr(updated, "tags", [])] if updated.tags else []
    except Exception:
        tags = []

    return schemas.ProjectOut(
        id=updated.id,
        name=updated.name,
        folder_path=updated.folder_path,
        cover_url=cover_url,
        architect=updated.architect,
        description=updated.description,
        location=updated.location,
        category=updated.category,
        year=updated.year,
        display_order=updated.display_order,
        tags=tags,
        fs_path=fs_path,
    )


# ========== API：手动设封面 ==========
class ProjectCoverUpdate(BaseModel):
    # 直接用 Image.file_rel_path（相对 MEDIA_ROOT）
    file_rel_path: str


class ProjectMergeRequest(BaseModel):
    target_id: int
    source_ids: List[int]


class ProjectMergeResponse(BaseModel):
    target: schemas.ProjectOut
    removed_ids: List[int]


@app.post("/api/projects/{project_id}/cover", response_model=schemas.ProjectOut)
def set_project_cover_api(
    project_id: int,
    payload: ProjectCoverUpdate,
    db: Session = Depends(get_db),
):
    """
    手动设封面：
    - 请求体只需要传 file_rel_path（相对 MEDIA_ROOT）
    - 该图片必须属于这个项目，否则返回 404
    - 设置封面后会自动生成封面缩略图，并把 is_meta_locked 置为 True
    """
    project = crud.set_project_cover(
        db,
        project_id=project_id,
        file_rel_path=payload.file_rel_path,
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Project or image not found")

    cover_url: Optional[str] = None
    if getattr(project, "cover_rel_path", None):
        cover_url = f"/thumbs/{project.cover_rel_path}"

    fs_path = crud._build_fs_path(project.folder_path)

    try:
        tags = [t.name for t in getattr(project, "tags", [])] if project.tags else []
    except Exception:
        tags = []

    return schemas.ProjectOut(
        id=project.id,
        name=project.name,
        folder_path=project.folder_path,
        cover_url=cover_url,
        architect=project.architect,
        description=project.description,
        location=project.location,
        category=project.category,
        year=project.year,
        display_order=project.display_order,
        tags=tags,
        fs_path=fs_path,
    )


@app.post("/api/projects/merge", response_model=ProjectMergeResponse)
def merge_projects_api(
    payload: ProjectMergeRequest,
    db: Session = Depends(get_db),
):
    """
    合并多个项目到一个目标项目：
    - target_id: 保留的目标项目
    - source_ids: 被合并进来的项目（合并后会被删除）
    """
    target_id = payload.target_id
    source_ids = list(set(payload.source_ids or []))

    if not source_ids:
        raise HTTPException(status_code=400, detail="source_ids 不能为空")

    # 如果把目标 id 也传进来了，从 source_ids 中去掉
    if target_id in source_ids:
        source_ids.remove(target_id)

    if not source_ids:
        raise HTTPException(status_code=400, detail="没有有效的待合并项目")

    target = crud.get_project_by_id(db, target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Target project not found")

    # 查出所有源项目，确保都存在
    sources = (
        db.query(models.Project)
        .filter(models.Project.id.in_(source_ids))
        .all()
    )
    found_ids = {p.id for p in sources}
    missing_ids = [pid for pid in source_ids if pid not in found_ids]
    if missing_ids:
        raise HTTPException(
            status_code=404,
            detail=f"Source project(s) not found: {', '.join(map(str, missing_ids))}",
        )

    merged_target, removed_ids = crud.merge_projects(db, target, sources)

    # 组装 ProjectOut（和其它接口保持一致）
    cover_url: Optional[str] = None
    if getattr(merged_target, "cover_rel_path", None):
        cover_url = f"/thumbs/{merged_target.cover_rel_path}"

    fs_path = crud._build_fs_path(merged_target.folder_path)

    try:
        tags = [t.name for t in getattr(merged_target, "tags", [])] if merged_target.tags else []
    except Exception:
        tags = []

    target_out = schemas.ProjectOut(
        id=merged_target.id,
        name=merged_target.name,
        folder_path=merged_target.folder_path,
        cover_url=cover_url,
        architect=merged_target.architect,
        description=merged_target.description,
        location=merged_target.location,
        category=merged_target.category,
        year=merged_target.year,
        display_order=merged_target.display_order,
        tags=tags,
        fs_path=fs_path,
    )

    return ProjectMergeResponse(target=target_out, removed_ids=removed_ids)


# ========== API：项目点击（全站热度 +1） ==========
@app.post("/api/projects/{project_id}/click")
def click_project(
    project_id: int,
    db: Session = Depends(get_db),
):
    """
    每点击一次项目卡片，就把该项目的 heat +1，并记录一条点击日志。
    前端目前只需要 id 和最新 heat。
    """
    project = crud.increment_project_heat(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    return {"id": project.id, "heat": project.heat}


# ========== API：图片列表 ==========
@app.get("/api/images", response_model=List[schemas.ImageOut])
def list_images(
    q: Optional[str] = Query(None, description="搜索关键词（按文件名、标签等）"),
    project_id: Optional[int] = Query(None, description="按项目过滤"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    images = crud.get_images(
        db,
        q=q,
        project_id=project_id,
        limit=limit,
        offset=offset,
    )
    return images


# ========== API：手动刷新案例库（管理员按钮调用） ==========
@app.post("/api/admin/resync")
def admin_resync(
    db: Session = Depends(get_db),
):
    """
    手动触发一次 sync_from_fs。
    建议前端“刷新案例库”按钮调用这个接口。
    """
    sync_from_fs(db)
    return {"status": "ok"}


# ========== 本地开发启动 ==========
if __name__ == "__main__":
    import os
    import uvicorn

    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        reload=True,  # 继续保持自动重载
    )
