# backend/web_import_sites/archdaily.py
import json
import html as html_lib
import logging
import re
from typing import Dict, Any, List, Optional

from bs4 import BeautifulSoup

from web_import_common import ParsedProject, fetch_html, slugify, absolute_image_url

logger = logging.getLogger(__name__)

SITE_KEY = "archdaily"
SITE_NAME = "ArchDaily"
MATCH_DOMAINS = ["archdaily.cn", "archdaily.com"]


def _parse_gallery_from_photo_page(photo_url: str) -> tuple[List[str], Dict[str, str]]:
    """
    访问图片库页面（含 #gallery-items），解析所有大图 URL + 标题。
    返回 (image_urls, title_map)。
    """
    html_text = fetch_html(photo_url)
    soup = BeautifulSoup(html_text, "html.parser")

    gallery_div = soup.find("div", id="gallery-items")
    if not gallery_div:
        logger.info("ArchDaily: gallery-items 未找到，URL=%s", photo_url)
        return [], {}

    raw = gallery_div.get("data-images") or ""
    if not raw:
        logger.info("ArchDaily: data-images 为空，URL=%s", photo_url)
        return [], {}

    data = None
    # data-images 可能是 HTML 转义后的 JSON，尝试两次
    for candidate in (raw, html_lib.unescape(raw)):
        try:
            data = json.loads(candidate)
            break
        except Exception:
            data = None

    image_urls: List[str] = []
    title_map: Dict[str, str] = {}

    if isinstance(data, list):
        for fig in data:
            if not isinstance(fig, dict):
                continue

            url_large = (
                fig.get("url_large")
                or fig.get("url")
                or fig.get("src")
            )

            urls_dict = fig.get("urls")
            if not url_large and isinstance(urls_dict, dict):
                url_large = urls_dict.get("url_large") or urls_dict.get("url")

            if not url_large:
                continue

            full = absolute_image_url(url_large, photo_url)
            if not full:
                continue

            image_urls.append(full)

            title = (
                fig.get("title")
                or fig.get("caption")
                or fig.get("alt")
                or ""
            )
            if title:
                clean = re.sub(r"[\\/:*?\"<>|]", "_", title.strip())
                clean = re.sub(r"\s+", "_", clean)
                if len(clean) > 60:
                    clean = clean[:60]
                title_map[full] = clean
    else:
        # 如果 data 不是 JSON，退回在原始字符串里用正则找 URL
        urls = re.findall(r"https?://[^\s\"']+", raw)
        for u in urls:
            if "images.adsttc.com" in u and (
                "large_jpg" in u or "original" in u or "large" in u
            ):
                image_urls.append(u)

    # 去重
    seen = set()
    uniq_urls: List[str] = []
    for u in image_urls:
        if u not in seen:
            seen.add(u)
            uniq_urls.append(u)

    return uniq_urls, title_map


def _find_gallery_link(soup: BeautifulSoup, page_url: str) -> Optional[str]:
    """
    在项目页 DOM 中找到指向图片库的链接。
    """
    from urllib.parse import urljoin

    # 1) 优先按 class 含 gallery-link 的 <a>
    a_tag = soup.find("a", class_=lambda c: c and "gallery-link" in c)
    if a_tag and a_tag.get("href"):
        return urljoin(page_url, a_tag["href"])

    # 2) 退一步：href 中含 /images/ 或 /gallery/，或文本包含 “Gallery / 项目图库”
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = (a.get_text() or "").strip()
        if "/images/" in href or "/gallery/" in href:
            return urljoin(page_url, href)
        if text and ("项目图库" in text or "Gallery" in text):
            return urljoin(page_url, href)

    return None


