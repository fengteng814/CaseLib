"""
全局配置：统一从 config.ini 读取。
"""

from pathlib import Path
import configparser

# backend 目录: .../CaseLib/backend
BACKEND_DIR = Path(__file__).resolve().parent

# 仓库根目录: .../CaseLib
BASE_DIR = BACKEND_DIR.parent

# ========== 读取 config.ini ==========

config = configparser.ConfigParser()
ini_path = BASE_DIR / "config.ini"

if ini_path.exists():
    config.read(ini_path, encoding="utf-8")

# 从 [paths] 下面读取:
# - media_root       : 后端本机访问案例库的实际路径（本地盘符或 UNC 都可以）
# - media_share_root : （可选）客户端复制用的共享路径前缀（UNC）。不写则默认等于 media_root。
media_root_fs = ""
media_share_root = ""

if config.has_section("paths"):
    if config.has_option("paths", "media_root"):
        media_root_fs = config.get("paths", "media_root").strip()
    if config.has_option("paths", "media_share_root"):
        media_share_root = config.get("paths", "media_share_root").strip()

# 默认的仓库内 media 目录
default_media = (BASE_DIR / "media").resolve()

# 1) 后端真正用于扫盘 / 读写文件的路径
#    没配就用仓库里的 media 目录
fs_root_str = media_root_fs or str(default_media)
MEDIA_ROOT = Path(fs_root_str).expanduser().resolve()

# 2) 给前端“复制路径”用的共享前缀（字符串，不做 Path 解析）
#    如果没单独配置 media_share_root，就退回 media_root；再没就退回默认 media 目录。
if not media_share_root:
    media_share_root = media_root_fs or str(default_media)

MEDIA_ROOT_RAW = media_share_root

# 项目案例所在根目录：现在直接等于 MEDIA_ROOT，
# 下面可以直接是各个项目的子目录（不再强制有 "projects" 这一层）
PROJECTS_ROOT = MEDIA_ROOT

# ========== 前端分页 / 标签配置（从 [frontend] 读取，带默认值） ==========

DEFAULT_INITIAL_PROJECT_LIMIT = 60   # 首页初始加载多少个项目
DEFAULT_PROJECT_PAGE_SIZE = 30      # 滚动一次再加载多少个
DEFAULT_HOT_TAG_LIMIT = 10          # 常用标签前多少名（后面会用）
DEFAULT_FIXED_HOT_TAGS: list[str] = []  # 默认没有固定标签

if config.has_section("frontend"):
    INITIAL_PROJECT_LIMIT = config.getint(
        "frontend", "initial_project_limit", fallback=DEFAULT_INITIAL_PROJECT_LIMIT
    )
    PROJECT_PAGE_SIZE = config.getint(
        "frontend", "project_page_size", fallback=DEFAULT_PROJECT_PAGE_SIZE
    )
    HOT_TAG_LIMIT = config.getint(
        "frontend", "hot_tag_limit", fallback=DEFAULT_HOT_TAG_LIMIT
    )

    # fixed_hot_tags = 体育, 文化, 教育, 图书馆, 博物馆
    fixed_raw = config.get("frontend", "fixed_hot_tags", fallback="")
    if fixed_raw:
        FIXED_HOT_TAGS = [
            s.strip() for s in fixed_raw.split(",") if s.strip()
        ]
    else:
        FIXED_HOT_TAGS = DEFAULT_FIXED_HOT_TAGS.copy()
else:
    INITIAL_PROJECT_LIMIT = DEFAULT_INITIAL_PROJECT_LIMIT
    PROJECT_PAGE_SIZE = DEFAULT_PROJECT_PAGE_SIZE
    HOT_TAG_LIMIT = DEFAULT_HOT_TAG_LIMIT
    FIXED_HOT_TAGS = DEFAULT_FIXED_HOT_TAGS.copy()

# 前端静态资源路径：一般不需要动
FRONTEND_DIR = BASE_DIR / "frontend"
FRONTEND_INDEX = FRONTEND_DIR / "index.html"
