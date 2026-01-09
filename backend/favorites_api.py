# favorites_api.py
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import SessionLocal
from favorites_models import Collection, CollectionItem
from user_identity import get_user_key
import models  # 用到 Project


router = APIRouter(prefix="/api/collections", tags=["collections"])


# ========== 依赖：数据库 Session ==========


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ========== Pydantic 模型 ==========


class ProjectMini(BaseModel):
    id: int
    name: str
    folder_path: str
    cover_rel_path: Optional[str] = None
    architect: Optional[str] = None

    class Config:
        orm_mode = True


class CollectionSummary(BaseModel):
    id: int
    name: str
    visibility: str  # 'public' / 'private'
    description: Optional[str] = None
    owner_is_me: bool
    item_count: int

    class Config:
        orm_mode = True


class CollectionDetail(CollectionSummary):
    items: List[ProjectMini] = []


class CollectionCreate(BaseModel):
    name: str
    visibility: str  # 'public' / 'private'
    description: Optional[str] = None


class CollectionUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    visibility: Optional[str] = None  # 'public' / 'private'



class CollectionItemCreate(BaseModel):
    project_id: int


class CollectionsOfProjectResponse(BaseModel):
    private: List[CollectionSummary]
    public: List[CollectionSummary]


# ========== 工具函数 ==========


def _normalize_visibility(visibility: str) -> str:
    v = (visibility or "").strip().lower()
    if v not in ("public", "private"):
        raise HTTPException(status_code=400, detail="visibility must be 'public' or 'private'")
    return v


def _collection_to_summary(
    c: Collection,
    current_user_key: str,
) -> CollectionSummary:
    return CollectionSummary(
        id=c.id,
        name=c.name,
        visibility=c.visibility,
        description=c.description,
        owner_is_me=(c.owner_key == current_user_key),
        item_count=len(c.items),
    )


def _project_to_mini(p: models.Project) -> ProjectMini:
    return ProjectMini(
        id=p.id,
        name=p.name,
        folder_path=p.folder_path,
        cover_rel_path=p.cover_rel_path,
        architect=p.architect,
    )


# ========== API：获取所有收藏夹（供收藏夹模式 banner 使用） ==========


