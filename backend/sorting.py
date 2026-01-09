"""
项目列表排序相关辅助函数。

- 统一管理 sort 关键字（heat / recent / updated / name / location / architect）
- 对 SQLAlchemy 查询对象附加对应的 order_by / join / group_by
"""

from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Query

import models


def normalize_sort_key(sort: str) -> str:
    """
    把各种别名规整到内部统一的几个 key 上。
    """
    if not sort:
        return "heat"

    s = sort.lower().strip()

    if s in ("heat", "heat_total", "hot"):
        return "heat"

    if s in ("updated", "updated_at", "update_time", "time"):
        return "updated"

    if s in ("recent", "recent_heat", "heat_recent", "heat_7d"):
        return "recent"

    if s in ("name", "title"):
        return "name"

    if s in ("location", "loc", "place"):
        return "location"

    if s in ("architect", "arch"):
        return "architect"

    # 默认回落到总热度
    return "heat"


def apply_project_sort(query: Query, sort: str) -> Query:
    """
    根据 sort 关键字对 Project 列表查询添加排序规则。

    约定：
    - 传入的 query 初始为 db.query(models.Project)
    - 返回的依旧是 Project 实体查询
    """

    key = normalize_sort_key(sort)

    # 2. 按更新时间（越新越靠前）
    if key == "updated":
        return query.order_by(
            models.Project.updated_at.desc(),
            models.Project.id.desc(),
        )

    # 3. 按近期热度：最近 7 天点击次数多的在前
    if key == "recent":
        since = datetime.utcnow() - timedelta(days=7)
        return (
            query.outerjoin(
                models.ProjectClick,
                (models.ProjectClick.project_id == models.Project.id)
                & (models.ProjectClick.clicked_at >= since),
            )
            .group_by(models.Project.id)
            .order_by(
                func.count(models.ProjectClick.id).desc(),
                models.Project.name.asc(),
            )
        )

    # 4. 按项目名称（首字母）
    if key == "name":
        return query.order_by(
            models.Project.name.asc(),
            models.Project.id.asc(),
        )

    # 5. 按地点（首字母）
    if key == "location":
        return query.order_by(
            models.Project.location.asc(),
            models.Project.name.asc(),
        )

    # 6. 按建筑师（首字母）
    if key == "architect":
        return query.order_by(
            models.Project.architect.asc(),
            models.Project.name.asc(),
        )

    # 1. 默认：按总热度
    return query.order_by(
        models.Project.heat.desc(),
        models.Project.name.asc(),
    )
