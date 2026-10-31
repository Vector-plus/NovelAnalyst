---
schema_version: "2.0"
novel_id: wukon
id: doc-char-0001-stage-001
kind: character_stage
revision: 1
safe_through: 10
title: 取经路上·林中之变
chapter_ranges:
  - start: 1
    end: 10
as_of: 10
stage_ref:
  path: navigation/stage-plan.json
  record_id: stage-001
subject_refs:
  - path: characters/char-0001/index.json
    record_id: char-0001
record_refs: []
source_refs: []
---

# 取经路上·林中之变

## 阶段起点
第1章取经队伍在密林前争吵，唐僧作为被服侍的师父在场（ev-local-1）。同章他赌气脱离队伍独自入林、僧袍被扯破（ev-local-2），构成本阶段第一个行动起点：由被服侍者转为主动行动方。

## 目标与动机
- 自述所修为“大乘”“圆满”，但对具体所求“还没想好”（claim-local-14，reported），自我定位是自信而含糊的。
- 对队内关系的态度表现为赌气式对抗：以“别以为我离了你们就不行”式的独行进入林中（ev-local-2 ch1）。

## 关键选择与经历
1. 第1章 独自入林 → 第2章 与怪树搭话后被藤蔓与暗伏存在困住，以大喊救命收尾（ev-local-1/2 ch2、claim-local-18）。此处与第1章的独行宣言形成行为重复点。
2. 第3章 与绿衣女孩论佛，直接交锋小乘/大乘与“金蝉子走火入魔陷万劫”的传说（ev-local-3、claim-local-14、claim-local-15）。
3. 第4章 在万年老树残躯前发出迟暮/孤独的叹语（claim-local-22），是全阶段唯一的抒情性自我表达。
4. 第6章 被孙悟空以“既知你是谁”为由击杀（ev-local-1 ch6；claim-local-11 为直述证据）。
5. 第10章 肉身被烧坏、只剩半边（claim-local-3，由猪八戒转述）。

## 身份与能力变化
- 关系位置变化：由队伍中的“师父/被保护者”变为被本队护法者处死的对象，第10章确认为肉身损毁、需取魂魄。
- 第3章出现“金蝉子”一说，但只是他人质疑中的传说，本阶段**未明示**金蝉子与唐僧是否同一，故不作身份合并。

## 认知与性格表现
- 对自身佛法定位自信（修大乘、修圆满），但在实际危险面前立刻转为呼救，独行与依赖交替出现。
- 缺乏对林中风险的判断，被陌生存在以对话拖住；面对怪树的自述（几千年猴群、三百年前被吃）未有反向质询记录。

## 阶段终点
身死：第6章被击杀，第10章肉身只剩半边，魂魄待取（孙悟空离队赴地府，ev-local-1 ch10）。

## 证据不足与补读入口
- 本 doc 仅依据 stage_buffer 中的事件/陈述 Ref 组织，未读原文；ev-local-* 为 stage 内局部 id，需落库层解析到 ledger。
- “绿衣女孩”“林中女子”是否为同一存在，以及与阿瑶的关系，本阶段无证据，不作合并。
- claim-local-14“还没想好”的完整语境、以及第6章“你是谁”所指，均需补读第3—6章。
