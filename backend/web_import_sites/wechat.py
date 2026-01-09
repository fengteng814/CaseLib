import logging
import re
from typing import Dict, Any, List
from urllib.parse import urlparse, urljoin

from bs4 import BeautifulSoup

from web_import_common import ParsedProject, fetch_html, slugify

logger = logging.getLogger(__name__)

# 站点标识 & 域名匹配
SITE_KEY = "wechat_mp"
SITE_NAME = "微信公众号"
MATCH_DOMAINS = ["mp.weixin.qq.com"]


# ============= 文本字段抽取规则 =============

FIELD_PATTERNS = {
    "project_name": ["项目名称", "项目名", "工程名称", "项目"],
    "location": ["项目地点", "地点", "位置", "坐落", "地址"],
    "architect": ["设计单位", "建筑设计", "建筑师", "建筑单位"],
    "area": ["建筑面积", "总建筑面积", "用地面积"],
    "client": ["业主", "开发单位", "建设单位"],
}


def _normalize_wechat_img_url(url: str) -> str:
    """
    将微信图片 URL 的末尾尺寸（通常是 /640）尽量替换为 /0 以获取大图。
    例如：
      https://mmbiz.qpic.cn/mmbiz_png/xxxx/640?wx_fmt=png -> /0?wx_fmt=png
    """
    parsed = urlparse(url)
    # 把路径结尾的 /数字 替换为 /0
    path = re.sub(r"/(\d+)$", "/0", parsed.path)
    return parsed._replace(path=path).geturl()


def _extract_text_fields(content_root) -> Dict[str, str]:
    """
    从正文段落中用启发式规则抽取“项目名称 / 地点 / 设计单位”等信息。
    """
    info: Dict[str, str] = {}

    paragraphs = content_root.find_all(["p", "section", "span"])
    for p in paragraphs:
        text = p.get_text(separator=" ", strip=True)
        if not text:
            continue

        # 统一全角冒号
        text_norm = text.replace("：", ":")

        for field, keys in FIELD_PATTERNS.items():
            if field in info:
                continue
            for key in keys:
                if key not in text_norm:
                    continue

                # 匹配 “键: 值”
                m = re.search(rf"{re.escape(key)}\s*:\s*(.+)", text_norm)
                if not m:
                    continue

                value = m.group(1).strip()
                # 截断到句号 / 分号之前，避免后面一大串说明
                value = re.split(r"[。；;]", value)[0].strip()
                if value:
                    info[field] = value
                break

    return info


def _parse_meta(soup: BeautifulSoup, url: str, raw_title: str) -> Dict[str, Any]:
    """
    解析文章中可结构化的元信息：
    - location / architect / area / client
    - description：取前几段正文做简介
    """
    content_root = soup.find(id="js_content") or soup

    fields = _extract_text_fields(content_root)

    meta: Dict[str, Any] = {
        "source_site": SITE_KEY,
        "source_url": url,
    }

    if "location" in fields:
        meta["location"] = fields["location"]
    if "architect" in fields:
        meta["architect"] = fields["architect"]
    if "area" in fields:
        meta["area"] = fields["area"]
    if "client" in fields:
        meta["client"] = fields["client"]

    # 取正文前若干段作为 description
    paragraphs: List[str] = []
    for p in content_root.find_all("p"):
        t = p.get_text(" ", strip=True)
        if t:
            paragraphs.append(t)
    if paragraphs:
        meta["description"] = "\n\n".join(paragraphs[:6])

    return meta


def _parse_images(soup: BeautifulSoup, page_url: str) -> tuple[List[str], Dict[str, str]]:
    """
    从正文中解析图片 URL：
    - 只保留微信 CDN（mmbiz / qpic.cn）的图
    - 对 URL 做大图化处理（/640 -> /0）
    - 返回：image_urls + image_title_map（用于命名）
    """
    content_root = soup.find(id="js_content") or soup

    image_urls: List[str] = []
    title_map: Dict[str, str] = {}

    for img in content_root.find_all("img"):
        raw_src = img.get("data-src") or img.get("data-backsrc") or img.get("src")
        if not raw_src:
            continue

        src = raw_src.strip()
        if not src:
            continue

        # 绝对 URL
        full = urljoin(page_url, src)

        # 只要微信图床的图片
        if "mmbiz" not in full and "qpic.cn" not in full:
            continue

        full = _normalize_wechat_img_url(full)
        lower = full.lower()

        # 粗略跳过一些非项目图
        if any(k in lower for k in ["icon", "emoji", "emoticon"]):
            continue

        if full in image_urls:
            continue

        image_urls.append(full)

        alt = img.get("alt") or ""
        if alt:
            clean = re.sub(r"[\\/:*?\"<>|]", "_", alt.strip())
            clean = re.sub(r"\s+", "_", clean)
            if len(clean) > 60:
                clean = clean[:60]
            title_map[full] = clean

    return image_urls, title_map


def parse(url: str) -> ParsedProject:
    """
    站点统一入口：
    - 给一个微信公众号文章 URL
    - 返回 ParsedProject，交给 web_import_common 统一下载图片 & 写 project.json
    """
    html_text = fetch_html(url)
    soup = BeautifulSoup(html_text, "html.parser")

    # 标题：优先 activity-name，其次 <h1>
    title_el = soup.find(id="activity-name") or soup.find("h1")
    if title_el and title_el.get_text(strip=True):
        raw_title = title_el.get_text(strip=True)
    else:
        raw_title = "未命名微信项目"

    meta = _parse_meta(soup, url, raw_title)
    image_urls, title_map = _parse_images(soup, url)

    # 供 download_images 用于命名文件
    meta["image_title_map"] = title_map

    return ParsedProject(
        site=SITE_KEY,
        url=url,
        title=raw_title,
        suggested_folder=slugify(raw_title),
        meta=meta,
        image_urls=image_urls,
    )
