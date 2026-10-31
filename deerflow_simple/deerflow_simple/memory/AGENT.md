# Memory 模块决策记录

## 设计原则
- 参考 deer-flow `deermem` 实现，按 deerflow-simple 的极简风格落地，只保留实用核心，不引入企业级复杂度。

## 核心机制（6 点）
1. **结构化抽取**：LLM 输出 JSON（`content` / `category` / `confidence`），对应 deermem 的 `fact_extraction.yaml`。
2. **纯寒暄过滤**：正则过滤「嗯/好的/谢谢/收到」等确认语，避免触发无意义抽取（对应 `filter_trivial`）。
3. **置信度阈值**：`memory_confidence_threshold=0.7`，低于阈值不存储（对应 `fact_confidence_threshold`）。
4. **去重**：精确去重 + 包含关系合并（对应 `fact_dedup`）。
5. **容量驱逐**：`memory_max_facts=50`，超限按 confidence 降序保留（对应 confidence 驱逐策略）。
6. **注入裁剪**：`memory_injection_max_facts=20`，`get_context` 按 confidence 降序取前 N 条（对应 `max_injection_tokens` 的条数化简化）。

## 关键决策
- **去重策略取舍**：最初尝试 deermem 的 token-Jaccard 思路（简化为字符 bigram Jaccard），但实测对中文短句效果差（「用户叫小明」vs「用户名字是小明」相似度仅 0.25，漏判）。且 deermem 的 `fact_dedup_enabled` 默认就是 `False`。故改用对中文更可靠的「精确去重 + 包含关系合并」。
- **事实结构**：`{id, content, category, confidence, created_at}`。旧格式 `{id, content, created_at}` 加载时自动补默认值（`category="context"`, `confidence=0.5`），保证向后兼容。
- **配置项默认值**：`memory_max_facts=50`、`memory_confidence_threshold=0.7`、`memory_injection_max_facts=20`，均可通过 `SimpleConfig` 覆盖。

## 刻意保留的简化（暂未引入）
- debounce 队列、信号检测（correction/reinforcement 等 6 类）、hybrid-v1 多信号驱逐、staleness 时效审查、FTS5 检索索引。
- 上述均属企业级复杂度，当前 6 个机制已覆盖「记忆无用信息 + 限制数量」的核心诉求。若后续记忆质量仍需提升，可优先引入信号检测（仅对有信号的对话抽取）以进一步减少 LLM 调用次数。