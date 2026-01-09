# backend/web_import_sites/gooood.py
import html as html_lib
import logging
import re
from typing import Dict, Any, List, Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from bs4.element import NavigableString, Tag

from web_import_common import (
    ParsedProject,
    fetch_html,
    slugify,
    absolute_image_url,
)

logger = logging.getLogger(__name__)

SITE_KEY = "gooood"
SITE_NAME = "谷德设计网"
MATCH_DOMAINS = ["gooood.cn", "www.gooood.cn"]

API_BASE = "https://dashboard.gooood.cn/api/wp/v2"


# ========== 小工具 ==========

def _extract_slug(url: str) -> Optional[str]:
    """
    从项目页 URL 中提取 slug：
    https://www.gooood.cn/teviot-house-sao-paulo-by-casa100-architecture.htm
    -> teviot-house-sao-paulo-by-casa100-architecture
    """
    path = urlparse(url).path
    m = re.search(r"/([^/]+?)\.htm(?:/)?$", path, re.IGNORECASE)
    if not m:
        return None
    return m.group(1)


def _fetch_post_json_by_slug(slug: str) -> Optional[Dict[str, Any]]:
    """
    调用 Gooood 的 API 拿到单篇文章 JSON。
    """
    api_url = f"{API_BASE}/posts/byslug"
    try:
        resp = requests.get(
            api_url,
            params={"slug": slug},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict):
            return data
        logger.warning("Gooood API: 返回结果不是 dict，slug=%s", slug)
    except Exception as e:
        logger.warning("Gooood API: 请求失败 slug=%s, err=%s", slug, e)
    return None


def _clean_filename(name: str) -> str:
    """
    清洗字符串为安全的文件名片段。
    """
    name = html_lib.unescape(name or "").strip()
    if not name:
        return ""

    name = re.sub(r"[\\/:*?\"<>|]", "_", name)
    name = re.sub(r"\s+", "_", name)
    if len(name) > 60:
        name = name[:60]
    return name


def _parse_images_from_api(
    post_json: Dict[str, Any]
) -> tuple[List[str], Dict[str, str]]:
    """
    从 API 的 JSON 里解析出图片 URL + 对应的命名映射。
    期望字段：gallery: [ { "full_url": "...", "title"/"alt"/"caption": "...", ... }, ... ]
    """
    image_urls: List[str] = []
    title_map: Dict[str, str] = {}

    gallery = post_json.get("gallery") or []
    if not isinstance(gallery, list):
        return [], {}

    for idx, img in enumerate(gallery):
        if not isinstance(img, dict):
            continue

        url = img.get("full_url") or img.get("url") or img.get("src")
        if not url:
            continue

        full_url = str(url).strip()
        if not full_url:
            continue

        image_urls.append(full_url)

        raw_name = (
            img.get("title")
            or img.get("caption")
            or img.get("alt")
            or ""
        )
        clean = _clean_filename(raw_name)
        if not clean:
            clean = f"image_{idx + 1}"

        title_map[full_url] = clean

    # 去重
    seen = set()
    uniq_urls: List[str] = []
    uniq_title_map: Dict[str, str] = {}

    for u in image_urls:
        if u in seen:
            continue
        seen.add(u)
        uniq_urls.append(u)
        if u in title_map:
            uniq_title_map[u] = title_map[u]

    return uniq_urls, uniq_title_map


def _parse_meta_from_api(post_json: Dict[str, Any], url: str) -> Dict[str, Any]:
    """
    从 API JSON 中尽量构造 meta 信息。
    这里不做太复杂的分类 / 标签二次请求，只保留基础信息。
    """
    meta: Dict[str, Any] = {
        "source_site": SITE_KEY,
        "source_url": url,
    }

    if "id" in post_json:
        meta["gooood_post_id"] = post_json["id"]
    if "slug" in post_json:
        meta["gooood_slug"] = post_json["slug"]

    if "date" in post_json:
        meta["date"] = post_json["date"]

    # 简要说明：优先 excerpt.rendered，其次 content.rendered
    excerpt_html = None
    excerpt = post_json.get("excerpt")
    if isinstance(excerpt, dict):
        excerpt_html = excerpt.get("rendered")

    if not excerpt_html:
        content = post_json.get("content")
        if isinstance(content, dict):
            excerpt_html = content.get("rendered")

    if excerpt_html:
        desc = BeautifulSoup(excerpt_html, "html.parser").get_text(" ", strip=True)
        if desc:
            meta["description"] = desc

    return meta


