"""小说空间 + 原文 CRUD 的 HTTP API（纯后端，无 LLM 参与）。

对应产品化的两个纯后端能力：
- 小说空间列表 / 创建 / 查询 / 更新 / 删除；
- 空间内原文的增（PUT 幂等创建）/ 删 / 改 / 查。

原文统一存放在 ``novel_root/source/`` 下，唯一一个文件（文件名见 ``SOURCE_FILE``），
接口无 ``path`` 参数；上传走 ``multipart/form-data``（``UploadFile``），后端自动探测
编码（UTF-8 / GBK / GB18030 / Big5 等）并统一转 UTF-8 落盘。
"""

from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, Request, UploadFile

from deerflow_simple.spaces.manager import (
    SpaceManager,
    SpaceNotFoundError,
)
from deerflow_simple.spaces.models import NovelSpace
from deerflow_simple.spaces.schemas import (
    ResultWriteRequest,
    SpaceCreateRequest,
    SpaceResponse,
    SpaceUpdateRequest,
)

router = APIRouter(prefix="/api/spaces", tags=["spaces"])


def _get_manager(request: Request) -> SpaceManager:
    return request.app.state.space_manager


def _to_response(space: NovelSpace) -> SpaceResponse:
    return SpaceResponse(
        id=space.id,
        name=space.name,
        description=space.description,
        author=space.author,
        created_at=space.created_at,
        updated_at=space.updated_at,
    )


# ---------------------------------------------------------------------------
# 小说空间
# ---------------------------------------------------------------------------

@router.post("", response_model=SpaceResponse, status_code=201)
async def create_space(body: SpaceCreateRequest, request: Request) -> SpaceResponse:
    """创建小说空间（后端为该小说生成唯一 id，并创建沙箱环境）。"""
    manager = _get_manager(request)
    space = manager.create_space(body.name, body.description, body.author)
    return _to_response(space)


@router.get("", response_model=list[SpaceResponse])
async def list_spaces(request: Request) -> list[SpaceResponse]:
    """列出全部小说空间。"""
    manager = _get_manager(request)
    return [_to_response(s) for s in manager.list_spaces()]


@router.get("/{space_id}", response_model=SpaceResponse)
async def get_space(space_id: str, request: Request) -> SpaceResponse:
    """查询单个小说空间详情。"""
    manager = _get_manager(request)
    try:
        return _to_response(manager.get_space(space_id))
    except SpaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/{space_id}", response_model=SpaceResponse)
async def update_space(
    space_id: str, body: SpaceUpdateRequest, request: Request
) -> SpaceResponse:
    """更新小说空间元数据（仅更新传入的非 None 字段）。"""
    manager = _get_manager(request)
    try:
        space = manager.update_space(
            space_id,
            name=body.name,
            description=body.description,
            author=body.author,
        )
    except SpaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _to_response(space)


@router.delete("/{space_id}", status_code=204)
async def delete_space(space_id: str, request: Request) -> None:
    """删除小说空间（连同沙箱目录）。"""
    manager = _get_manager(request)
    try:
        manager.delete_space(space_id)
    except SpaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# 原文 CRUD（novel_root/source/ 下，唯一一个文件，无 path 参数）
# ---------------------------------------------------------------------------

@router.get("/{space_id}/source", response_model=dict)
async def read_source(space_id: str, request: Request) -> dict:
    """读取原文内容。"""
    manager = _get_manager(request)
    try:
        content = manager.read_source(space_id)
    except SpaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"content": content}


@router.put("/{space_id}/source", response_model=dict)
async def write_source(
    space_id: str, request: Request, file: UploadFile = File(...)
) -> dict:
    """上传原文文件（multipart/form-data），后端探测编码并统一转 UTF-8 落盘。"""
    manager = _get_manager(request)
    data = await file.read()
    try:
        return manager.write_source_bytes(space_id, data)
    except SpaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{space_id}/source", status_code=204)
async def delete_source(space_id: str, request: Request) -> None:
    """删除原文文件。"""
    manager = _get_manager(request)
    try:
        manager.delete_source(space_id)
    except SpaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# 解说词结果 CRUD（novel_root/result/ 下，多个文件，需 filename 定位）
# ---------------------------------------------------------------------------

@router.get("/{space_id}/result", response_model=dict)
async def list_results(space_id: str, request: Request) -> dict:
    """列出 result 目录下所有结果文件名。"""
    manager = _get_manager(request)
    try:
        files = manager.list_results(space_id)
    except SpaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"files": files}


@router.get("/{space_id}/result/{filename}", response_model=dict)
async def read_result(space_id: str, filename: str, request: Request) -> dict:
    """读取单个结果文件内容（UTF-8 Markdown）。"""
    manager = _get_manager(request)
    try:
        content = manager.read_result(space_id, filename)
    except SpaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"filename": filename, "content": content}


@router.put("/{space_id}/result/{filename}", response_model=dict)
async def write_result(
    space_id: str, filename: str, body: ResultWriteRequest, request: Request
) -> dict:
    """写入（创建或覆盖）单个结果文件，返回相对沙箱根目录的路径。"""
    manager = _get_manager(request)
    try:
        path = manager.write_result(space_id, filename, body.content)
    except SpaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"path": path}


@router.delete("/{space_id}/result/{filename}", status_code=204)
async def delete_result(space_id: str, filename: str, request: Request) -> None:
    """删除单个结果文件。"""
    manager = _get_manager(request)
    try:
        manager.delete_result(space_id, filename)
    except SpaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
