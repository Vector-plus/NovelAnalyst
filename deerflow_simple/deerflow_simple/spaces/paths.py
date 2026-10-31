"""小说空间路径解析 —— novel_id → 沙箱目录的确定性映射（单一来源）。

一本小说对应一个沙箱目录：``config.workspace_path / novel_id``，
例如 ``.deerflow_simple/workspace/asdafd454da6df/``。

本模块是 id→路径映射的**唯一来源**：narration（解说词只读消费）与 spaces
（小说空间管理）都从这里解析，避免两处规则漂移。
"""

from __future__ import annotations

from pathlib import Path

from deerflow_simple.config import SimpleConfig

# 索引树根目录名（与 novel-index-creator 的约定一致：索引数据根目录默认 novel/，
# manifest.json 与各主题索引都位于 novel/ 下，Ref.path 相对 novel/）。
INDEX_DIR = "novel"

# 解说词结果目录名：生成完成的解说词稿件落盘在 space_root/result/ 下。
# 注意这是「产出物」，挂在 space root（不是 index root）下——index root 是索引的
# 只读消费区，result 是解说词的写入区，二者语义不同、不可混用。
RESULT_DIR = "result"

def resolve_novel_path(config: SimpleConfig, novel_id: str) -> Path:
    """novel_id → 沙箱目录绝对路径（防路径穿越，不校验存在性）。

    这是「小说空间根」（space root）：``config.workspace_path / novel_id``，
    例如 ``.deerflow_simple/workspace/asdafd454da6df/``。spaces 模块的原文
    ``source/novel.txt`` 就存放在这里。

    护栏（纯代码、零 token）：
    - **防路径穿越**：``novel_id`` 解析后必须仍位于 workspace 内（拒绝 ``../`` 等）。
    - 不做存在性校验：建空间时目录尚不存在；需要存在性校验的调用方自行判断。

    Raises:
        ValueError: novel_id 非法（路径越界）。
    """
    workspace = config.workspace_path.resolve()
    root = (workspace / novel_id).resolve()
    if not root.is_relative_to(workspace):
        raise ValueError(f"novel_id 非法（路径越界）: {novel_id}")
    return root

def resolve_novel_index_path(config: SimpleConfig, novel_id: str) -> Path:
    """novel_id → 索引树根目录（space_root/novel），防路径穿越，不校验存在性。

    「索引树根」（index root）与「小说空间根」（space root）是**两层**：
    - space root = ``workspace / novel_id``（存原文 source/novel.txt）
    - index root = ``workspace / novel_id / novel``（存 manifest.json 与各主题索引）

    narration 解说词只读消费、以及未来的 build_novel_index 写工作流，锚定的都是
    **index root**，不是 space root。二者不可混用，否则工具找不到 manifest.json。
    """
    space_root = resolve_novel_path(config, novel_id)
    return space_root / INDEX_DIR


def resolve_novel_result_path(config: SimpleConfig, novel_id: str) -> Path:
    """novel_id → 解说词结果目录（space_root/result），防路径穿越，不校验存在性。

    这是解说词**产出物**的落盘目录，挂在「小说空间根」（space root）下：
    ``workspace / novel_id / result``。与 index root（``workspace / novel_id / novel``）
    是**两个不同语义**的目录：
    - index root：索引的只读消费区（narration 检索工具读这里）。
    - result：解说词的写入区（generate_narration 成功后写这里）。

    复用 ``resolve_novel_path`` 做防路径穿越；目录不存在时由写入方自行 mkdir。
    """
    space_root = resolve_novel_path(config, novel_id)
    return space_root / RESULT_DIR