def _parse_title_from_api(post_json: Dict[str, Any]) -> Optional[str]:
    title_obj = post_json.get("title")
    if isinstance(title_obj, dict):
        rendered = title_obj.get("rendered") or ""
        if rendered:
            text = BeautifulSoup(rendered, "html.parser").get_text(" ", strip=True)
            if text:
                return text
    return None


def _parse_images_from_html(
    soup: BeautifulSoup, page_url: str
) -> tuple[List[str], Dict[str, str]]:
    """
    API 失败时，从页面 HTML 兜底解析图片。
    简单策略：抓所有 jpg/png/webp/gif，并尽量过滤 logo / icon 等。
    """
    image_urls: List[str] = []
    title_map: Dict[str, str] = {}

    for img in soup.find_all("img"):
        src = img.get("data-src") or img.get("src") or ""
        if not src:
            continue

        full_url = absolute_image_url(src, page_url)
        if not full_url:
            continue

        lower = full_url.lower()
        if not re.search(r"\.(jpg|jpeg|png|webp|gif)(?:\?|$)", lower):
            continue

        if any(k in lower for k in [
            "logo", "icon", "avatar", "qr", "qrcode",
            "wechat", "weixin", "instagram", "pinterest",
            "banner", "ads"
        ]):
            continue

        image_urls.append(full_url)

        alt = img.get("alt") or img.get("title")
        if not alt:
            filename = full_url.split("/")[-1].split("?")[0]
            alt = filename.rsplit(".", 1)[0]

        clean = _clean_filename(alt)
        if clean:
            title_map[full_url] = clean

    # 去重
    seen = set()
    uniq_urls: List[str] = []
    uniq_title_map: Dict[str, str] = {}

    for u in image_urls:
        if u in seen:
            continue
        seen.add(u)
        uniq_urls.append(u)
        if u in title_map:
            uniq_title_map[u] = title_map[u]

    return uniq_urls, uniq_title_map


def _parse_title_from_html(soup: BeautifulSoup) -> str:
    """
    从 HTML 中抓标题，兜底逻辑。
    """
    h1 = soup.find("h1")
    if h1 and h1.get_text(strip=True):
        return h1.get_text(strip=True)

    if soup.title and soup.title.string:
        return soup.title.string.strip()

    return "Untitled Gooood Project"


def _parse_specs_from_soup(soup: BeautifulSoup) -> Dict[str, List[str]]:
    """
    解析页面中的“项目标签 / Project Specs”块，返回：
    {
        "design": [...],
        "location": [...],
        "type": [...],
        "materials": [...],
        "tags": [...],
        "category": [...],
    }
    """
    # 找到“Project Specs / 项目标签”的标题节点
    def is_specs_title(tag: Tag) -> bool:
        if not isinstance(tag, Tag):
            return False
        text = tag.get_text(strip=True) if tag else ""
        if not text:
            return False
        text_no_space = text.replace(" ", "")
        return ("ProjectSpecs" in text_no_space) or ("项目标签" in text_no_space)

    specs_title = soup.find(is_specs_title)
    if not specs_title:
        return {}

    # 中英文标签映射到统一字段名
    label_to_field: Dict[str, str] = {}
    mapping = {
        "design": ["Design", "设计公司", "设计"],
        "location": ["Location", "位置", "地点"],
        "type": ["Type", "类型"],
        "materials": ["Materials", "材料"],
        "tags": ["Tags", "标签"],
        "category": ["Category", "分类"],
    }
    for field, labels in mapping.items():
        for lab in labels:
            label_to_field[lab.lower()] = field

    stop_markers = [
        "版权", "Copyright",
        "Recommended Jobs", "Latest Jobs", "Random Jobs",
        "Post a Comment", "发表评论",
        "Submissions", "投稿",
    ]

    specs: Dict[str, List[str]] = {}
    current_field: Optional[str] = None

    for node in specs_title.next_elements:
        if isinstance(node, NavigableString):
            txt = node.strip()
            if not txt:
                continue

            # 结束区域的标记
            if any(m in txt for m in stop_markers):
                break

            plain = txt.rstrip("：:").strip()
            if not plain:
                continue

            # 跳过标题自身
            if plain in ("Project Specs", "项目标签"):
                continue

            # 是否是一个新的“标签名”
            field = label_to_field.get(plain.lower())
            if field:
                current_field = field
                continue

            # 纯冒号
            if plain in (":", "："):
                continue

            # 普通内容，当作当前字段的值
            if current_field:
                specs.setdefault(current_field, [])
                if plain not in specs[current_field]:
                    specs[current_field].append(plain)

        elif isinstance(node, Tag):
            # 标题标签里的文字会在上面的 NavigableString 分支里处理，这里不用额外逻辑
            continue

    return specs