def _parse_meta(soup: BeautifulSoup, url: str, title: str) -> Dict[str, Any]:
    """
    尽量从 specs 区块里提取 architect / location / category / year 等信息。
    """
    meta: Dict[str, Any] = {
        "source_site": SITE_KEY,
        "source_url": url,
    }

    # 位置：afd-specs__header-location
    loc_header = soup.find(class_=lambda c: c and "afd-specs__header-location" in c)
    if loc_header:
        txt = loc_header.get_text(strip=True)
        if txt:
            meta["location"] = txt
            parts = [p.strip() for p in txt.split(",") if p.strip()]
            if parts:
                meta["location_city"] = parts[0]
                if len(parts) > 1:
                    meta["location_country"] = parts[-1]

    # 类型：afd-specs__header-category
    cat_el = soup.find(class_=lambda c: c and "afd-specs__header-category" in c)
    if cat_el:
        a = cat_el.find("a")
        txt = (a.get_text(strip=True) if a else cat_el.get_text(strip=True)) or ""
        if txt:
            meta["category"] = txt

    # specs__item 顺序（参考你给的插件）：
    # 1-Architects, 2-Area, 3-Year, 4-Photographs
    spec_items = soup.find_all(class_=lambda c: c and "afd-specs__item" in c)
    labels = ["architect", "area", "year", "photographers"]
    for i, item in enumerate(spec_items):
        if i >= len(labels):
            break
        text = item.get_text(strip=True)
        if not text:
            continue
        # 兼容中英文冒号
        value = text
        for sep in (":", "："):
            if sep in text:
                value = text.split(sep, 1)[1].strip()
                break
        if not value:
            continue
        meta[labels[i]] = value

    # 简单抓一段文本说明当 description（取前几段 <p>）
    paragraphs = []
    for p in soup.find_all("p"):
        t = p.get_text(" ", strip=True)
        if t:
            paragraphs.append(t)
    if paragraphs:
        desc = "\n\n".join(paragraphs[:6])
        meta["description"] = desc

    return meta


def parse(url: str) -> ParsedProject:
    """
    外部调用入口：给项目 URL，返回 ParsedProject。
    """
    html_text = fetch_html(url)
    soup = BeautifulSoup(html_text, "html.parser")

    # 标题
    title_tag = soup.find("h1")
    if title_tag and title_tag.get_text(strip=True):
        title = title_tag.get_text(strip=True)
    elif soup.title and soup.title.string:
        title = soup.title.string.strip()
    else:
        title = "Untitled ArchDaily Project"

    meta = _parse_meta(soup, url, title)

    # 1) 优先用 gallery 页面 data-images 抓大图
    image_urls: List[str] = []
    title_map: Dict[str, str] = {}

    gallery_url = _find_gallery_link(soup, url)
    if gallery_url:
        try:
            logger.info("ArchDaily: 使用 gallery 链接解析图片: %s", gallery_url)
            gallery_urls, title_map = _parse_gallery_from_photo_page(gallery_url)
            image_urls.extend(gallery_urls)
        except Exception as e:
            logger.warning("ArchDaily: 解析 gallery 页面失败: %s", e)

    # 2) 兜底：项目页上的 <img>（缩略图）
    if not image_urls:
        logger.info("ArchDaily: gallery 未解析到图片，退回项目页 DOM 扫描缩略图")
        for img in soup.find_all("img"):
            src = (
                img.get("data-largesrc")
                or img.get("data-src")
                or img.get("src")
                or ""
            )
            full_url = absolute_image_url(src, url)
            if not full_url:
                continue

            lower = full_url.lower()
            if any(k in lower for k in ["logo", "icon", "avatar", "svg", "sprite"]):
                continue
            if not re.search(r"\.(jpg|jpeg|png|webp|gif)(?:\?|$)", lower):
                continue

            image_urls.append(full_url)

            alt = img.get("alt") or img.get("title")
            if alt:
                clean = re.sub(r"[\\/:*?\"<>|]", "_", alt.strip())
                clean = re.sub(r"\s+", "_", clean)
                if len(clean) > 60:
                    clean = clean[:60]
                title_map[full_url] = clean

    # 去重
    seen = set()
    uniq_urls: List[str] = []
    for u in image_urls:
        if u not in seen:
            seen.add(u)
            uniq_urls.append(u)

    image_urls = uniq_urls
    meta["image_title_map"] = title_map

    return ParsedProject(
        site=SITE_KEY,
        url=url,
        title=title,
        suggested_folder=slugify(title),
        meta=meta,
        image_urls=image_urls,
    )
