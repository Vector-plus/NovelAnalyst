"""小说空间 API 的请求 / 响应模型。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class SpaceCreateRequest(BaseModel):
    """创建小说空间的请求体。"""

    name: str = Field(..., min_length=1, max_length=200, description="小说名称")
    description: str = Field(default="", description="小说描述")
    author: str = Field(default="", description="作者")


class SpaceUpdateRequest(BaseModel):
    """更新小说空间元数据的请求体（仅更新传入的非 None 字段）。"""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    author: str | None = None


class SpaceResponse(BaseModel):
    """小说空间响应体。"""

    id: str
    name: str
    description: str = ""
    author: str = ""
    created_at: str
    updated_at: str


class ResultWriteRequest(BaseModel):
    """写入（创建或覆盖）单个解说词结果文件的请求体。

    解说词结果是自产的 UTF-8 Markdown，无需编码探测，故用 JSON body 而非
    multipart（与原文 source 的 ``UploadFile`` 上传不同）。
    """

    content: str = Field(..., description="结果文件完整内容（Markdown）")
