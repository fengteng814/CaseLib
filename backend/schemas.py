from typing import Optional, List
from pydantic import BaseModel, ConfigDict


class ProjectOut(BaseModel):
    # Pydantic v2：启用 ORM 模式（从 SQLAlchemy 对象读取属性）
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    folder_path: str
    description: Optional[str] = None

    # 封面图片 URL（缩略图，可能为 None），形如 /thumbs/xxx/yyy.jpg
    cover_url: Optional[str] = None

    architect: Optional[str] = None
    location: Optional[str] = None
    category: Optional[str] = None
    year: Optional[int] = None
    display_order: Optional[int] = None

    tags: List[str] = []

    # 用于“复制项目路径”的 Windows UNC 路径
    # 例如：\\10.0.96.80\ALXGNew01\A04资源\...\体育建筑\某项目
    fs_path: Optional[str] = None


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    architect: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    category: Optional[str] = None
    year: Optional[int] = None
    display_order: Optional[int] = None

    # 自由标签输入（空格 / 逗号分隔，后端会解析），为空字符串表示清空标签
    tags_text: Optional[str] = None

class ProjectCoverUpdate(BaseModel):
    """
    手动设封面时的请求体：
    - file_rel_path 为相对 MEDIA_ROOT 的图片路径
      例如："体育建筑/某项目/图片/01.jpg"
    """
    file_rel_path: str


class ImageOut(BaseModel):
    id: int
    project_id: int
    project_name: str

    # 原图 URL，用于放大查看
    url: str

    # 缩略图 URL（用于列表 / 网格展示），例如 /thumbs/xxx/yyy.jpg
    thumb_url: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)
