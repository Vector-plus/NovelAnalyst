---
schema_version: "2.0"
novel_id: wukon
id: doc-char-0002-stage-001
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
  - path: characters/char-0002/index.json
    record_id: char-0002
record_refs: []
source_refs: []
---

# 取经路上·林中之变

## 阶段起点
第1章密林前队伍争吵中在场（ev-local-1）。其动机从一开始就带有个人化执念：自述“只有看晚霞才能坚持向西走”（claim-local-4，reported）。

## 目标与动机
- 显性目标：捕妖换取“功德分”（claim-local-2，reported），行动理由直白而功利。
- 自述五百年关押与“赎罪三件事”的框架（ev-local-1 ch5、claim-local-8，reported）。
- 以金箍为由自述不自由（claim-local-15，ch8）。

## 关键选择与经历
1. 第3章 凌空赶到林中之变现场（ev-local-4 ch3），衔接唐僧被困的危机。
2. 第4—5章 与认出他的女子对话：女子称已等数万年、“逃不出他的掌心”（claim-local-14），并说“他已记不得一切”（claim-local-12）；其“你就是……”被打断。
3. 第5章 举棒未落、放过女子（ev-local-2 ch5）——本阶段最重要的自我克制，也是人物转折点。
4. 第6章 以“她说了我是谁，也说了我们每一个人是谁”为由击杀唐僧（ev-local-1、claim-local-8），随即闪电引燃森林、纵身离去（ev-local-2）；同章自述“又犯了一桩天条”（claim-local-12），暗示此前已有前科。
5. 第8章 归来追问师父下落，得知唐僧已死且有人冒充他行凶（ev-local-1 ch8、claim-local-12 ch8）；与猪八戒林中争吵互骂（ev-local-2 ch8）。
6. 第10章 离队赴地府取唐僧魂魄（ev-local-1 ch10）。

## 身份与能力变化
- 第5章“四大魔王名号清单”中被列入“齐天大圣美猴王”（claim-local-10，reported）——属名号层面的身份信息，本阶段未观察到新能力。
- 金箍的约束性被本人明言（claim-local-15）：行动自由受限是其自我认知的一部分。

## 认知与性格表现
- 自保与杀伐并存：放过女子（第5章）与击杀师父（第6章）相邻发生，判断依据是自己听到的“身份”陈述，处置果断且不留缓冲。
- 对“我是谁”的答案依赖外部叙述，自身记忆存在缺口（女子“他已记不得一切”），这一缺口直接影响其行为选择。
- 对师父之死的反应以“追问—推断”为主，情绪表现弱于猪八戒一侧。

## 阶段终点
脱离取经队伍，独自赴地府取唐僧魂魄（第10章），本阶段末处于离队状态。

## 证据不足与补读入口
- 女子所称“你是谁”的具体内容本阶段未给出（claim-local-8 为角色自述且被截断），需补读第5—6章。
- 第4章“积功德分”与第5章“赎罪三件事”之间的关系未在 buffer 中说明。
- ev-local-* 为 stage 内局部 id，需落库层解析到 ledger。