@router.get("/all", response_model=List[CollectionSummary])
def list_all_collections(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    返回当前系统中的所有收藏夹列表，供“收藏夹模式”右上角星星入口使用。

    排序规则（从前到后）：
    1. 当前用户的 private 收藏夹
    2. 当前用户的 public 收藏夹
    3. 其他用户的 public 收藏夹
    4. 其他用户的 private（理论上不会出现，但防御性处理）
    """
    user_key = get_user_key(request)

    q = db.query(Collection).order_by(Collection.created_at.desc())
    all_cols: List[Collection] = q.all()

    my_private: List[Collection] = []
    my_public: List[Collection] = []
    other_public: List[Collection] = []
    other_private: List[Collection] = []

    for c in all_cols:
        if c.visibility == "private":
            if c.owner_key == user_key:
                my_private.append(c)
            else:
                other_private.append(c)
        else:  # 'public'
            if c.owner_key == user_key:
                my_public.append(c)
            else:
                other_public.append(c)

    ordered = my_private + my_public + other_public + other_private
    return [_collection_to_summary(c, user_key) for c in ordered]


# ========== API：列表收藏夹 ==========


@router.get("", response_model=List[CollectionSummary])
def list_collections(
    request: Request,
    visibility: str = Query(..., description="'public' 或 'private'"),
    mine: Optional[bool] = Query(
        None,
        description="仅对 public 有意义：mine=true 只看自己创建的公共收藏夹；false 或不传则看全部",
    ),
    db: Session = Depends(get_db),
):
    """
    获取收藏夹列表：
    - visibility = 'private'：只返回当前用户自己的私人收藏夹；
    - visibility = 'public'：
        - mine = true：只看自己创建的公共收藏夹；
        - mine = false / None：查看所有公共收藏夹。
    """
    user_key = get_user_key(request)
    visibility = _normalize_visibility(visibility)

    q = db.query(Collection).filter(Collection.visibility == visibility)

    if visibility == "private":
        # 私人收藏夹只能看到自己的
        q = q.filter(Collection.owner_key == user_key)
    else:
        # public
        if mine is True:
            q = q.filter(Collection.owner_key == user_key)
        # mine 为 False 或 None 时，不加 owner_key 过滤，查看全部公共夹

    q = q.order_by(Collection.created_at.desc())

    collections = q.all()
    return [_collection_to_summary(c, user_key) for c in collections]


# ========== API：获取收藏夹详情（含项目） ==========


@router.get("/{collection_id}", response_model=CollectionDetail)
def get_collection_detail(
    collection_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user_key = get_user_key(request)

    c: Optional[Collection] = db.query(Collection).filter(Collection.id == collection_id).first()
    if c is None:
        raise HTTPException(status_code=404, detail="Collection not found")

    # 私人收藏夹只能自己查看
    if c.visibility == "private" and c.owner_key != user_key:
        raise HTTPException(status_code=403, detail="Not allowed to view this collection")

    # items + 对应项目
    project_minis: List[ProjectMini] = []
    for item in c.items:
        if item.project is not None:
            project_minis.append(_project_to_mini(item.project))

    summary = _collection_to_summary(c, user_key)
    return CollectionDetail(
        **summary.dict(),
        items=project_minis,
    )


# ========== API：新建收藏夹 ==========


@router.post("", response_model=CollectionSummary)
def create_collection(
    payload: CollectionCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    user_key = get_user_key(request)
    visibility = _normalize_visibility(payload.visibility)

    c = Collection(
        name=payload.name.strip(),
        visibility=visibility,
        owner_key=user_key,
        description=(payload.description or "").strip() or None,
    )

    db.add(c)
    db.commit()
    db.refresh(c)

    # 新建时还没有 items
    return _collection_to_summary(c, user_key)


# ========== API：修改收藏夹（改名 / 描述） ==========

@router.patch("/{collection_id}", response_model=CollectionSummary)
def update_collection(
    collection_id: int,
    payload: CollectionUpdate,
    request: Request,
    db: Session = Depends(get_db),
):
    user_key = get_user_key(request)

    c: Optional[Collection] = (
        db.query(Collection).filter(Collection.id == collection_id).first()
    )
    if c is None:
        raise HTTPException(status_code=404, detail="Collection not found")

    # 只有创建者可以修改收藏夹信息
    if c.owner_key != user_key:
        raise HTTPException(
            status_code=403, detail="Not allowed to modify this collection"
        )

    if payload.name is not None:
        c.name = payload.name.strip()
    if payload.description is not None:
        desc = payload.description.strip()
        c.description = desc or None

    # ★ 新增：切换私密 / 公开
    if payload.visibility is not None:
        c.visibility = _normalize_visibility(payload.visibility)

    db.commit()
    db.refresh(c)

    return _collection_to_summary(c, user_key)

# ========== API：删除收藏夹 ==========


@router.delete("/{collection_id}")
def delete_collection(
    collection_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user_key = get_user_key(request)

    c: Optional[Collection] = db.query(Collection).filter(Collection.id == collection_id).first()
    if c is None:
        raise HTTPException(status_code=404, detail="Collection not found")

    # 只有创建者可以删除收藏夹（无论 public / private）
    if c.owner_key != user_key:
        raise HTTPException(status_code=403, detail="Not allowed to delete this collection")

    db.delete(c)
    db.commit()

    return {"status": "deleted", "id": collection_id}


# ========== API：往收藏夹里添加项目（Pinterest 点一次保存） ==========


@router.post("/{collection_id}/items")
def add_project_to_collection(
    collection_id: int,
    payload: CollectionItemCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    user_key = get_user_key(request)

    c: Optional[Collection] = db.query(Collection).filter(Collection.id == collection_id).first()
    if c is None:
        raise HTTPException(status_code=404, detail="Collection not found")

    # 私人收藏夹：只能自己往里加
    if c.visibility == "private" and c.owner_key != user_key:
        raise HTTPException(status_code=403, detail="Not allowed to modify this private collection")

    # 公共收藏夹：任何人都可以往里加（按我们之前的约定）

    # 检查项目是否存在
    project: Optional[models.Project] = (
        db.query(models.Project).filter(models.Project.id == payload.project_id).first()
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    # 检查是否已经存在这一条
    existing = (
        db.query(CollectionItem)
        .filter(
            CollectionItem.collection_id == c.id,
            CollectionItem.project_id == project.id,
        )
        .first()
    )
    if existing is not None:
        return {"status": "exists", "collection_id": c.id, "project_id": project.id}

    item = CollectionItem(
        collection_id=c.id,
        project_id=project.id,
    )
    db.add(item)
    db.commit()

    return {"status": "added", "collection_id": c.id, "project_id": project.id}


# ========== API：从收藏夹中移除项目 ==========


@router.delete("/{collection_id}/items/{project_id}")
def remove_project_from_collection(
    collection_id: int,
    project_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user_key = get_user_key(request)

    c: Optional[Collection] = db.query(Collection).filter(Collection.id == collection_id).first()
    if c is None:
        raise HTTPException(status_code=404, detail="Collection not found")

    # 删除项目：无论 public / private，都只允许收藏夹创建者做（避免别人乱删）
    if c.owner_key != user_key:
        raise HTTPException(status_code=403, detail="Not allowed to modify this collection")

    item: Optional[CollectionItem] = (
        db.query(CollectionItem)
        .filter(
            CollectionItem.collection_id == c.id,
            CollectionItem.project_id == project_id,
        )
        .first()
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found in this collection")

    db.delete(item)
    db.commit()

    return {"status": "removed", "collection_id": c.id, "project_id": project_id}


# ========== API：查询某个项目在哪些收藏夹里（供前端弹窗高亮） ==========


@router.get("/of_project/{project_id}", response_model=CollectionsOfProjectResponse)
def get_collections_of_project(
    project_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user_key = get_user_key(request)

    # 项目是否存在（可选校验）
    project: Optional[models.Project] = (
        db.query(models.Project).filter(models.Project.id == project_id).first()
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    # 私人：只查当前用户自己的 private 收藏夹
    private_q = (
        db.query(Collection)
        .join(CollectionItem, CollectionItem.collection_id == Collection.id)
        .filter(
            Collection.visibility == "private",
            Collection.owner_key == user_key,
            CollectionItem.project_id == project_id,
        )
        .order_by(Collection.created_at.desc())
    )
    private_cols = private_q.all()

    # 公共：所有 public 收藏夹中包含该项目的
    public_q = (
        db.query(Collection)
        .join(CollectionItem, CollectionItem.collection_id == Collection.id)
        .filter(
            Collection.visibility == "public",
            CollectionItem.project_id == project_id,
        )
        .order_by(Collection.created_at.desc())
    )
    public_cols = public_q.all()

    private_summaries = [_collection_to_summary(c, user_key) for c in private_cols]
    public_summaries = [_collection_to_summary(c, user_key) for c in public_cols]

    return CollectionsOfProjectResponse(
        private=private_summaries,
        public=public_summaries,
    )
