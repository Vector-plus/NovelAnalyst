"""确定性落库层。

把 ReAct Agent 产出的结构化结果（ChapterExtraction / StageCommitPayload），
按 novel-index-templates.md v2.0 的格式写入正式索引目录：

    events/block-*.json          event_collection（事件 + 分次更新 + 陈述）
    plot/chapters/ch-*.md        chapter_summary（章节摘要 Markdown）
    plot/arcs/arc-*.md           arc_summary（剧情阶段 Markdown）
    characters/char-*/index.json entity_index（人物档案）
    characters/char-*/stages/*.md character_stage（人物阶段 Markdown）
    factions/fac-*/index.json    entity_index（势力档案）
    factions/landscape/*.md      faction_landscape（格局概览）
    settings/entries/*.json      setting（体系设定）
    relationships/pairs/*.json   relationship（关系对）
    relationships/by-character/*.json 按人物索引的关系入口
    emotions/emo-*/index.json    emotional_index（感情线）
    emotions/emo-*/stages/*.md   emotional_stage
    threads/thread-*.json        story_thread（故事线）
    ledger/chapters/*.json       chapter_ledger（章节账本，四态状态机）
    ledger/id-state.json         id_state（ID 高水位）

本模块不依赖 LLM，只做确定性转换与写盘（对应 03-核心图设计.md 的 D 类写入服务）。
"""
import json
import os
import re
from typing import Optional


# ---------- 公共辅助 ----------
def _filemeta(novel_id: str, record_id: str, kind: str, safe_through: int,
              revision: int = 1) -> dict:
    """生成公共文件头 FileMeta（模板 §3.1）。"""
    return {
        'schema_version': '2.0',
        'novel_id': novel_id,
        'id': record_id,
        'kind': kind,
        'revision': revision,
        'safe_through': safe_through,
    }


def _ref(path: str, record_id: str) -> dict:
    """生成引用 Ref（模板 §3.3）。"""
    return {'path': path, 'record_id': record_id}


