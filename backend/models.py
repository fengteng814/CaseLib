from datetime import datetime

from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean, Table
from sqlalchemy.orm import relationship

from database import Base

# 关联表：项目 <-> 标签（多对多）
project_tags = Table(
    "project_tags",
    Base.metadata,
    Column("project_id", Integer, ForeignKey("projects.id"), primary_key=True),
    Column("tag_id", Integer, ForeignKey("tags.id"), primary_key=True),
)

class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)

    # 项目名称（默认用文件夹名，可以被 project.json / 后台编辑覆盖）
    name = Column(String, nullable=False)

    # 相对 media 根目录的文件夹路径，例如：
    #   "体育建筑/某项目"
    #   "文化建筑/子类/某项目"
    folder_path = Column(String, unique=True, index=True, nullable=False)

    # 项目简介
    description = Column(Text, nullable=True)

    # 建筑师 / 设计单位
    architect = Column(String, nullable=True)

    # 地点
    location = Column(String, nullable=True)

    # 项目类别（体育建筑、文化建筑等）
    category = Column(String, nullable=True)

    # 年份（竣工 / 设计年份）
    year = Column(Integer, nullable=True)

    # 显示排序（越大越靠前）
    display_order = Column(Integer, nullable=True)

    # 封面图相对路径（相对 media 根目录，通常就是某条 Image.file_rel_path）
    # 例如：
    #   "体育建筑/某项目/图片/01.jpg"
    cover_rel_path = Column(String, nullable=True)

    # 全站热度（被点击次数，越大越靠前）
    heat = Column(Integer, nullable=False, default=0, server_default="0", index=True)

    # 是否已经通过后台编辑过 meta（编辑之后置为 True，索引器不再覆盖）
    is_meta_locked = Column(Boolean, default=False, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    images = relationship(
        "Image",
        back_populates="project",
        cascade="all, delete-orphan",
    )

    # 点击记录（用于“近期热度”统计）
    clicks = relationship(
        "ProjectClick",
        back_populates="project",
        cascade="all, delete-orphan",
    )

    # 项目标签（自由标签，多对多）
    tags = relationship(
        "Tag",
        secondary="project_tags",
        back_populates="projects",
    )


class Image(Base):
    __tablename__ = "images"

    id = Column(Integer, primary_key=True, index=True)

    project_id = Column(
        Integer,
        ForeignKey("projects.id"),
        nullable=False,
        index=True,
    )

    # 纯文件名，例如 "xxx.jpg"
    file_name = Column(String, nullable=False)

    # 相对 media 根目录的路径，例如：
    #   "体育建筑/项目名/xxx.jpg"
    file_rel_path = Column(String, unique=True, nullable=False)

    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    tags = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    project = relationship("Project", back_populates="images")


class ProjectClick(Base):
    """
    项目点击记录，用于统计“近期热度”（例如最近 7 天点击次数）。
    """

    __tablename__ = "project_clicks"

    id = Column(Integer, primary_key=True, index=True)

    project_id = Column(
        Integer,
        ForeignKey("projects.id"),
        nullable=False,
        index=True,
    )

    clicked_at = Column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
        index=True,
    )

    project = relationship("Project", back_populates="clicks")


class SearchKeyword(Base):
    """
    全站搜索热词统计：
    - keyword：关键词（去重）
    - count：被记录的次数
    - last_used_at：最近一次被记录时间
    """

    __tablename__ = "search_keywords"

    id = Column(Integer, primary_key=True, index=True)
    keyword = Column(String, unique=True, index=True, nullable=False)
    count = Column(Integer, nullable=False, default=0, server_default="0", index=True)
    last_used_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

class Tag(Base):
    """
    项目标签（用于自由标记 / 搜索）。
    """
    __tablename__ = "tags"

    id = Column(Integer, primary_key=True, index=True)
    # 标签名统一存小写，避免重复
    name = Column(String, unique=True, nullable=False, index=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    projects = relationship(
        "Project",
        secondary="project_tags",
        back_populates="tags",
    )
