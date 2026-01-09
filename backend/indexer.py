import os
import json
import logging

from pathlib import Path
from datetime import datetime
from typing import Iterable, Optional

from sqlalchemy.orm import Session

import models
from config import MEDIA_ROOT, PROJECTS_ROOT

logger = logging.getLogger(__name__)

# 支持的图片后缀
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".tif"}

THUMB_DIR_NAME = "_thumbs"
THUMB_LONG_EDGE = 800


def load_project_meta(folder_abs_path: str) -> dict:
    """
    从项目文件夹中读取 project.json，如果没有或出错，返回 {}。

    兼容两种结构（旧版平铺 / 新版带 meta、display 等），这里只负责把 JSON 读成 dict，
    上层再去拆字段。
    """
    meta_path = Path(folder_abs_path) / "project.json"
    if not meta_path.is_file():
        return {}

    try:
        # 先整体读出来，避免空文件直接 json.load 报 Expecting value
        raw = meta_path.read_text(encoding="utf-8").strip()
        if not raw:
            logger.warning("project.json 为空 (%s)，按无 meta 处理", meta_path)
            return {}

        data = json.loads(raw)
        if not isinstance(data, dict):
            logger.warning("project.json 根节点不是对象 (%s)，按无 meta 处理", meta_path)
            return {}

        return data

    except Exception as e:
        # 你日志里那几条就是这里打出来的
        logger.warning("读取 project.json 失败 (%s): %s", meta_path, e)
        return {}


def iter_image_files(project_dir: Path, project_roots: Iterable[Path]) -> Iterable[Path]:
    """
    遍历某个项目目录下所有图片文件（递归）。

    规则：
    - 递归扫描 project_dir
    - 始终跳过名为 `_thumbs` 的目录及其子目录
    - 如果该项目目录下面还有“子项目”（也被识别为项目目录），
      则不会把子项目目录及其子树中的图片算到当前项目里，避免重复计入。
    """
    project_dir = project_dir.resolve()
    project_roots_set = {p.resolve() for p in project_roots}

    # 找出当前项目目录下的“子项目根目录”
    subproject_roots = {
        p for p in project_roots_set
        if p != project_dir and project_dir in p.parents
    }

    for dirpath, dirnames, filenames in os.walk(project_dir):
        current = Path(dirpath)

        # 如果进入了某个子项目目录，则整棵子树交给子项目自身处理，这里直接跳过
        if current in subproject_roots:
            dirnames[:] = []
            continue

        # 跳过 _thumbs 目录及其子目录
        dirnames[:] = [d for d in dirnames if d != THUMB_DIR_NAME]

        for name in filenames:
            ext = Path(name).suffix.lower()
            if ext in IMAGE_EXTS:
                yield Path(dirpath) / name


def iter_project_dirs(root: Path) -> Iterable[Path]:
    """
    递归遍历 root，寻找“项目目录”。

    新规则：

    1）任何目录中只要有 project.json → 必然是一个项目目录
        · 即使它下面还有子项目，也允许并行存在

    2）没有 project.json 时，只把“叶子图片目录”当成项目：
        · 该目录自身包含图片文件（直接放在此目录下的图片）；
        · 并且它的子树中不存在其他被认定为项目的目录（不再向下有“项目级”图片目录）。

    3）名为 `_thumbs` 的目录及其子目录一律跳过：
        · 不参与项目识别，也不会被视为分类目录或项目目录。
    """
    root = root.resolve()

    # -------- 第一遍：收集目录信息 --------
    dir_info: dict[Path, dict] = {}

    for dirpath, dirnames, filenames in os.walk(root):
        path = Path(dirpath)

        # 跳过 _thumbs 目录及其子目录
        dirnames[:] = [d for d in dirnames if d != THUMB_DIR_NAME]

        has_project_json = (path / "project.json").is_file()
        has_image_here = any(
            Path(name).suffix.lower() in IMAGE_EXTS
            for name in filenames
        )
        children = [path / d for d in dirnames]

        dir_info[path] = {
            "has_project_json": has_project_json,
            "has_image_here": has_image_here,
            "children": children,
        }

    if not dir_info:
        return

    # -------- 第二遍：自底向上判定项目目录 --------

    def depth(p: Path) -> int:
        """计算相对 root 的深度，用于排序。"""
        try:
            rel = p.relative_to(root)
        except ValueError:
            return 0
        return len(rel.parts)

    # 按深度从深到浅排序，确保先处理子目录，再处理父目录
    sorted_paths = sorted(dir_info.keys(), key=depth, reverse=True)

    is_project: dict[Path, bool] = {}
    has_project_subtree: dict[Path, bool] = {}

    for path in sorted_paths:
        info = dir_info[path]
        children = info["children"]

        # 子树中是否已有项目（不含当前目录本身）
        has_project_below = any(
            has_project_subtree.get(child, False) for child in children
        )

        if info["has_project_json"]:
            # 规则 1：有 project.json 的目录必然是项目
            is_project[path] = True
        elif info["has_image_here"] and not has_project_below:
            # 规则 2：叶子图片目录才是项目
            is_project[path] = True
        else:
            is_project[path] = False

        # 当前目录及其子树是否存在项目目录
        has_project_subtree[path] = is_project[path] or has_project_below

    # 按路径排序输出项目目录，保证结果稳定
    for path in sorted(sorted_paths):
        if is_project.get(path):
            yield path


