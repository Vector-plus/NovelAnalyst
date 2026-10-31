#!/usr/bin/env python3
"""将 _staging/deepread 下的精读提取结果重新归档到正式索引目录。

背景：IndexWriter 的 write_chapter / write_stage_commit 是增量落库（推进 ledger
高水位、向 events/block-*.json 追加），直接重放会重复分配 ID 并重复写入事件。
因此本脚本默认先「重置」deepread 阶段落盘的产物与 ledger 高水位，再按章节顺序
重放 chapters/*.json，最后重放 stages/*.commit.json。

用法：
    python scripts/archive_staging.py                     # 重置 + 重新归档
    python scripts/archive_staging.py --no-reset          # 仅重放（不清理旧产物）
    python scripts/archive_staging.py --novel-root PATH
"""

import argparse
import glob
import json
import os
import shutil
import sys

from index_writer import IndexWriter

# 确保中文日志在非 UTF-8 终端下也能正常输出
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

NOVEL_ROOT = os.getenv(
    'DEEPREAD_NOVEL_ROOT',
    '/Users/wickfu/code/cls-ai/deer-flow/xianni_test/work_test/novel',
)
STAGING_DIR = os.getenv('DEEPREAD_STAGING_DIR', '_staging/deepread')

# deepread 阶段落盘的根索引（重置时清空 entries，保留骨架字段）
ROOT_INDEXES = [
    'events/index.json',
    'characters/index.json',
    'plot/index.json',
    'relationships/index.json',
    'settings/index.json',
    'threads/index.json',
    'emotions/index.json',
    'factions/index.json',
]


def _load(root: str, rel: str):
    full = os.path.join(root, rel)
    if not os.path.isfile(full):
        return None
    with open(full, encoding='utf-8') as f:
        return json.load(f)


def _write(root: str, rel: str, obj) -> None:
    full = os.path.join(root, rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write('\n')


def _rm_glob(root: str, pattern: str) -> None:
    for p in glob.glob(os.path.join(root, pattern)):
        if os.path.isdir(p):
            shutil.rmtree(p, ignore_errors=True)
        else:
            os.remove(p)


def reset(root: str) -> None:
    """删除 deepread 阶段落盘产物，清空根索引 entries，重置 ledger 高水位。"""
    # 1. 删除实体 / 事件 / 章节 / 关系 / 设定 / 故事线 / 账本等产物
    _rm_glob(root, 'events/block-*.json')
    _rm_glob(root, 'characters/char-*')
    _rm_glob(root, 'plot/chapters/*.md')
    _rm_glob(root, 'plot/arcs/*.md')
    _rm_glob(root, 'relationships/pairs/*.json')
    _rm_glob(root, 'relationships/by-character/*.json')
    _rm_glob(root, 'settings/entries/*.json')
    _rm_glob(root, 'threads/thread-*.json')
    _rm_glob(root, 'emotions/emo-*')
    _rm_glob(root, 'factions/fac-*')
    _rm_glob(root, 'ledger/chapters/*.json')

    # 2. 清空根索引 entries（保留 id / kind / novel_id / title / schema_version 骨架）
    for rel in ROOT_INDEXES:
        idx = _load(root, rel)
        if idx is None:
            continue
        idx['entries'] = []
        idx['revision'] = 1
        idx['safe_through'] = 0
        if 'scope' in idx:
            idx['scope']['chapter_ranges'] = []
            idx['scope']['subject_refs'] = []
        _write(root, rel, idx)

    # 3. 重置 ledger 高水位（让 ID 从 1 重新分配）
    id_state = _load(root, 'ledger/id-state.json')
    if id_state and 'high_watermarks' in id_state:
        for ns in id_state['high_watermarks']:
            id_state['high_watermarks'][ns] = 0
        _write(root, 'ledger/id-state.json', id_state)


def archive(root: str) -> None:
    """按顺序重放 chapters 与 stages 到正式索引目录。"""
    writer = IndexWriter(root)
    staging = os.path.join(root, STAGING_DIR)

    # 1. 逐章精读结果（按 chapter_order 升序）
    chapter_files = sorted(glob.glob(os.path.join(staging, 'chapters', 'ch-*.json')))
    for cf in chapter_files:
        with open(cf, encoding='utf-8') as f:
            extraction = json.load(f)
        chapter_order = extraction.get('chapter_order')
        if chapter_order is None:
            print(f'  [skip] missing chapter_order: {os.path.basename(cf)}')
            continue
        print(f'[archive] chapter {chapter_order} <- {os.path.basename(cf)}')
        writer.write_chapter(chapter_order, extraction)

    # 2. stage 聚合结果（按 stage-plan 中的顺序匹配 stage 对象）
    stage_plan = _load(root, 'navigation/stage-plan.json') or {}
    stages_by_id = {st['id']: st for st in stage_plan.get('stages', [])}
    commit_files = sorted(glob.glob(os.path.join(staging, 'stages', '*.commit.json')))
    for cf in commit_files:
        stage_id = os.path.basename(cf).replace('.commit.json', '')
        stage = stages_by_id.get(stage_id)
        if stage is None:
            print(f'  [warn] stage {stage_id} not in stage-plan, skip')
            continue
        with open(cf, encoding='utf-8') as f:
            payload = json.load(f)
        print(f'[archive] stage {stage_id} <- {os.path.basename(cf)}')
        writer.write_stage_commit(stage, payload)


def main() -> None:
    parser = argparse.ArgumentParser(description='重新归档 _staging/deepread 下的精读产物')
    parser.add_argument('--novel-root', default=NOVEL_ROOT)
    parser.add_argument('--no-reset', action='store_true', help='不清理旧产物，仅重放')
    args = parser.parse_args()

    root = args.novel_root
    if not args.no_reset:
        reset(root)
        print('[reset] deepread artifacts cleared and ledger reset')
    archive(root)
    print('[done] archive complete')


if __name__ == '__main__':
    main()