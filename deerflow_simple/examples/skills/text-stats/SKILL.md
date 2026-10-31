---
name: text-stats
description: 统计文本的单词数、字符数、行数
---
# 文本统计技能

当你需要统计一段文本的单词数 / 字符数 / 行数时：

1. 先把文本用 `write_file` 写入沙箱文件（如 `input.txt`）。
2. 用 `bash` 执行 `wc input.txt` 查看统计结果。
3. 报告统计结果。