# ========== 缩略图工具函数（保留给 /thumbs 路由等按需调用） ==========

def _generate_thumbnail(src: Path, dst: Path, long_edge: int = THUMB_LONG_EDGE) -> None:
    """
    从 src 生成一张缩略图写到 dst，长边缩放到指定像素。
    需要安装 Pillow：pip install Pillow
    """
    from PIL import Image as PILImage  # 延迟导入，避免无 Pillow 时模块级导入失败

    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        with PILImage.open(src) as im:
            # 转成 RGB，避免 RGBA / P 等模式保存出问题
            if im.mode not in ("RGB", "L"):
                im = im.convert("RGB")
            im.thumbnail((long_edge, long_edge))
            im.save(dst)
    except Exception as e:
        logger.warning("生成缩略图失败 (%s -> %s): %s", src, dst, e)


def ensure_thumb_for_image(
    abs_image_path: Path,
    project_dir: Path,
) -> Optional[Path]:
    """
    确保给定原图有一张对应的缩略图，返回缩略图路径（可能为 None）。

    规则：
    - 缩略图统一放在项目目录下的 `_thumbs` 子树中，保持与项目内相对路径一致：
      原图：   <project_dir>/<子路径>/xxx.jpg
      缩略图： <project_dir>/_thumbs/<子路径>/xxx.jpg
    - 若缩略图已存在则**先检查是否损坏**，损坏则删除并重建；
    - 若原图不存在则记录 warning 后返回 None。

    注意：本函数现在**不再在 sync_from_fs 里被批量调用**，
          只给 /thumbs 路由或其他“按需生成”的场景用。
    """
    project_dir = project_dir.resolve()
    abs_image_path = abs_image_path.resolve()

    try:
        rel_to_project = abs_image_path.relative_to(project_dir)
    except ValueError:
        logger.warning(
            "图片不在项目目录内，无法生成缩略图: %s (project_dir=%s)",
            abs_image_path,
            project_dir,
        )
        return None

    thumb_path = project_dir / THUMB_DIR_NAME / rel_to_project

    # 如果缩略图已经存在，先简单做一次“健康检查”
    if thumb_path.is_file():
        try:
            from PIL import Image as PILImage
            with PILImage.open(thumb_path) as im:
                im.verify()  # 不解码整图，只校验文件结构
            return thumb_path
        except Exception as e:
            logger.warning("检测到损坏的缩略图，准备重建 (%s): %s", thumb_path, e)
            try:
                thumb_path.unlink()
            except OSError as del_err:
                logger.warning("删除损坏缩略图失败: %s (%s)", thumb_path, del_err)
            # 继续往下，用原图重建

    if not abs_image_path.is_file():
        logger.warning("原图不存在，无法生成缩略图: %s", abs_image_path)
        return None

    _generate_thumbnail(abs_image_path, thumb_path)
    return thumb_path if thumb_path.is_file() else None


