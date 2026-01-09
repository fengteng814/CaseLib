# backend/web_import_sites/__init__.py
import importlib
import logging
import pkgutil
from typing import Dict, List, Any, Optional

from web_import_common import ParsedProject

logger = logging.getLogger(__name__)


class SiteParser:
    def __init__(self, key: str, name: str, module: Any):
        self.key = key
        self.name = name
        self.module = module

    def parse(self, url: str) -> ParsedProject:
        return self.module.parse(url)


# key -> SiteParser
SITE_REGISTRY: Dict[str, SiteParser] = {}

# 自动扫描当前包下的所有站点文件
for info in pkgutil.iter_modules(__path__):
    if info.name.startswith("_"):
        continue
    module_name = f"{__name__}.{info.name}"
    try:
        module = importlib.import_module(module_name)
    except Exception as e:
        logger.warning("导入站点解析模块失败: %s (%s)", module_name, e)
        continue

    key = getattr(module, "SITE_KEY", info.name)
    name = getattr(module, "SITE_NAME", key)
    parse_func = getattr(module, "parse", None)
    if not callable(parse_func):
        logger.warning("站点模块 %s 缺少 parse(url) 函数，已忽略", module_name)
        continue

    SITE_REGISTRY[key] = SiteParser(key, name, module)

logger.info("已加载 web_import 站点解析器: %s", ", ".join(SITE_REGISTRY.keys()))


def list_sites() -> List[dict]:
    """
    返回 [{id, name}, ...]，供前端展示“当前支持的网站”。
    """
    return [
        {"id": key, "name": parser.name}
        for key, parser in SITE_REGISTRY.items()
    ]


def detect_site_for_url(url: str) -> Optional[str]:
    """
    根据 URL 匹配属于哪个站点（看 MATCH_DOMAINS）。
    """
    lower = (url or "").lower()
    for key, parser in SITE_REGISTRY.items():
        domains = getattr(parser.module, "MATCH_DOMAINS", [])
        for d in domains:
            if d and d.lower() in lower:
                return key
    return None


def parse_url(url: str) -> ParsedProject:
    site_key = detect_site_for_url(url)
    if not site_key:
        raise ValueError("该链接不属于当前支持的网站")
    parser = SITE_REGISTRY[site_key]
    return parser.parse(url)
