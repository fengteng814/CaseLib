# backend/web_import_common.py
import json
import logging
import re
from pathlib import Path
from typing import Dict, Any, Optional, List, Callable

import requests
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class ParsedProject(BaseModel):
    """
    各站点解析结果的统一结构。
    """
    site: str                # 站点 key，例如 "archdaily"
    url: str                 # 原始项目 URL
    title: str               # 项目标题
    suggested_folder: str    # 建议的文件夹名
    meta: Dict[str, Any] = {}        # 其他元数据：architect / location / year ...
    image_urls: List[str] = []       # 大图 URL 列表（导入时下载）


def fetch_html(url: str) -> str:
    """
    携带 UA 请求网页 HTML。
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0 Safari/537.36"
        )
    }
    resp = requests.get(url, headers=headers, timeout=20)
    resp.raise_for_status()
    return resp.text


def slugify(text: str) -> str:
    """
    把项目名转成一个比较安全的文件夹名。
    """
    text = (text or "").strip()
    text = re.sub(r"[\\/:*?\"<>|]", "_", text)
    text = re.sub(r"\s+", "_", text)
    return text or "project"


def absolute_image_url(img_src: str, page_url: str) -> Optional[str]:
    """
    把图片相对地址转成绝对地址。
    """
    if not img_src:
        return None
    img_src = img_src.strip()
    if not img_src or img_src.startswith("data:"):
        return None

    if img_src.startswith("http://") or img_src.startswith("https://"):
        return img_src

    from urllib.parse import urljoin
    return urljoin(page_url, img_src)


def safe_folder_name(name: str) -> str:
    name = (name or "").strip()
    name = re.sub(r"[\\/:*?\"<>|]", "_", name)
    return name or "project"

def download_images(
    parsed: ParsedProject,
    dest_dir: Path,
    task_id: str,
    update_task_cb: Callable[[str, Optional[str], Optional[float], Optional[str]], None],
) -> None:
    """
    通用图片下载逻辑：
    - parsed.image_urls: 所有图片 URL；
    - parsed.meta.get("image_title_map"): URL -> 标题（用于命名文件）。
    - update_task_cb: 用于反馈进度的回调。
    """
    urls = parsed.image_urls or []

    # 去重保持顺序
    seen = set()
    uniq_urls: List[str] = []
    for u in urls:
        if u and u not in seen:
            seen.add(u)
            uniq_urls.append(u)
    urls = uniq_urls

    dest_dir.mkdir(parents=True, exist_ok=True)

    total = len(urls)
    if total == 0:
        update_task_cb(
            task_id,
            status="running",
            progress=0.0,
            message="没有找到可用图片",
        )
        return

    # URL -> 标题
    title_map: Dict[str, str] = {}
    raw_map = parsed.meta.get("image_title_map") if isinstance(parsed.meta, dict) else None
    if isinstance(raw_map, dict):
        for k, v in raw_map.items():
            if isinstance(k, str) and isinstance(v, str):
                title_map[k] = v

    # === 关键修改：针对微信图片增加 Referer，其他站点保持通用 UA ===
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0 Safari/537.36"
        )
    }
    if parsed.site.startswith("wechat"):
        # 微信图床一般需要带上文章页作为 Referer，否则容易 403
        headers["Referer"] = parsed.url

    for idx, img_url in enumerate(urls, start=1):
        # 推断后缀
        ext = ".jpg"
        m = re.search(r"\.(jpg|jpeg|png|webp|gif)(?:\?|$)", img_url, re.IGNORECASE)
        if m:
            ext = "." + m.group(1).lower()

        # 文件名：优先用标题
        title = title_map.get(img_url)
        if title:
            base = title.strip()
            base = re.sub(r"[\\/:*?\"<>|]", "_", base)
            base = re.sub(r"\s+", "_", base)
            if len(base) > 80:
                base = base[:80]
            filename = f"{idx:02d}_{base}{ext}"
        else:
            filename = f"{idx:02d}{ext}"

        file_path = dest_dir / filename

        try:
            logger.info("下载图片 %s -> %s", img_url, file_path)
            resp = requests.get(img_url, headers=headers, stream=True, timeout=30)
            resp.raise_for_status()
            with open(file_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
        except Exception as e:
            logger.warning("下载图片失败: %s (%s)", img_url, e)

        progress = idx / total
        update_task_cb(
            task_id,
            status="running",
            progress=progress,
            message=f"已下载 {idx}/{total} 张图片",
        )


def write_project_json(parsed: ParsedProject, dest_dir: Path) -> None:
    """
    按统一格式写 project.json：
    - name / architect / location / category / year / description
    - source（内含 site + url）
    - source_site（冗余一份简单字符串，方便以后直接读取）
    """
    dest_dir.mkdir(parents=True, exist_ok=True)

    meta = parsed.meta or {}

    location = (
        meta.get("location")
        or meta.get("location_city")
        or meta.get("location_country")
    )

    data: Dict[str, Any] = {
        "name": parsed.title,
        "architect": meta.get("architect"),
        "location": location,
        "category": meta.get("category"),
        "year": meta.get("year"),
        "description": meta.get("description"),
        "source": {
            "site": parsed.site,
            "url": parsed.url,
        },
        # 额外冗余一个简单字段（“来源网站”）
        "source_site": parsed.site,
    }

    # 去掉为 None 的字段，保持 json 简洁
    data = {k: v for k, v in data.items() if v is not None}

    json_path = dest_dir / "project.json"
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