# ========== 主同步逻辑（扫盘 + 更新数据库 + 清理幽灵项目） ==========
def sync_from_fs(db: Session) -> None:
    """
    从 MEDIA_ROOT（配置的案例库根目录）下扫描文件系统，同步到数据库。

    关键规则：

    - 以 PROJECTS_ROOT 为根目录，递归查找“项目目录”（见 iter_project_dirs）：
      · 有 project.json 的目录 → 必然是一个项目；
      · 否则，仅“叶子图片目录”作为项目；
      · 名为 `_thumbs` 的目录及其子目录被完全跳过。

    - 每个“项目目录”视为一个 Project，folder_path 为相对 MEDIA_ROOT 的路径。

    - 项目目录下（含子目录）的所有图片文件（不含 `_thumbs`，且不含子项目目录及其子树）
      视为该项目的 Image：
      · Image.file_rel_path 始终是相对 MEDIA_ROOT 的路径；
      · 不会把 `_thumbs` 里的文件写入 Image 表；
      · 不会把“子项目”目录中的图片计入当前项目，避免重复。

    - **Image 在全表范围内以 file_rel_path 作为唯一标识**，避免重复插入：
      · 同一个 file_rel_path 如果已经存在，就只更新它的 project_id / file_name / 时间；
      · 不会再新建第二条记录，从而避免 UNIQUE 约束报错。

    - 项目的 name / architect / 等信息优先来自 project.json：
      · 新项目：直接用 JSON 初始化；
      · 已有项目：仅在 is_meta_locked=False 时允许被 JSON 覆盖。

    - 封面逻辑：
      · 若项目未锁定（is_meta_locked=False），扫描图片时自动选择“第一张图片”作为封面
        （按扫描顺序第一张），写入 Project.cover_rel_path；
      · 若项目已锁定，则保留原有 cover_rel_path，不被索引器覆盖。

    注意：本函数 **不生成缩略图**。
          缩略图统一通过 /thumbs 路由等“按需生成”，避免在全库同步时给文件服务器造成压力。
    """
    if not PROJECTS_ROOT.exists():
        logger.warning("PROJECTS_ROOT 不存在: %s", PROJECTS_ROOT)
        return

    now = datetime.utcnow()

    # 先把已有项目按 folder_path 建索引，避免重复插入
    existing_projects: dict[str, models.Project] = {
        p.folder_path: p for p in db.query(models.Project).all()
    }

    # ❗ 新增：把已有图片按 file_rel_path 建一个“全局索引”，一库只允许一条
    existing_images_by_path: dict[str, models.Image] = {
        img.file_rel_path: img for img in db.query(models.Image).all()
    }

    # 统计信息，方便排查问题
    created_projects = 0
    updated_projects = 0
    deleted_projects = 0
    created_images = 0
    deleted_images = 0

    # 记录这次扫描到的“实际存在的项目目录”（相对 MEDIA_ROOT 的 folder_path）
    seen_folders: set[str] = set()

    # ❗ 新增：记录这次扫描到的所有图片 file_rel_path，用于后面全局清理“幽灵图片”
    seen_image_paths: set[str] = set()

    # 先算出所有项目目录列表，供后续图片扫描时用来排除子项目目录
    project_dirs = list(iter_project_dirs(PROJECTS_ROOT))

    # 遍历所有项目目录（支持多级目录，遵从“叶子图片目录”规则）
    for project_dir in project_dirs:
        if not project_dir.is_dir():
            continue

        # 相对 MEDIA_ROOT 的文件夹路径，例如：
        #   "Beal Blanckaert Architectes"
        #   "体育建筑/某项目"
        #   "文化建筑/子类/某项目"
        rel_folder = project_dir.relative_to(MEDIA_ROOT).as_posix()
        seen_folders.add(rel_folder)

        # === 从 project.json 读取项目信息（如果有） ===
        meta = load_project_meta(str(project_dir))

        meta_name = project_dir.name
        meta_architect = None
        meta_location = None
        meta_category = None
        meta_year = None
        meta_description = None
        meta_order = None

        if isinstance(meta, dict):
            # 优先使用 meta 节点，没有则退回旧版平铺结构
            src = meta.get("meta")
            if not isinstance(src, dict):
                src = meta

            name_val = src.get("name")
            arch_val = src.get("architect")
            loc_val = src.get("location")
            cat_val = src.get("category")
            year_val = src.get("year")
            desc_val = src.get("description")

            if isinstance(name_val, str) and name_val.strip():
                meta_name = name_val.strip()
            if isinstance(arch_val, str) and arch_val.strip():
                meta_architect = arch_val.strip()
            if isinstance(loc_val, str) and loc_val.strip():
                meta_location = loc_val.strip()
            if isinstance(cat_val, str) and cat_val.strip():
                meta_category = cat_val.strip()
            if isinstance(desc_val, str) and desc_val.strip():
                meta_description = desc_val.strip()
            if year_val is not None:
                try:
                    meta_year = int(year_val)
                except (TypeError, ValueError):
                    meta_year = None

            display = meta.get("display")
            if isinstance(display, dict):
                order_val = display.get("order")
                if isinstance(order_val, int):
                    meta_order = order_val

        effective_name = meta_name
        effective_architect = meta_architect

        # === 新建或更新 Project ===
        project = existing_projects.get(rel_folder)
        is_new_project = project is None

        if is_new_project:
            # 新项目：用 project.json 的信息初始化（没有 json 则用默认值）
            project = models.Project(
                name=effective_name,
                folder_path=rel_folder,
                architect=effective_architect,
                location=meta_location,
                category=meta_category,
                year=meta_year,
                description=meta_description,
                display_order=meta_order,
                created_at=now,
                updated_at=now,
            )
            db.add(project)
            db.flush()  # 立刻拿到 project.id
            existing_projects[rel_folder] = project
            created_projects += 1
        else:
            # 已有项目：仅在 is_meta_locked=False 时允许被 JSON 覆盖
            changed = False
            if not getattr(project, "is_meta_locked", False):
                if project.name != effective_name:
                    project.name = effective_name
                    changed = True

                if getattr(project, "architect", None) != effective_architect:
                    project.architect = effective_architect
                    changed = True

                if getattr(project, "location", None) != meta_location:
                    project.location = meta_location
                    changed = True

                if getattr(project, "category", None) != meta_category:
                    project.category = meta_category
                    changed = True

                if getattr(project, "year", None) != meta_year:
                    project.year = meta_year
                    changed = True

                if getattr(project, "description", None) != meta_description:
                    project.description = meta_description
                    changed = True

                if getattr(project, "display_order", None) != meta_order:
                    project.display_order = meta_order
                    changed = True

            if changed:
                project.updated_at = now
                updated_projects += 1

        # === 同步图片（⚠ 这里开始是关键修改） ===
        # 不再按项目单独查 Image，而是用上面构建好的 existing_images_by_path 做“全局去重”
        first_image_rel_path: Optional[str] = None

        # 遍历这个项目目录下的所有图片（递归，跳过 _thumbs，并跳过子项目目录）
        for file_path in iter_image_files(project_dir, project_dirs):
            # 相对 MEDIA_ROOT 的路径，例如：
            #   "Beal Blanckaert Architectes/xxx.jpg"
            #   "体育建筑/某项目/图1.png"
            rel_path = file_path.relative_to(MEDIA_ROOT).as_posix()
            file_name = file_path.name

            # 记录这次全局扫描里确实存在的图片路径
            seen_image_paths.add(rel_path)

            if first_image_rel_path is None:
                first_image_rel_path = rel_path

            img = existing_images_by_path.get(rel_path)
            if img is None:
                # 这个 file_rel_path 之前从未出现过 → 新建一条 Image
                img = models.Image(
                    project_id=project.id,
                    file_name=file_name,
                    file_rel_path=rel_path,
                    created_at=now,
                    updated_at=now,
                )
                db.add(img)
                existing_images_by_path[rel_path] = img
                created_images += 1
            else:
                # 已经有这个路径的记录 → 更新归属项目、文件名与更新时间
                changed_img = False
                if img.project_id != project.id:
                    img.project_id = project.id
                    changed_img = True
                if img.file_name != file_name:
                    img.file_name = file_name
                    changed_img = True
                if changed_img:
                    img.updated_at = now

        # === 自动封面逻辑（仅未锁定项目） ===
        if not getattr(project, "is_meta_locked", False):
            # 仅在未锁定时才允许自动调整封面
            old_cover = getattr(project, "cover_rel_path", None)
            new_cover = first_image_rel_path  # 若 None，则表示该项目目前没有图片

            if old_cover != new_cover:
                project.cover_rel_path = new_cover
                project.updated_at = now

    # === 全局清理“数据库里有，但这次扫盘没找到”的图片 ===
    # 这里按 file_rel_path 维度统一清理，防止“幽灵图片”残留
    for rel_path, img in list(existing_images_by_path.items()):
        if rel_path not in seen_image_paths:
            db.delete(img)
            deleted_images += 1

    # === 清理“数据库里有，但磁盘没有目录或已不再被视为项目目录”的项目 ===
    for folder_path, project in list(existing_projects.items()):
        # folder_path 是相对 MEDIA_ROOT 的路径，例如 "体育建筑/某项目"
        project_dir = (MEDIA_ROOT / folder_path).resolve()
        # 1）磁盘上目录已经不存在
        # 2）目录还在，但这次扫描没有把它识别为项目目录（旧版本遗留的“幽灵项目”）
        if (not project_dir.exists()) or (folder_path not in seen_folders):
            db.delete(project)
            deleted_projects += 1

    db.commit()

    logger.info(
        "sync_from_fs 完成: 新增项目 %d, 更新项目 %d, 删除项目 %d; 新增图片 %d, 删除图片 %d",
        created_projects,
        updated_projects,
        deleted_projects,
        created_images,
        deleted_images,
    )
