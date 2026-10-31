"""离线重放落库脚本。

把 _staging/deepread 下已生成的章节提取结果（chapters/*.json）与 stage 聚合结果
（stages/*.commit.json）重新写入正式索引目录，避免重复调用 LLM。

用法：
    python replay_write.py [novel_root]
"""
import json
import os
import shutil
import sys

from index_writer import IndexWriter


def reset(root: str):
    """清理正式索引目录中的落库产物，并复位 id-state 与各主题根索引。"""
    novel_id = _manifest_id(root)

    # 1. 删除落库产物目录/文件
    for rel in [
        'characters/char-*', 'factions/fac-*', 'emotions/emo-*',
        'settings/entries/*.json',
        'relationships/pairs/*.json', 'relationships/by-character/*.json',
        'threads/thread-*.json',
        'plot/chapters/*.md', 'plot/arcs/*.md',
        'events/block-*.json',
        'ledger/chapters/*.json',
    ]:
        import glob
        for p in glob.glob(os.path.join(root, rel)):
            if os.path.isdir(p):
                shutil.rmtree(p)
            else:
                os.remove(p)

    # 2. 复位 id-state 高水位
    id_path = os.path.join(root, 'ledger/id-state.json')
    if os.path.isfile(id_path):
        st = json.load(open(id_path, encoding='utf-8'))
        st['high_watermarks'] = {k: 0 for k in st.get('high_watermarks', {})}
        st['pending_reservation'] = None
        st['revision'] = 1
        st['safe_through'] = 0
        _dump(id_path, st)

    # 3. 复位各主题根索引（保留骨架，清空 entries/scope）
    for topic in ['characters', 'factions', 'emotions', 'settings', 'relationships',
                  'threads', 'plot', 'events']:
        idx_path = os.path.join(root, f'{topic}/index.json')
        if os.path.isfile(idx_path):
            idx = json.load(open(idx_path, encoding='utf-8'))
            idx['entries'] = []
            idx['scope'] = {'chapter_ranges': [], 'subject_refs': []}
            idx['safe_through'] = 0
            idx['revision'] = 1
            _dump(idx_path, idx)


def _manifest_id(root: str) -> str:
    m = json.load(open(os.path.join(root, 'manifest.json'), encoding='utf-8'))
    return m.get('novel_id', 'unknown')


def _dump(path: str, obj):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write('\n')


def replay(root: str):
    staging = os.path.join(root, '_staging/deepread')
    if not os.path.isdir(staging):
        print('未找到 _staging/deepread，请先运行 deepread_simple.py 生成提取结果')
        return

    writer = IndexWriter(root)

    # 1. 章级落库（按章节号排序）
    chapters_dir = os.path.join(staging, 'chapters')
    if os.path.isdir(chapters_dir):
        files = sorted(os.listdir(chapters_dir))
        for fn in files:
            if not fn.endswith('.json'):
                continue
            ext = json.load(open(os.path.join(chapters_dir, fn), encoding='utf-8'))
            ch = ext.get('chapter_order')
            if not ch:
                continue
            writer.write_chapter(ch, ext)
            print(f'[replay] 落库 ch-{ch:06d}')

    # 2. stage 聚合落库
    stages_dir = os.path.join(staging, 'stages')
    if os.path.isdir(stages_dir):
        stage_plan = json.load(open(os.path.join(root, 'navigation/stage-plan.json'), encoding='utf-8'))
        stage_by_id = {st['id']: st for st in stage_plan['stages']}
        for fn in sorted(os.listdir(stages_dir)):
            if not fn.endswith('.commit.json'):
                continue
            stage_id = fn.replace('.commit.json', '')
            commit = json.load(open(os.path.join(stages_dir, fn), encoding='utf-8'))
            stage = stage_by_id.get(stage_id)
            if stage is None:
                print(f'[warn] 未在 stage-plan 找到 {stage_id}')
                continue
            writer.write_stage_commit(stage, commit)
            print(f'[replay] 落库 {stage_id} stage 聚合')


if __name__ == '__main__':
    root = sys.argv[1] if len(sys.argv) > 1 else 'novel'
    root = os.path.abspath(root)
    print(f'== 清理正式索引产物 ==  {root}')
    reset(root)
    print(f'== 离线重放落库 ==')
    replay(root)
    print('== 完成 ==')