# ========== 对外主入口 ==========

def parse(url: str) -> ParsedProject:
    """
    外部调用入口：给 Gooood 项目 URL，返回 ParsedProject。
    """
    slug = _extract_slug(url)

    title: Optional[str] = None
    meta: Dict[str, Any] = {
        "source_site": SITE_KEY,
        "source_url": url,
    }
    image_urls: List[str] = []
    title_map: Dict[str, str] = {}

    # 先把 HTML 抓下来，方便兜底 + 解析项目标签
    soup: Optional[BeautifulSoup] = None
    try:
        html_text = fetch_html(url)
        soup = BeautifulSoup(html_text, "html.parser")
    except Exception as e:
        logger.warning("Gooood: 获取 HTML 失败 url=%s, err=%s", url, e)

    # 1) 优先用 API 拿 gallery 和基础信息
    post_json: Optional[Dict[str, Any]] = None
    if slug:
        post_json = _fetch_post_json_by_slug(slug)

    if post_json:
        logger.info("Gooood: 使用官方 API 解析 slug=%s", slug)

        api_title = _parse_title_from_api(post_json)
        if api_title:
            title = api_title

        api_meta = _parse_meta_from_api(post_json, url)
        meta.update(api_meta)

        api_image_urls, api_title_map = _parse_images_from_api(post_json)
        image_urls = api_image_urls
        title_map.update(api_title_map)

    # 2) HTML 兜底：标题 / 描述 / 图片 + 项目标签
    if soup is not None:
        # 标题兜底
        if not title:
            title = _parse_title_from_html(soup)

        # description 兜底：取前几段 <p>
        if "description" not in meta:
            paragraphs: List[str] = []
            for p in soup.find_all("p"):
                t = p.get_text(" ", strip=True)
                if t:
                    paragraphs.append(t)
            if paragraphs:
                meta["description"] = "\n\n".join(paragraphs[:6])

        # 图片兜底
        if not image_urls:
            html_image_urls, html_title_map = _parse_images_from_html(soup, url)
            image_urls = html_image_urls
            for k, v in html_title_map.items():
                title_map.setdefault(k, v)

        # 解析 “项目标签 / Project Specs”
        specs = _parse_specs_from_soup(soup)
        if specs:
            # 保存原始结构
            meta.setdefault("gooood_specs", specs)

            # 设计公司 -> architect / design
            if specs.get("design"):
                design_str = " / ".join(specs["design"])
                meta.setdefault("architect", design_str)
                meta.setdefault("design", design_str)

            # 位置
            if specs.get("location"):
                loc_str = " / ".join(specs["location"])
                meta.setdefault("location", loc_str)

            # 类型（Architecture / Landscape…）单独存
            if specs.get("type"):
                type_str = " / ".join(specs["type"])
                meta.setdefault("gooood_type", type_str)

            # 分类（办公室、工作室等真实建筑类型）
            if specs.get("category"):
                cat_str = " / ".join(specs["category"])
                meta.setdefault("category", cat_str)

            # 材料、标签：保持为列表
            if specs.get("materials"):
                meta.setdefault("materials", specs["materials"])
            if specs.get("tags"):
                meta.setdefault("tags", specs["tags"])

    if not title:
        title = "Untitled Gooood Project"

    meta["image_title_map"] = title_map

    return ParsedProject(
        site=SITE_KEY,
        url=url,
        title=title,
        suggested_folder=slugify(title),
        meta=meta,
        image_urls=image_urls,
    )