def _write_json(root: str, rel_path: str, obj: dict) -> None:
    """写 JSON 文件（UTF-8、两空格缩进、末尾 LF）。"""
    full = os.path.join(root, rel_path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write('\n')


def _write_markdown(root: str, rel_path: str, text: str) -> None:
    """写 Markdown 文件（LF、末尾 LF）。"""
    full = os.path.join(root, rel_path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    text = text.replace('\r\n', '\n')
    if not text.endswith('\n'):
        text += '\n'
    with open(full, 'w', encoding='utf-8') as f:
        f.write(text)


def _load(root: str, rel_path: str) -> Optional[dict]:
    full = os.path.join(root, rel_path)
    if not os.path.isfile(full):
        return None
    with open(full, encoding='utf-8') as f:
        return json.load(f)


# ---------- ID 分配器（模板 §11.4） ----------
class IdAllocator:
    """ID 高水位分配器，持久化到 ledger/id-state.json。"""

    NAMESPACES = ['char', 'fac', 'setting', 'ev', 'rel', 'emo', 'thread',
                  'claim', 'update', 'issue']

    def __init__(self, root: str, novel_id: str):
        self.root = root
        self.novel_id = novel_id
        self.path = os.path.join(root, 'ledger/id-state.json')
        self.state = self._load()

    def _load(self) -> dict:
        data = _load(self.root, 'ledger/id-state.json')
        if data and 'high_watermarks' in data:
            return data
        return _filemeta(self.novel_id, 'id-state', 'id_state', 0) | {
            'high_watermarks': {ns: 0 for ns in self.NAMESPACES},
            'pending_reservation': None,
        }

    def allocate(self, namespace: str, count: int = 1) -> list:
        assert namespace in self.NAMESPACES, f'非法命名空间: {namespace}'
        base = self.state['high_watermarks'][namespace]
        ids = [f'{namespace}-{base + i + 1:04d}' for i in range(count)]
        self.state['high_watermarks'][namespace] = base + count
        self._save()
        return ids

    def _save(self) -> None:
        _write_json(self.root, 'ledger/id-state.json', self.state)


# ---------- 名字索引（模板 §4.4 / §4.5，简化内存 + 落盘） ----------
class NameIndex:
    """名字 → 实体 char-* 的映射，含别名。"""

    def __init__(self, root: str, novel_id: str):
        self.root = root
        self.novel_id = novel_id
        self._name_to_char = {}
        self._char_to_label = {}
        self._load_existing()

    def _load_existing(self):
        # 从已存在的 characters 根索引恢复 label 映射
        idx = _load(self.root, 'characters/index.json')
        if idx:
            for e in idx.get('entries', []):
                char_id = e.get('target', {}).get('record_id')
                label = e.get('title')
                if char_id and label:
                    self._name_to_char[label] = char_id
                    self._char_to_label[char_id] = label

    def resolve(self, name: str) -> Optional[str]:
        return self._name_to_char.get(name)

    def register(self, name: str, char_id: str, aliases=None):
        self._name_to_char[name] = char_id
        self._char_to_label[char_id] = name
        for a in (aliases or []):
            if a and a != name:
                self._name_to_char[a] = char_id

    def label_of(self, char_id: str) -> str:
        return self._char_to_label.get(char_id, char_id)


# ---------- 核心落库器 ----------
class IndexWriter:
    def __init__(self, root: str):
        self.root = root
        manifest = _load(root, 'manifest.json') or {}
        self.novel_id = manifest.get('novel_id', 'unknown')
        self.source_version = manifest.get('source_version', 'source-v1')
        self.id_alloc = IdAllocator(root, self.novel_id)
        self.name_index = NameIndex(root, self.novel_id)
        self.stage_plan = _load(root, 'navigation/stage-plan.json') or {'stages': []}
        # stage_id -> 序号（1 起），用于 block 分片编号
        self._stage_order = {st['id']: i + 1 for i, st in enumerate(self.stage_plan['stages'])}
        # 本章运行期：local_id -> real_id 映射（跨函数共享）
        self._local_to_real: dict = {}
        self._name_to_ref: dict = {}
        # 关系对映射：sorted(char_id 对) -> rel_id，供 stage 落库查找已有关系
        self._pair_rel_map: dict = {}
        # 当前章所属 stage 的 block 分片名（供 claim Ref 指向正确的 block 文件）
        self._current_block_id = 'block-0001'

    # ==================== 工具方法 ====================
    def _stage_of(self, chapter_order: int) -> dict:
        for st in self.stage_plan['stages']:
            for r in st['chapter_ranges']:
                if r['start'] <= chapter_order <= r['end']:
                    return st
        return {'id': 'stage-000', 'title': '未知', 'chapter_ranges': [{'start': chapter_order, 'end': chapter_order}]}

    def _block_id_for_stage(self, stage_id: str) -> str:
        order = self._stage_order.get(stage_id, 1)
        return f'block-{order:04d}'

    def _resolve_name_ref(self, name: str) -> Optional[dict]:
        """名字 → 实体 Ref（已建档），否则返回 None。"""
        char_id = self.name_index.resolve(name)
        if char_id:
            return _ref(f'characters/{char_id}/index.json', char_id)
        return None

    def _ensure_char_ref(self, name: str, introduced_at: int,
                         aliases=None, identity_notes_text: str = '',
                         evidence_local_ids=None) -> dict:
        """为名字解析或新建人物实体，返回其 Ref。"""
        if name in self._name_to_ref:
            return self._name_to_ref[name]

        char_id = self.name_index.resolve(name)
        if char_id is None:
            char_id = self.id_alloc.allocate('char', 1)[0]
            self.name_index.register(name, char_id, aliases)
            self._create_entity_index(
                char_id=char_id, entity_type='character', label=name,
                introduced_at=introduced_at, identity_notes_text=identity_notes_text,
                evidence_local_ids=evidence_local_ids or [],
            )
        ref = _ref(f'characters/{char_id}/index.json', char_id)
        self._name_to_ref[name] = ref
        return ref

    def _create_entity_index(self, char_id: str, entity_type: str, label: str,
                             introduced_at: int, identity_notes_text: str,
                             evidence_local_ids: list):
        """写 characters/char-*/index.json（entity_index，模板 §7.2）。"""
        identity_notes = []
        claim_refs = self._local_ids_to_refs(evidence_local_ids)
        if claim_refs or identity_notes_text:
            identity_notes.append({
                'id': f'in-{char_id}-001',
                'revealed_at': introduced_at,
                'claims': [],
                'claim_refs': claim_refs,
            })
        doc = _filemeta(self.novel_id, char_id, 'entity_index', introduced_at) | {
            'entity_type': entity_type,
            'label': label,
            'introduced_at': introduced_at,
            'identity_notes': identity_notes,
            'identity_links': [],
            'related_materials': [],
            'entries': [],
        }
        _write_json(self.root, f'characters/{char_id}/index.json', doc)
        # 更新根索引
        self._append_root_entry('characters', char_id, 'entity_index', label,
                                introduced_at, 'character')

    def _local_ids_to_refs(self, local_ids: list) -> list:
        """把 local_id 列表转为真实 Claim Ref 列表。"""
        refs = []
        for lid in (local_ids or []):
            real = self._local_to_real.get(lid)
            if real:
                refs.append(_ref(f'events/{self._current_block_id}.json', real))
        return refs

    def _append_root_entry(self, topic: str, record_id: str, kind: str,
                           title: str, chapter_order: int, tag: str):
        """向主题根 index.json 追加一条 IndexEntry。"""
        rel = f'{topic}/index.json'
        idx = _load(self.root, rel)
        if idx is None:
            return
        target_path = self._topic_target_path(topic, record_id)
        entry = {
            'target': _ref(target_path, record_id),
            'kind': kind,
            'title': title,
            'summary': f'{title}（第{chapter_order}章起）',
            'chapter_ranges': [{'start': chapter_order, 'end': chapter_order}],
            'entity_refs': [_ref(target_path, record_id)],
            'tags': [tag],
            'safe_through': chapter_order,
        }
        # 去重
        existing = {e['target']['record_id'] for e in idx.get('entries', [])}
        if record_id not in existing:
            idx.setdefault('entries', []).append(entry)
        idx['revision'] = idx.get('revision', 1) + 1
        idx['safe_through'] = max(idx.get('safe_through', 0), chapter_order)
        # 更新 scope.chapter_ranges（合并）
        idx['scope'] = idx.get('scope', {'chapter_ranges': [], 'subject_refs': []})
        idx['scope']['chapter_ranges'] = self._merge_ranges(
            idx['scope'].get('chapter_ranges', []), chapter_order)
        _write_json(self.root, rel, idx)

    def _topic_target_path(self, topic: str, record_id: str) -> str:
        if topic == 'characters':
            return f'characters/{record_id}/index.json'
        if topic == 'events':
            return f'events/{record_id}.json'
        if topic == 'settings':
            return f'settings/entries/{record_id}.json'
        if topic == 'relationships':
            return f'relationships/pairs/{record_id}.json'
        if topic == 'threads':
            return f'threads/{record_id}.json'
        if topic == 'factions':
            return f'factions/{record_id}/index.json'
        if topic == 'emotions':
            return f'emotions/{record_id}/index.json'
        if topic == 'plot':
            # arc 文件实际落盘为 plot/arcs/arc-NNN.md，record_id 形如 doc-arc-NNN
            return f'plot/arcs/{record_id[len("doc-"):]}.md'
        return f'{topic}/{record_id}.json'

    @staticmethod
    def _merge_ranges(ranges: list, chapter_order: int) -> list:
        """把 chapter_order 并入升序、无重叠、相邻合并的 ranges。"""
        if not ranges:
            return [{'start': chapter_order, 'end': chapter_order}]
        merged = [dict(r) for r in ranges]
        merged.append({'start': chapter_order, 'end': chapter_order})
        merged.sort(key=lambda r: r['start'])
        out = []
        for r in merged:
            if out and r['start'] <= out[-1]['end'] + 1:
                out[-1]['end'] = max(out[-1]['end'], r['end'])
            else:
                out.append(r)
        return out

    # ==================== 章级落库 ====================
    def write_chapter(self, chapter_order: int, extraction: dict):
        """把 ChapterExtraction 落库为 events/plot/characters/relationships/settings/threads + 账本。"""
        self._local_to_real = {}
        self._name_to_ref = {}
        stage = self._stage_of(chapter_order)
        stage_id = stage['id']
        self._current_block_id = self._block_id_for_stage(stage_id)

        # 1. 分配 claim / event / update ID
        new_claims = extraction.get('new_claims', [])
        new_events = extraction.get('new_events', [])
        claim_ids = self.id_alloc.allocate('claim', len(new_claims)) if new_claims else []
        ev_ids = self.id_alloc.allocate('ev', len(new_events)) if new_events else []
        update_ids = self.id_alloc.allocate('update', len(new_events)) if new_events else []

        for c, cid in zip(new_claims, claim_ids):
            self._local_to_real[c.get('local_id')] = cid
        for e, eid in zip(new_events, ev_ids):
            self._local_to_real[e.get('local_id')] = eid

        # 2. 先解析所有新人物候选，建立 name -> ref
        for cand in extraction.get('new_character_candidates', []):
            name = cand.get('label')
            if name:
                self._ensure_char_ref(
                    name,
                    introduced_at=cand.get('introduced_at', chapter_order),
                    aliases=cand.get('alias_texts', []),
                    identity_notes_text=cand.get('identity_notes', ''),
                    evidence_local_ids=cand.get('evidence_claim_local_ids', []),
                )

        # 3. 写事件块（events/block-*.json）
        if new_events:
            self._write_events_block(stage_id, chapter_order, extraction, new_events,
                                     ev_ids, update_ids, claim_ids, new_claims)

        # 4. 写章节摘要（plot/chapters/ch-*.md）
        summary = extraction.get('chapter_summary_markdown')
        if summary:
            self._write_chapter_md(chapter_order, stage_id, summary)

        # 5. 写设定（settings/entries/setting-*.json）
        for cand in extraction.get('new_setting_candidates', []):
            self._write_setting(chapter_order, cand)

        # 6. 写关系（relationships/pairs/rel-*.json）
        for cand in extraction.get('relationship_candidates', []):
            self._write_relationship(chapter_order, stage_id, cand)

        # 7. 写故事线（threads/thread-*.json）
        for cand in extraction.get('thread_update_candidates', []):
            self._write_thread(chapter_order, cand)

        # 8. 写章节账本（ledger/chapters/ch-*.json，status=committed）
        self._write_chapter_ledger(chapter_order, extraction)

    def _write_events_block(self, stage_id, chapter_order, extraction, new_events,
                            ev_ids, update_ids, claim_ids, new_claims):
        block_id = self._block_id_for_stage(stage_id)
        rel = f'events/{block_id}.json'
        block = _load(self.root, rel)
        if block is None:
            block = _filemeta(self.novel_id, block_id, 'event_collection', chapter_order)
            block['events'] = []

        # 建立 claim local_id -> Claim 对象（含真实 id）
        claim_by_local = {c['local_id']: c for c in new_claims}
        # 跨事件去重：同一 claim 只内联一次，避免重复 record_id；
        # 后续事件重复声明同一 local_id 时改走 trigger_refs 关联而非再次内联。
        claimed_locals = set()

        for e, ev_id, upd_id in zip(new_events, ev_ids, update_ids):
            upd = e.get('update', {})
            participants = []
            for p in upd.get('participants', []):
                ent = p.get('entity_ref_or_candidate', {})
                role = p.get('role', 'unknown')
                ref = None
                if ent.get('candidate_name'):
                    ref = self._ensure_char_ref(ent['candidate_name'], chapter_order)
                elif ent.get('path') and ent.get('record_id'):
                    ref = _ref(ent['path'], ent['record_id'])
                if ref:
                    participants.append({'entity_ref': ref, 'role': role})

            # 组装 update.claims（内联 Claim）
            claims = []
            reused_claim_local_ids = []
            for lid in upd.get('new_claim_local_ids', []):
                c = claim_by_local.get(lid)
                if not c:
                    continue
                if lid in claimed_locals:
                    # 已在先前事件内联过，改为引用而非重复内联
                    reused_claim_local_ids.append(lid)
                    continue
                claimed_locals.add(lid)
                claims.append(self._to_claim(c, self._local_to_real[lid]))
            for lid in upd.get('reused_claim_refs', []):
                # reused 是已有 claim 的引用，用 Ref 而非内联
                pass

            event_update = {
                'id': upd_id,
                'chapter_ranges': upd.get('chapter_ranges') or [{'start': chapter_order, 'end': chapter_order}],
                'revealed_at': upd.get('revealed_at', chapter_order),
                'status': upd.get('status', 'ongoing'),
                'story_time': upd.get('story_time'),
                'summary': upd.get('summary', ''),
                'participants': participants,
                'claims': claims,
                'trigger_refs': self._local_ids_to_refs(
                    (upd.get('trigger_claim_local_ids', []) or []) + reused_claim_local_ids),
                'action_refs': self._local_ids_to_refs(upd.get('action_claim_local_ids', [])),
                'outcome_refs': self._local_ids_to_refs(upd.get('outcome_claim_local_ids', [])),
                'related_event_refs': [],
            }
            block['events'].append({
                'id': ev_id,
                'kind': 'event',
                'title': e.get('title', ''),
                'introduced_at': e.get('introduced_at', chapter_order),
                'safe_through': chapter_order,
                'updates': [event_update],
            })

        block['revision'] = block.get('revision', 1) + 1
        block['safe_through'] = max(block.get('safe_through', 0), chapter_order)
        _write_json(self.root, rel, block)

        # 更新 events/index.json（块级入口）
        self._append_root_entry('events', block_id, 'event_collection',
                                f'{stage_id} 事件块', chapter_order, 'event')

    def _to_claim(self, c: dict, claim_id: str) -> dict:
        attributed = c.get('attributed_to_candidate_or_ref')
        attributed_ref = None
        if attributed:
            if attributed.get('candidate_name'):
                ref = self._resolve_name_ref(attributed['candidate_name'])
                attributed_ref = ref or None
            elif attributed.get('path') and attributed.get('record_id'):
                attributed_ref = _ref(attributed['path'], attributed['record_id'])
        return {
            'id': claim_id,
            'text': c.get('text', ''),
            'certainty': c.get('certainty', 'explicit'),
            'attributed_to_ref': attributed_ref,
            'revealed_at': c.get('revealed_at', 1),
            'source_refs': c.get('source_refs', []),
            'basis_refs': c.get('basis_refs', []),
            'supersedes_refs': c.get('supersedes_refs', []),
        }

    def _write_chapter_md(self, chapter_order: int, stage_id: str, summary: dict):
        info = self._chapter_info(chapter_order)
        chapter_id = info['chapter_id']
        fm = summary.get('front_matter', {})
        title = summary.get('title') or f'第{chapter_order}章'

        # 生成 Front Matter
        subject_refs = []
        for s in fm.get('subject_refs_or_candidates', []):
            if s.get('candidate_name'):
                ref = self._resolve_name_ref(s['candidate_name'])
                if ref:
                    subject_refs.append(ref)
            elif s.get('path'):
                subject_refs.append(_ref(s['path'], s.get('record_id')))

        record_refs = []
        for rid in fm.get('record_refs_or_local_ids', []):
            real = self._local_to_real.get(rid)
            if real:
                record_refs.append(_ref(f'events/{self._current_block_id}.json', real))
            # 非 local id（如已存在的 ref）直接跳过，简化处理

        lines = ['---',
                 'schema_version: "2.0"',
                 f'novel_id: {self.novel_id}',
                 f'id: doc-{chapter_id}',
                 'kind: chapter_summary',
                 'revision: 1',
                 f'safe_through: {chapter_order}',
                 f'title: {title}',
                 'chapter_ranges:',
                 f'  - start: {chapter_order}',
                 f'    end: {chapter_order}',
                 f'as_of: {chapter_order}',
                 'stage_ref:',
                 '  path: navigation/stage-plan.json',
                 f'  record_id: {stage_id}',
                 'subject_refs:']
        for r in subject_refs:
            lines.append(f'  - path: {r["path"]}')
            lines.append(f'    record_id: {r["record_id"]}')
        lines.append('record_refs:')
        for r in record_refs:
            lines.append(f'  - path: {r["path"]}')
            lines.append(f'    record_id: {r["record_id"]}')
        lines.append('source_refs:')
        lines.append(f'  - path: {info["path"]}')
        lines.append(f'    chapter_id: {chapter_id}')
        lines.append(f'    chapter_order: {chapter_order}')
        lines.append('---')
        lines.append('')
        lines.append(f'# {title}')
        lines.append('')
        lines.append(summary.get('body_markdown', ''))

        _write_markdown(self.root, f'plot/chapters/{chapter_id}.md', '\n'.join(lines))

    def _chapter_info(self, chapter_order: int) -> dict:
        si = _load(self.root, 'source/index.json') or {'entries': []}
        for entry in si['entries']:
            vol_id = entry['target']['path'].split('/')[1]
            vol = _load(self.root, entry['target']['path']) or {'chapters': []}
            for ch in vol['chapters']:
                if ch['chapter_order'] == chapter_order:
                    return {'chapter_id': ch['id'], 'path': ch['path'], 'vol_id': vol_id}
        return {'chapter_id': f'ch-{chapter_order:06d}', 'path': f'source/vol-001/ch-{chapter_order:06d}.txt', 'vol_id': 'vol-001'}

    def _write_setting(self, chapter_order: int, cand: dict):
        label = cand.get('label', '')
        if not label:
            return
        sid = self.id_alloc.allocate('setting', 1)[0]
        category = cand.get('category', 'other')
        # 映射到 §3.8 受控值
        valid = {'power_system', 'ability', 'artifact', 'geography', 'species', 'social_rule', 'other'}
        if category not in valid:
            category = 'other'
        evidence_refs = self._local_ids_to_refs(cand.get('evidence_claim_local_ids', []))
        doc = _filemeta(self.novel_id, sid, 'setting', chapter_order) | {
            'label': label,
            'category': category,
            'introduced_at': cand.get('introduced_at', chapter_order),
            'updates': [{
                'id': f'update-{sid}-001',
                'revealed_at': chapter_order,
                'chapter_ranges': [{'start': chapter_order, 'end': chapter_order}],
                'claims': [],
                'definition_refs': [],
                'condition_refs': evidence_refs,
                'limitation_refs': [],
                'cost_refs': [],
                'exception_refs': [],
                'change_refs': [],
                'demonstration_event_refs': [],
                'related_event_refs': [],
                'links': [],
            }],
        }
        _write_json(self.root, f'settings/entries/{sid}.json', doc)
        self._append_root_entry('settings', sid, 'setting', label, chapter_order, 'setting')

    def _write_relationship(self, chapter_order: int, stage_id: str, cand: dict):
        a = cand.get('subject_a', {})
        b = cand.get('subject_b', {})
        a_name = a.get('candidate_name')
        b_name = b.get('candidate_name')
        if not a_name or not b_name:
            return
        ref_a = self._ensure_char_ref(a_name, chapter_order)
        ref_b = self._ensure_char_ref(b_name, chapter_order)
        # subjects 按 ID 排序去重
        subjects = sorted([ref_a, ref_b], key=lambda r: r['record_id'])
        if subjects[0]['record_id'] == subjects[1]['record_id']:
            return  # 同一实体，跳过

        pair_key = (subjects[0]['record_id'], subjects[1]['record_id'])
        if pair_key in self._pair_rel_map:
            return  # 该关系对已建，跳过重复新建（stage 快照由 stage 落库追加）
        rid = self.id_alloc.allocate('rel', 1)[0]
        self._pair_rel_map[pair_key] = rid
        facet = cand.get('facet', {})
        basis_refs = self._local_ids_to_refs(cand.get('source_claim_local_ids', []))
        summary = cand.get('summary', '')
        doc = _filemeta(self.novel_id, rid, 'relationship', chapter_order) | {
            'introduced_at': chapter_order,
            'subjects': subjects,
            'stages': [{
                'id': f'{rid}-stage-001',
                'stage_ref': _ref('navigation/stage-plan.json', stage_id),
                'chapter_ranges': [{'start': chapter_order, 'end': chapter_order}],
                'as_of': chapter_order,
                'revealed_at': chapter_order,
                'summary': summary,
                'claims': [],
                'facets': [{
                    'type': facet.get('type', 'other'),
                    'direction': 'symmetric',
                    'from_ref': None,
                    'to_ref': None,
                    'description': summary,
                    'basis_refs': basis_refs,
                }],
                'attitudes': [],
                'turning_event_refs': [],
            }],
        }
        _write_json(self.root, f'relationships/pairs/{rid}.json', doc)
        self._append_root_entry('relationships', rid, 'relationship',
                                f'{a_name}×{b_name}', chapter_order, 'relationship')
        # 写 by-character 索引（两个主体各一份）
        for ref in subjects:
            self._write_by_character_index(ref, rid, f'{a_name}×{b_name}', chapter_order)

    def _write_by_character_index(self, subject_ref: dict, rel_id: str, title: str, chapter_order: int):
        char_id = subject_ref['record_id']
        rel = f'relationships/by-character/{char_id}.json'
        idx = _load(self.root, rel)
        if idx is None:
            idx = _filemeta(self.novel_id, f'idx-rel-{char_id}', 'index', chapter_order) | {
                'title': f'{self.name_index.label_of(char_id)} 关系入口',
                'scope': {'chapter_ranges': [], 'subject_refs': [subject_ref]},
                'coverage_status': 'partial',
                'entries': [],
            }
        entry = {
            'target': _ref(f'relationships/pairs/{rel_id}.json', rel_id),
            'kind': 'relationship',
            'title': title,
            'summary': f'与{title}的关系',
            'chapter_ranges': [{'start': chapter_order, 'end': chapter_order}],
            'entity_refs': [subject_ref],
            'tags': ['relationship'],
            'safe_through': chapter_order,
        }
        existing = {e['target']['record_id'] for e in idx.get('entries', [])}
        if rel_id not in existing:
            idx['entries'].append(entry)
        idx['revision'] = idx.get('revision', 1) + 1
        idx['safe_through'] = max(idx.get('safe_through', 0), chapter_order)
        idx['scope']['chapter_ranges'] = self._merge_ranges(
            idx['scope'].get('chapter_ranges', []), chapter_order)
        _write_json(self.root, rel, idx)

    def _write_thread(self, chapter_order: int, cand: dict):
        title = cand.get('title') or cand.get('label', '')
        if not title:
            return
        tid = self.id_alloc.allocate('thread', 1)[0]
        category = cand.get('category', 'subplot')
        status = cand.get('status', 'open')
        role = cand.get('role', 'introduction')
        claim_refs = self._local_ids_to_refs(cand.get('source_claim_local_ids', []))
        doc = _filemeta(self.novel_id, tid, 'story_thread', chapter_order) | {
            'label': title,
            'introduced_at': chapter_order,
            'updates': [{
                'id': f'update-{tid}-001',
                'revealed_at': chapter_order,
                'chapter_ranges': [{'start': chapter_order, 'end': chapter_order}],
                'category': category,
                'status': status,
                'role': role,
                'summary': cand.get('summary', ''),
                'claims': [],
                'claim_refs': claim_refs,
                'event_refs': [],
                'resolution_refs': [],
            }],
        }
        _write_json(self.root, f'threads/{tid}.json', doc)
        self._append_root_entry('threads', tid, 'story_thread', title, chapter_order, 'thread')

    def _write_chapter_ledger(self, chapter_order: int, extraction: dict):
        info = self._chapter_info(chapter_order)
        chapter_id = info['chapter_id']
        doc = _filemeta(self.novel_id, f'ledger-{chapter_id}', 'chapter_ledger', 0) | {
            'chapter_ref': {'chapter_id': chapter_id, 'chapter_order': chapter_order},
            'source_version': self.source_version,
            'stage_plan_revision': self.stage_plan.get('revision', 1),
            'status': 'committed',
            'allocated_ids': list(self._local_to_real.values()),
            'input_revisions': [],
            'extraction': {
                'summary': f'第{chapter_order}章精读完成',
                'record_ids': list(self._local_to_real.values()),
                'coverage_topics': {},
            },
            'operations': [],
            'error': None,
        }
        _write_json(self.root, f'ledger/chapters/{chapter_id}.json', doc)

    # ==================== stage 聚合落库 ====================
    def write_stage_commit(self, stage: dict, payload: dict):
        stage_id = stage['id']
        ranges = stage['chapter_ranges']
        stage_start = ranges[0]['start']
        stage_end = ranges[-1]['end']
        as_of = payload.get('as_of', stage_end)

        # 1. 剧情阶段 arc
        arc = payload.get('arc_summary')
        if arc:
            self._write_arc_md(stage_id, stage_start, stage_end, as_of, arc)

        # 2. 人物阶段 Markdown
        for cs in payload.get('character_stages', []):
            self._write_entity_stage_md('characters', cs, stage_id, stage_start, stage_end, as_of, 'character_stage')

        # 3. 势力阶段 Markdown
        for fs in payload.get('faction_stages', []):
            self._write_entity_stage_md('factions', fs, stage_id, stage_start, stage_end, as_of, 'faction_stage')

        # 4. 关系阶段快照（追加到 relationships/pairs/*.json）
        for rs in payload.get('relationship_snapshots', []):
            self._append_relationship_snapshot(stage_id, stage_start, stage_end, as_of, rs)

        # 5. 感情线
        for es in payload.get('emotional_stages', []):
            self._write_emotional(stage_id, stage_start, stage_end, as_of, es)

    def _write_arc_md(self, stage_id, stage_start, stage_end, as_of, arc: dict):
        title = arc.get('front_matter', {}).get('title') or f'{stage_id} 阶段'
        order = self._stage_order.get(stage_id, 1)
        arc_id = f'arc-{order:03d}'
        lines = ['---',
                 'schema_version: "2.0"',
                 f'novel_id: {self.novel_id}',
                 f'id: doc-{arc_id}',
                 'kind: arc_summary',
                 'revision: 1',
                 f'safe_through: {as_of}',
                 f'title: {title}',
                 'chapter_ranges:',
                 f'  - start: {stage_start}',
                 f'    end: {stage_end}',
                 f'as_of: {as_of}',
                 'stage_ref:',
                 '  path: navigation/stage-plan.json',
                 f'  record_id: {stage_id}',
                 'subject_refs: []',
                 'record_refs: []',
                 'source_refs: []',
                 '---',
                 '',
                 f'# {title}',
                 '',
                 arc.get('body_markdown', '')]
        _write_markdown(self.root, f'plot/arcs/{arc_id}.md', '\n'.join(lines))
        # 更新 plot/index.json
        self._append_root_entry('plot', f'doc-{arc_id}', 'arc_summary', title, as_of, 'plot')

    def _write_entity_stage_md(self, topic, cs: dict, stage_id, stage_start, stage_end, as_of, kind):
        # 优先用 candidate_name 通过名字索引解析真实实体 ID（Agent 的 entity_ref 是猜测 ID，不可信）
        ent_id = None
        label = None
        cand_name = cs.get('candidate_name')
        if cand_name:
            ref = self._resolve_name_ref(cand_name)
            if ref:
                ent_id = ref['record_id']
                label = cand_name
        if not ent_id:
            ent_ref = cs.get('entity_ref') or {}
            ent_id = ent_ref.get('record_id')
            label = ent_id
        if not ent_id:
            return
        sm = cs.get('stage_markdown', {})
        title = sm.get('front_matter', {}).get('title') or f'{stage_id} 阶段'
        order = self._stage_order.get(stage_id, 1)
        doc_id = f'doc-{ent_id}-stage-{order:03d}'
        lines = ['---',
                 'schema_version: "2.0"',
                 f'novel_id: {self.novel_id}',
                 f'id: {doc_id}',
                 f'kind: {kind}',
                 'revision: 1',
                 f'safe_through: {as_of}',
                 f'title: {title}',
                 'chapter_ranges:',
                 f'  - start: {stage_start}',
                 f'    end: {stage_end}',
                 f'as_of: {as_of}',
                 'stage_ref:',
                 '  path: navigation/stage-plan.json',
                 f'  record_id: {stage_id}',
                 'subject_refs:',
                 f'  - path: {topic}/{ent_id}/index.json',
                 f'    record_id: {ent_id}',
                 'record_refs: []',
                 'source_refs: []',
                 '---',
                 '',
                 f'# {title}',
                 '',
                 sm.get('body_markdown', '')]
        _write_markdown(self.root, f'{topic}/{ent_id}/stages/stage-{order:03d}.md', '\n'.join(lines))
        # 更新实体入口的 entries
        self._append_entity_stage_entry(topic, ent_id, doc_id, kind, title, stage_start, stage_end, as_of)

    def _append_entity_stage_entry(self, topic, ent_id, doc_id, kind, title, stage_start, stage_end, as_of):
        rel = f'{topic}/{ent_id}/index.json'
        doc = _load(self.root, rel)
        if doc is None:
            return
        entry = {
            'target': _ref(f'{topic}/{ent_id}/stages/stage-{self._stage_order.get("stage-001", 1):03d}.md', doc_id),
            'kind': kind,
            'title': title,
            'summary': f'{title}（第{stage_start}—{stage_end}章）',
            'chapter_ranges': [{'start': stage_start, 'end': stage_end}],
            'entity_refs': [_ref(f'{topic}/{ent_id}/index.json', ent_id)],
            'tags': [kind.split('_')[0]],
            'safe_through': as_of,
        }
        # 修正 target path 需要 stage 序号；这里用 doc_id 反推不好，改用直接构造
        # 简化：从 doc_id 推导文件名
        stage_no = doc_id.rsplit('-stage-', 1)[-1]
        entry['target'] = _ref(f'{topic}/{ent_id}/stages/stage-{stage_no}.md', doc_id)
        existing = {e['target']['record_id'] for e in doc.get('entries', [])}
        if doc_id not in existing:
            doc.setdefault('entries', []).append(entry)
        doc['revision'] = doc.get('revision', 1) + 1
        doc['safe_through'] = max(doc.get('safe_through', 0), as_of)
        _write_json(self.root, rel, doc)

    def _append_relationship_snapshot(self, stage_id, stage_start, stage_end, as_of, rs: dict):
        rel_info = rs.get('relationship_ref_or_new', {})
        new_rel = rel_info.get('new_rel', {})
        pair_names = new_rel.get('pair_names', [])
        if len(pair_names) < 2:
            return
        # 用 pair_names 解析真实 char refs（Agent 的 rel_id/from_ref 均为猜测，不可信）
        refs = []
        for name in pair_names:
            ref = self._resolve_name_ref(name)
            if ref:
                refs.append(ref)
        if len(refs) < 2:
            return
        subjects = sorted(refs, key=lambda r: r['record_id'])
        pair_key = (subjects[0]['record_id'], subjects[1]['record_id'])

        # 查找已有 rel，否则新建
        rel_id = self._pair_rel_map.get(pair_key)
        if rel_id is None:
            rel_id = self.id_alloc.allocate('rel', 1)[0]
            self._pair_rel_map[pair_key] = rel_id
            label_a = self.name_index.label_of(subjects[0]['record_id'])
            label_b = self.name_index.label_of(subjects[1]['record_id'])
            doc = _filemeta(self.novel_id, rel_id, 'relationship', as_of) | {
                'introduced_at': stage_start,
                'subjects': subjects,
                'stages': [],
            }
            _write_json(self.root, f'relationships/pairs/{rel_id}.json', doc)
            self._append_root_entry('relationships', rel_id, 'relationship',
                                    f'{label_a}×{label_b}', as_of, 'relationship')
            for ref in subjects:
                self._write_by_character_index(ref, rel_id, f'{label_a}×{label_b}', as_of)
        else:
            doc = _load(self.root, f'relationships/pairs/{rel_id}.json')
            if doc is None:
                return

        # 转换 facets：Agent 的自由文本 facet → 模板受控 facet（type 归为 other）
        facets = []
        for f in rs.get('facets', []):
            direction = f.get('direction', 'symmetric')
            desc = f.get('facet', '')
            if f.get('attitude'):
                desc = f'{desc}；{f["attitude"]}' if desc else f['attitude']
            facets.append({
                'type': 'other',
                'direction': direction,
                'from_ref': None,
                'to_ref': None,
                'description': desc,
                'basis_refs': [],  # Agent 的 basis_refs 是编造引用，置空（宁可缺失不编造）
            })

        order = self._stage_order.get(stage_id, 1)
        snap_id = f'{rel_id}-stage-{order:03d}'
        new_stage = {
            'id': snap_id,
            'stage_ref': _ref('navigation/stage-plan.json', stage_id),
            'chapter_ranges': [{'start': stage_start, 'end': stage_end}],
            'as_of': as_of,
            'revealed_at': as_of,
            'summary': new_rel.get('kind', ''),
            'claims': [],
            'facets': facets,
            'attitudes': [],
            'turning_event_refs': [],
        }
        existing_ids = {s['id'] for s in doc.get('stages', [])}
        if snap_id not in existing_ids:
            doc.setdefault('stages', []).append(new_stage)
        doc['revision'] = doc.get('revision', 1) + 1
        doc['safe_through'] = max(doc.get('safe_through', 0), as_of)
        _write_json(self.root, f'relationships/pairs/{rel_id}.json', doc)

    def _write_emotional(self, stage_id, stage_start, stage_end, as_of, es: dict):
        emo_info = es.get('emotional_ref_or_new', {})
        new_emotion = emo_info.get('new_emotion', {})
        # 总是重新分配 emo ID（Agent 的 emotion_id 是猜测，不可信）
        emo_id = self.id_alloc.allocate('emo', 1)[0]
        pair_names = new_emotion.get('pair_names', [])
        assessment = es.get('new_assessment', {})
        sm = es.get('stage_markdown', {})
        title = (sm.get('front_matter', {}).get('title') if sm else None) or \
                new_emotion.get('label') or f'{stage_id} 感情分析'
        order = self._stage_order.get(stage_id, 1)
        doc_id = f'doc-{emo_id}-stage-{order:03d}'

        # participants 从 pair_names 解析
        participants = []
        for name in pair_names:
            ref = self._resolve_name_ref(name)
            if ref:
                participants.append({'character_ref': ref, 'revealed_at': as_of})

        emo_doc = _filemeta(self.novel_id, emo_id, 'emotional_index', as_of) | {
            'label': title,
            'introduced_at': stage_start,
            'participants': participants,
            'assessments': [],
            'entries': [],
        }
        if assessment:
            assess_id = f'assessment-{emo_id}-{order:03d}'
            existing_aids = {a['id'] for a in emo_doc.get('assessments', [])}
            if assess_id not in existing_aids:
                emo_doc.setdefault('assessments', []).append({
                    'id': assess_id,
                    'revealed_at': assessment.get('revealed_at', as_of),
                    'category': assessment.get('category', 'uncertain'),
                    'status': assessment.get('status', 'uncertain'),
                    'relationship_links': assessment.get('relationship_links', []),
                })
        # 阶段条目
        entry = {
            'target': _ref(f'emotions/{emo_id}/stages/stage-{order:03d}.md', doc_id),
            'kind': 'emotional_stage',
            'title': title,
            'summary': f'{title}（第{stage_start}—{stage_end}章）',
            'chapter_ranges': [{'start': stage_start, 'end': stage_end}],
            'entity_refs': [],
            'tags': ['emotion'],
            'safe_through': as_of,
        }
        existing_docids = {e['target']['record_id'] for e in emo_doc.get('entries', [])}
        if doc_id not in existing_docids:
            emo_doc.setdefault('entries', []).append(entry)
        emo_doc['revision'] = emo_doc.get('revision', 1) + 1
        emo_doc['safe_through'] = max(emo_doc.get('safe_through', 0), as_of)
        _write_json(self.root, f'emotions/{emo_id}/index.json', emo_doc)
        # 更新 emotions 根索引
        self._append_root_entry('emotions', emo_id, 'emotional_index', title, as_of, 'emotion')

        # 阶段 Markdown
        lines = ['---',
                 'schema_version: "2.0"',
                 f'novel_id: {self.novel_id}',
                 f'id: {doc_id}',
                 'kind: emotional_stage',
                 'revision: 1',
                 f'safe_through: {as_of}',
                 f'title: {title}',
                 'chapter_ranges:',
                 f'  - start: {stage_start}',
                 f'    end: {stage_end}',
                 f'as_of: {as_of}',
                 'stage_ref:',
                 '  path: navigation/stage-plan.json',
                 f'  record_id: {stage_id}',
                 'subject_refs: []',
                 'record_refs: []',
                 'source_refs: []',
                 '---',
                 '',
                 f'# {title}',
                 '',
                 sm.get('body_markdown', '')]
        _write_markdown(self.root, f'emotions/{emo_id}/stages/stage-{order:03d}.md', '\n'.join(lines))
