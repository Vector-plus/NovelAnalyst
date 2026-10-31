"""SpaceManager —— 小说空间管理 + 原文 CRUD（纯后端，无 LLM 参与）。

组合 :class:`SpaceStore`（元数据）与文件系统（沙箱目录、原文文件）。

关键设计：
- **建空间原子性**：先建沙箱目录，再写元数据；元数据写失败则回滚删目录。
- **原文存放约定**：原文放 ``novel_root/source/`` 下，**唯一一个文件**（文件名见 ``SOURCE_FILE``），
  统一以 UTF-8 落盘；上传时自动探测原始编码（UTF-8 / GBK / GB18030 / Big5 等）。
"""

from __future__ import annotations

import codecs
import shutil
from pathlib import Path

from deerflow_simple.config import SimpleConfig
from deerflow_simple.spaces.models import NovelSpace, now_iso
from deerflow_simple.spaces.paths import resolve_novel_path, resolve_novel_result_path
from deerflow_simple.spaces.store import SpaceStore

# 原文存放约定：novel_root/source/ 下，唯一一个文件（文件名固定为 SOURCE_FILE）。
SOURCE_DIR = "source"
SOURCE_FILE = "novel.txt"


def _decode_bytes(data: bytes) -> tuple[str, str]:
    """探测字节流编码并解码为 str，返回 ``(text, encoding)``。

    小说原文可能混用 GBK / GB18030 / Big5 等中文编码，上传时需探测后统一转 UTF-8。
    探测顺序：
    1. UTF-8 BOM → utf-8-sig；
    2. UTF-8 严格解码成功 → utf-8；
    3. charset_normalizer 探测（best，能识别 GBK / GB18030 / Big5 等）；
    4. 兜底 gb18030（GBK 超集，errors=replace，几乎不会失败）。
    """
    if not data:
        return "", "utf-8"

    if data.startswith(codecs.BOM_UTF8):
        return data.decode("utf-8-sig"), "utf-8-sig"

    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass

    try:
        import charset_normalizer
    except ImportError:
        charset_normalizer = None

    if charset_normalizer is not None:
        match = charset_normalizer.from_bytes(data).best()
        if match is not None:
            return str(match), match.encoding or "unknown"

    # 兜底：GB18030 是 GBK 的超集，能覆盖绝大多数中文编码
    return data.decode("gb18030", errors="replace"), "gb18030"


class SpaceNotFoundError(Exception):
    """小说空间不存在。"""


