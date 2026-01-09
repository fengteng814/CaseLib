# favorites_models.py
from datetime import datetime

from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    ForeignKey,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from database import Base
import models  # 只为了解决 relationship 中 "Project" 的引用，不会改动它


class Collection(Base):
    """
    收藏夹（既包含公共收藏夹，也包含私人收藏夹）
    visibility: 'public' / 'private'
    owner_key: 用来存“用户标识”（这里先用 IP，后面也可以无痛换成用户 ID）
    """
    __tablename__ = "collections"

    id = Column(Integer, primary_key=True, index=True)

    # 收藏夹名称
    name = Column(String(255), nullable=False)

    # 可见性：'public'（公共收藏夹） / 'private'（私人收藏夹）
    visibility = Column(String(20), nullable=False, index=True)

    # 拥有者标识（当前阶段用 IP，当作 pseudo user）
    owner_key = Column(String(64), nullable=False, index=True)

    # 说明文字，可选
    description = Column(String(500), nullable=True)

    # 封面项目（可选，不填就用第一个项目当封面）
    cover_project_id = Column(
        Integer,
        ForeignKey("projects.id"),   # ⚠ 如果你的项目表不是 'projects'，这里改一下
        nullable=True,
    )

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    # 关系字段：封面项目
    cover_project = relationship("Project", foreign_keys=[cover_project_id])

    # 关系字段：收藏夹中的条目（项目列表）
    items = relationship(
        "CollectionItem",
        back_populates="collection",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Collection id={self.id} name={self.name!r} visibility={self.visibility}>"


class CollectionItem(Base):
    """
    收藏夹中的一条记录：某个收藏夹 + 某个项目
    """
    __tablename__ = "collection_items"

    id = Column(Integer, primary_key=True, index=True)

    collection_id = Column(
        Integer,
        ForeignKey("collections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    project_id = Column(
        Integer,
        ForeignKey("projects.id", ondelete="CASCADE"),  # ⚠ 同上，表名不一致要改
        nullable=False,
        index=True,
    )

    created_at = Column(DateTime, default=datetime.utcnow)

    # 反向关系：所属收藏夹
    collection = relationship("Collection", back_populates="items")

    # 关联项目（只读，为了方便直接拿项目信息）
    project = relationship("Project")

    __table_args__ = (
        # 同一个收藏夹里，同一个项目只能出现一次
        UniqueConstraint(
            "collection_id",
            "project_id",
            name="uq_collection_project",
        ),
    )

    def __repr__(self) -> str:
        return f"<CollectionItem cid={self.collection_id} pid={self.project_id}>"
