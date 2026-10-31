"""Fingerprint —— SHA-256 指纹计算（对齐 templates §11.5 序列化规范）。

指纹是 ledger 四态 CAS（expected_sha256 / result_sha256）与 audit
check_sha256_match 的基础。任何参与幂等比对的落盘文件都必须用同一规范
序列化，否则指纹对不上。

序列化规范（与 skeleton.py::_json_dumps 完全一致）：
- JSON：UTF-8、两空格缩进、LF、末尾一个 LF；对象键递归按 Unicode 码点
  排序（``sort_keys=True``）；数组保持语义顺序。
- Markdown：统一 LF 与一个末尾 LF。

对应 03 文档 §5.9 的 Fingerprint service。本模块不引入文件锁（deepread 单协程
串行），CAS 的乐观锁语义由 LedgerService / IndexWriter 在调用侧实现。
"""

from __future__ import annotations

import hashlib
import json


def sha256_bytes(data: bytes) -> str:
    """返回字节的 SHA-256 十六进制摘要。"""
    return hashlib.sha256(data).hexdigest()


def json_bytes(obj: dict | list) -> bytes:
    """按规范序列化 JSON 对象为字节（写盘与指纹计算共用同一份字节）。"""
    return (
        json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
        + b"\n"
    )


def json_sha256(obj: dict | list) -> str:
    """计算 JSON 对象的规范指纹。"""
    return sha256_bytes(json_bytes(obj))


def markdown_bytes(text: str) -> bytes:
    """按规范规范化 Markdown 文本为字节（LF + 末尾一个 LF）。"""
    normalized = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.endswith("\n"):
        normalized += "\n"
    return normalized.encode("utf-8")


def markdown_sha256(text: str) -> str:
    """计算 Markdown 文本的规范指纹。"""
    return sha256_bytes(markdown_bytes(text))
