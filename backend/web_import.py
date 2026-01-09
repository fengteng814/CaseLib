# backend/web_import.py
import logging
import uuid
from pathlib import Path
from typing import Dict, Optional, List
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from config import PROJECTS_ROOT
from web_import_common import (
    ParsedProject,
    safe_folder_name,
    download_images,
    write_project_json,
)
import web_import_sites

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/web-import", tags=["web-import"])


class ParseRequest(BaseModel):
    url: str


class StartImportRequest(BaseModel):
    url: str
    folder_name: str


class StartImportResponse(BaseModel):
    task_id: str
    message: str


class TaskStatus(BaseModel):
    status: Literal["pending", "running", "done", "error"]
    progress: float = 0.0
    message: str = ""
    project_name: Optional[str] = None
    folder_path: Optional[str] = None


class StatusResponse(TaskStatus):
    task_id: str


class SiteInfo(BaseModel):
    id: str
    name: str


_tasks: Dict[str, TaskStatus] = {}


def _create_task(project_name: str, folder_path: str) -> str:
    task_id = uuid.uuid4().hex
    _tasks[task_id] = TaskStatus(
        status="pending",
        progress=0.0,
        message="任务已创建",
        project_name=project_name,
        folder_path=folder_path,
    )
    return task_id


def _update_task(
    task_id: str,
    status: Optional[str] = None,
    progress: Optional[float] = None,
    message: Optional[str] = None,
) -> None:
    task = _tasks.get(task_id)
    if not task:
        return
    data = task.dict()
    if status is not None:
        data["status"] = status
    if progress is not None:
        data["progress"] = float(progress)
    if message is not None:
        data["message"] = message
    _tasks[task_id] = TaskStatus(**data)


def _parse_url(url: str) -> ParsedProject:
    try:
        return web_import_sites.parse_url(url)
    except ValueError as e:
        # 不支持的网站
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("解析网页失败: %s", url)
        raise HTTPException(status_code=502, detail=f"解析网页失败: {e}")


def run_import_job(task_id: str, parsed: ParsedProject, folder_name: str) -> None:
    """
    后台导入主流程：下载图片 + 写 project.json。
    """
    try:
        folder_name_safe = safe_folder_name(folder_name or parsed.suggested_folder)
        dest_dir = PROJECTS_ROOT / folder_name_safe

        _update_task(
            task_id,
            status="running",
            progress=0.0,
            message="开始下载图片",
        )

        download_images(parsed, dest_dir, task_id, _update_task)
        write_project_json(parsed, dest_dir)

        _update_task(
            task_id,
            status="done",
            progress=1.0,
            message="导入完成（文件已写入本地，回到案例库刷新后可见）",
        )
    except Exception as e:
        logger.exception("导入任务失败: %s", e)
        _update_task(
            task_id,
            status="error",
            message=f"导入失败: {e}",
        )


# ========= 路由 =========


@router.get("/sites", response_model=List[SiteInfo])
def api_list_sites() -> List[SiteInfo]:
    """
    返回当前支持的网站列表，基于 web_import_sites 目录下的文件自动生成。
    """
    sites = web_import_sites.list_sites()
    return [SiteInfo(**s) for s in sites]


@router.post("/parse", response_model=ParsedProject)
def api_parse(req: ParseRequest) -> ParsedProject:
    """
    解析链接，不写文件，只返回标题 / 建议文件夹名 / 元信息 / 图片列表。
    前端可以用 meta + image_urls[0] 做预览。
    """
    return _parse_url(req.url)


@router.post("/start", response_model=StartImportResponse)
def api_start_import(
    req: StartImportRequest,
    background_tasks: BackgroundTasks,
) -> StartImportResponse:
    parsed = _parse_url(req.url)

    folder_name_safe = safe_folder_name(req.folder_name or parsed.suggested_folder)
    dest_dir = PROJECTS_ROOT / folder_name_safe

    # 如果目标文件夹已存在：
    # - 若只遗留了一个 project.json（可能是上次失败残留），自动删除重来；
    # - 否则直接报错，避免覆盖已有项目。
    if dest_dir.exists():
        children = list(dest_dir.iterdir())
        if children:
            if len(children) == 1 and children[0].name == "project.json":
                try:
                    children[0].unlink()
                except Exception:
                    pass
            else:
                raise HTTPException(
                    status_code=400,
                    detail="目标文件夹已存在且非空，请更换文件夹名或手动删除后再导入。",
                )

    task_id = _create_task(project_name=parsed.title, folder_path=str(dest_dir))

    background_tasks.add_task(run_import_job, task_id, parsed, folder_name_safe)

    return StartImportResponse(
        task_id=task_id,
        message="导入任务已启动，将在后台运行。",
    )


@router.get("/status/{task_id}", response_model=StatusResponse)
def api_get_status(task_id: str) -> StatusResponse:
    task = _tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="未找到该任务")
    return StatusResponse(task_id=task_id, **task.dict())