class SpaceManager:
    def __init__(self, config: SimpleConfig, store: SpaceStore):
        self._config = config
        self._store = store

    # ------------------------------------------------------------------
    # 空间 CRUD
    # ------------------------------------------------------------------
    def _root_of(self, space_id: str) -> Path:
        """空间 id → 沙箱目录（防穿越，不校验存在性）。"""
        return resolve_novel_path(self._config, space_id)

    def create_space(
        self, name: str, description: str = "", author: str = ""
    ) -> NovelSpace:
        """创建小说空间：先建沙箱目录 + source 子目录，再写元数据。

        若元数据写失败，回滚删除已建目录，避免「有目录无元数据」的脏状态。
        """
        space = NovelSpace(name=name, description=description, author=author)
        root = self._root_of(space.id)
        (root / SOURCE_DIR).mkdir(parents=True, exist_ok=False)
        try:
            return self._store.insert(space)
        except Exception:
            shutil.rmtree(root, ignore_errors=True)
            raise

    def get_space(self, space_id: str) -> NovelSpace:
        space = self._store.get(space_id)
        if space is None:
            raise SpaceNotFoundError(f"空间不存在: {space_id}")
        return space

    def list_spaces(self) -> list[NovelSpace]:
        return self._store.list()

    def update_space(
        self,
        space_id: str,
        name: str | None = None,
        description: str | None = None,
        author: str | None = None,
    ) -> NovelSpace:
        space = self.get_space(space_id)
        if name is not None:
            space.name = name
        if description is not None:
            space.description = description
        if author is not None:
            space.author = author
        space.updated_at = now_iso()
        return self._store.update(space)

    def delete_space(self, space_id: str) -> None:
        """删除空间：先删元数据，再删沙箱目录（含原文与索引）。"""
        space = self.get_space(space_id)
        root = self._root_of(space_id)
        self._store.delete(space.id)
        if root.exists():
            shutil.rmtree(root, ignore_errors=True)

    # ------------------------------------------------------------------
    # 原文 CRUD（novel_root/source/ 下，唯一一个文件，无 path 参数）
    # ------------------------------------------------------------------
    def _source_file_of(self, space_id: str) -> Path:
        """返回原文唯一文件的绝对路径（source/SOURCE_FILE）。"""
        self.get_space(space_id)  # 空间必须存在
        return self._root_of(space_id) / SOURCE_DIR / SOURCE_FILE

    def read_source(self, space_id: str) -> str:
        """读取原文（source/ 下唯一文件），不存在抛 FileNotFoundError。"""
        p = self._source_file_of(space_id)
        if not p.is_file():
            raise FileNotFoundError(f"原文文件不存在: {SOURCE_FILE}")
        return p.read_text(encoding="utf-8", errors="replace")

    def write_source(self, space_id: str, content: str) -> str:
        """以 UTF-8 创建或覆盖原文文件，返回相对沙箱根目录的路径（source/SOURCE_FILE）。"""
        p = self._source_file_of(space_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return p.relative_to(self._root_of(space_id)).as_posix()

    def write_source_bytes(self, space_id: str, data: bytes) -> dict:
        """探测编码、解码后以 UTF-8 落盘，返回 ``{path, size, encoding}``。

        ``encoding`` 为探测到的原始编码（utf-8 / gb18030 / big5 等），供排查。
        """
        text, encoding = _decode_bytes(data)
        p = self._source_file_of(space_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return {
            "path": p.relative_to(self._root_of(space_id)).as_posix(),
            "size": len(text),
            "encoding": encoding,
        }

    def delete_source(self, space_id: str) -> None:
        """删除原文文件，不存在抛 FileNotFoundError。"""
        p = self._source_file_of(space_id)
        if not p.is_file():
            raise FileNotFoundError(f"原文文件不存在: {SOURCE_FILE}")
        p.unlink()

    # ------------------------------------------------------------------
    # 解说词结果 CRUD（novel_root/result/ 下，多个文件，需 filename 定位）
    # ------------------------------------------------------------------
    def _result_dir_of(self, space_id: str) -> Path:
        """返回 result 目录绝对路径（防穿越，不校验目录存在性）。"""
        self.get_space(space_id)  # 空间必须存在
        return resolve_novel_result_path(self._config, space_id)

    def _result_file_of(self, space_id: str, filename: str) -> Path:
        """校验 filename 是合法 basename 并返回结果文件绝对路径（防穿越）。

        与 source（唯一固定文件名、无 path 参数）不同，result 是多文件，filename
        由用户输入，因此必须做防穿越：拒绝路径分隔符（``/``、``\\``）与相对路径符号
        （``.``、``..``），且 resolve 后必须仍位于 result 目录内。

        Raises:
            ValueError: filename 非法（含分隔符 / 相对符号 / 路径越界）。
        """
        if not filename or "/" in filename or "\\" in filename:
            raise ValueError(f"非法文件名: {filename!r}")
        if filename in (".", ".."):
            raise ValueError(f"非法文件名: {filename!r}")
        result_dir = self._result_dir_of(space_id)
        p = (result_dir / filename).resolve()
        if not p.is_relative_to(result_dir.resolve()):
            raise ValueError(f"非法文件名（路径越界）: {filename!r}")
        return p

    def list_results(self, space_id: str) -> list[str]:
        """列出 result 目录下所有文件名（按名称排序，仅文件）。目录不存在返回空列表。"""
        result_dir = self._result_dir_of(space_id)
        if not result_dir.is_dir():
            return []
        return sorted(p.name for p in result_dir.iterdir() if p.is_file())

    def read_result(self, space_id: str, filename: str) -> str:
        """读取单个结果文件（UTF-8），不存在抛 FileNotFoundError。"""
        p = self._result_file_of(space_id, filename)
        if not p.is_file():
            raise FileNotFoundError(f"结果文件不存在: {filename}")
        return p.read_text(encoding="utf-8", errors="replace")

    def write_result(self, space_id: str, filename: str, content: str) -> str:
        """以 UTF-8 创建或覆盖结果文件，返回相对沙箱根目录的路径（result/{filename}）。"""
        p = self._result_file_of(space_id, filename)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return p.relative_to(self._root_of(space_id)).as_posix()

    def delete_result(self, space_id: str, filename: str) -> None:
        """删除单个结果文件，不存在抛 FileNotFoundError。"""
        p = self._result_file_of(space_id, filename)
        if not p.is_file():
            raise FileNotFoundError(f"结果文件不存在: {filename}")
        p.unlink()
