# 涌现式活世界设计：LLM 世界生成 + 半自主 NPC + 张力状态机 + 终态结局

> 日期：2026-06-21
> 项目：`llmud`（LLM 驱动的修仙 MUD）
> 状态：待用户审阅
> 范围：把现有「手写固定主线节拍」的验证切片，升级为「LLM 生成世界圣经 + 半自主 NPC + 张力状态机 + 终态原型涌现结局」的中度涌现模拟，做成中等规模可玩的单机产品。
> 前置文档：`2026-06-17-llmud-tracer-slice-design.md`（穿透切片）、`2026-06-18-living-world-design.md`（活世界事件池）

---

## 1. 背景与目标

### 1.1 现状

切片 + 部分活世界已落地：`classify → engine → world → dm → npc` 管线、5 场景链、3 NPC（linwaner/chenhao/old_yang，含记忆与好感度）、1 妖兽遭遇、引擎驱动的线性所务弧（venture_bamboo→probe_anomaly→cultivate_breakthrough→venture_mountain）、流式叙事、H5 面板（场景/地图/角色/所务）、内容权威约束（DM 只能述及系统已有之物）。

### 1.2 本次方向（已在头脑风暴确认）

- **留存主轴**：成长/陪伴/探索三轴混合，由主线串起。
- **世界来源**：LLM 建立世界架构与主要世界事件，结合玩家选择与各 NPC 个性/行为方式，涌现出**未预先确定但合理**的结果。
- **世界生成时机**：里程碑再生——开局生成世界圣经，每过一大阶段基于当前状态再生下一阶段张力。
- **结局模型**：终态原型涌现结局——预定义一小批终态条件，模拟推进到撞上某个终态为止，LLM 据全程历史写终章；分支不需各自手写结局。
- **本版本仍是单机**：异步社交层（F）与平台/运营（G）继续延后。

### 1.3 目标与成功标准

一个中等规模可玩产品，玩家在一次完整游玩中能够：

1. 体验一条由自己选择与 NPC 反应长出的、没被预写的主线（涌现感）；
2. 感受到世界在自己不在时也走了（离线成长 + 活世界）；
3. 在线时进入心流（清晰近端目标 + 挑战匹配 + 即时反馈）；
4. 被情感纠葛触动（求不得/失所有…），且这些情感有因果、不强行卖惨；
5. 走到某个合理终态结局，终章与全程自洽。

---

## 2. 核心原则：骨/皮再平衡

现有铁律「引擎定骨、LLM 披皮」不变，但**职责重心移动**：

- 旧骨 = 引擎编**剧情节拍**（固定所务弧）。
- 新骨 = 引擎**守住世界自洽** + 算数值：LLM 提议世界变迁，**校验器**钳制在「活跃 canon + 已发生事实 + NPC 人格 + 因果」之内。
- 皮 = LLM 在 canon 内**提议涌现结局**并叙述。

引擎权威不退场，从「编剧情」转为「守自洽」。我们刚加的「只述已有之物」约束是校验器的一小部分，将被泛化到 world_delta。

---

## 3. 架构与管线

在现有 `classify → engine → world → dm → npc` 上扩展：

```
POST /game/action
  ① classify      意图识别（不变：规则优先 + LLM 兜底）
  ② engine        确定性数值结算（不变：修炼/战斗/移动的数）
  ③ world tick    【新】
       ├ 推进 tick
       ├ 规则驱动 NPC step（按 LLM 写好的行为模型更新 npc_state，不调 LLM）
       ├ 张力状态机：按条件激活/升级/解决主要事件张力
       └ 世界压力累积（满了触发里程碑再生）
  ④ outcome resolve  【新·皮】LLM 在「canon + 世界态 + 玩家行动 + 活跃张力 + npc_state」约束下，
                     提议 story + state_delta(玩家) + world_delta(张力/npc/势力) + npc_update
  ⑤ validate      【新·骨】校验器：查 canon + 人格一致 + 因果合理 + 数值；违规钳制或重试一次
  ⑥ apply         应用通过校验的增量到 玩家/世界/NPC，持久化
  ⑦ ending check 终态原型命中？→ 进入终章模式，封存世界
  ⑧ milestone check 世界压力≥阈值且无活跃张力在解决中？→ worldgen 再生下一阶段 canon
  ⑨ stream story  流式输出（不变）
```

**与现有代码的边界**：`classify / engine / dm 流式 / npc 记忆 / SQLite 仓储`全部沿用；新增 `worldgen/`（LLM 世界生成）、扩展 `engine/world.py`（张力状态机 + NPC 行为 step + 世界压力 + 离线推进）、新增 `engine/validator.py`（结算校验器）、新增 `engine/offline.py`（离线 tick 推进）、扩展 `engine/models.py`（WorldBible/WorldState/Tension/BehaviorModel/NPCRuntimeState/TerminalArchetype）。现有手写 `SCENE_MAP/ALL_EVENTS/ALL_NPC_PROFILES` 作为 phase-0 canon 直接复用，不推翻。

---

## 4. 世界生成层 `worldgen/`

LLM 驱动、里程碑触发。产出一份 **WorldBible** = 当前阶段的活跃 canon。

**关键：phase-0 不调 LLM**——直接把现有手写 `SCENE_MAP/ALL_EVENTS/ALL_NPC_PROFILES` 翻译成 phase-0 WorldBible（现有内容零浪费）；**LLM worldgen 从 phase-1 起**（里程碑再生时）才调用。

```python
class WorldBible(BaseModel):
    phase_id: int                 # 0=种子，每次再生 +1
    phase_title: str              # "练气篇" / "筑基风云"
    scenes: list[SceneSpec]       # 本阶段场景（phase-0 = 现有 5 场景）
    factions: list[FactionSpec]   # 势力：青云门/散修盟/妖兽潮…
    tensions: list[TensionSpec]   # 主要世界事件 = 张力（核心，见下）
    npc_models: list[BehaviorModel]  # NPC 行为模型
    ending_hints: dict            # 本阶段推动哪些终态原型
```

**TensionSpec（主要世界事件 = 张力）是涌现主线的心脏**——每个张力有触发条件、参与方、**多条可能解决方向**，但**不预设走哪条**：

```python
class TensionSpec(BaseModel):
    id: str                       # "mountain_beast_surge"
    name: str                     # "妖兽潮涌动"
    axis: list[str]               # ["探索","成长"] — 它编织哪几轴
    emotion: str                  # 求不得/爱别离/怨憎会/失所有/得而复失/背叛/牺牲/执念（八苦味）
    involved_npcs: list[str]
    involved_factions: list[str]
    trigger: TensionTrigger       # 激活条件（stat/tick/他张力已解决/npc_state）
    resolution_paths: list[ResolutionPath]  # 多条解决方向，各带判定 + 终态倾向
    pressure_weight: int          # 活跃未决时对 world_pressure 的贡献
    difficulty: int               # 难度标定，供心流调节

class ResolutionPath(BaseModel):
    id: str                       # "rally_sect" / "sneak_strike" / "parley"
    label: str
    condition: dict               # 玩家/世界态满足什么即走此路
    outcome_state: dict           # 走此路产生的 world_delta
    ending_lean: str | None       # 它推向哪个终态原型
```

走哪条 path 由模拟涌现，不预写结局——这就是「未预先确定但合理」的落点。

---

## 5. 世界状态模型（`engine/models.py` 扩展）

```python
class WorldState(BaseModel):
    tick: int
    phase_id: int
    world_pressure: int           # 累积；≥阈值触发里程碑再生
    tensions: dict[str, TensionRuntime]
    npc_state: dict[str, NPCRuntimeState]
    faction_state: dict[str, FactionRuntime]
    resolved_tensions: list[ResolvedTension]   # 喂给再生 + 终章
    sealed: bool = False          # 终态命中后冻结世界
    ending: str | None = None

class TensionRuntime(BaseModel):
    status: str                   # dormant | active | resolved
    pressure: int                  # 张力内部升级度
    progress: dict[str, int]       # 每条 resolution_path 的接近度 0..100
    activated_tick: int | None
    resolved_tick: int | None
    resolved_path: str | None

class NPCRuntimeState(BaseModel):
    npc_id: str
    scene_id: str
    mood: str                      # 心境 tag
    goal_progress: dict[str, int]  # goal_id → 0..100
    schedule_tick: int             # 上次自主步 tick
    last_autonomous_action: str | None
    # 好感度/关系阶段仍存 NPCRepository（不变）

class ResolvedTension(BaseModel):
    tension_id: str
    resolved_tick: int
    path_id: str
    summary: str                  # 一行结果，供再生上下文 + 终章

class FactionRuntime(BaseModel):
    faction_id: str
    trust: int                     # 与玩家/彼此关系
    dominance: int                # 用于「一统」终态判定
```

`WorldState` 持久化进 SQLite（扩展现有仓储）。

---

## 6. NPC 行为模型与半自主 tick

```python
class BehaviorModel(BaseModel):
    npc_id: str
    motive: str
    goals: list[NPCGoal]          # 按优先级，每个标 axis（它帮编织哪轴）
    triggers: list[BehaviorTrigger]
    routine: list[BehaviorAction] # 惯常 tick 行为（移动/静修/打探）
    decision_rules: list[str]     # 规则步可判定的简明规则

class NPCGoal(BaseModel):
    id: str
    label: str
    axis: str                      # 成长/陪伴/探索
    satisfy_condition: dict
    progress_driver: dict           # 什么世界事件推它的进度
    tragic_potential: str | None    # 此目标可能终结于失去/求不得（情感弧种子）

class BehaviorAction(BaseModel):
    type: str                       # move | mood | goal_progress | interact_npc
    params: dict
    condition: dict                 # 何时执行
```

**`engine/world.py::npc_step(world_state, behavior_models)`**——纯函数、可单测：对每个 NPC，按 `routine` 中 `condition` 成立的动作执行（按 schedule 移动、心境迁移、goal_progress 推进）。**完全由行为模型 + 世界态决定，不调 LLM**。LLM 只在第 ④ 步玩家卷入活跃张力或某 NPC 时才结算。这把「活世界感」与「每 tick 多次 LLM 调用」的成本切开。

---

## 7. 世界压力与里程碑再生

- `world_pressure` 由：活跃未决张力 × `pressure_weight`、张力升级、玩家突破等累积；**心流调节**会动态调整其升速（见 §11.2）。
- 当 `world_pressure ≥ REGEN_THRESHOLD` **且**没有活跃张力正处于解决中途 → 触发 worldgen 再生下一阶段 WorldBible，合入 canon（保留 `resolved_tensions` 历史），`world_pressure` 归零，`phase_id += 1`。
- 再生喂入上下文：`resolved_tensions` 全史 + 当前世界态摘要 + 玩家态，使新张力从旧张力结果长出（因果链）。

---

## 8. 结算校验器 `engine/validator.py`

DM 契约扩展一个 **`world_delta`** 字段（张力/NPC/势力增量）：

```json
{ "story":"…",
  "state_delta": {"spirit_power":2,"hp":-5},
  "world_delta": {
    "tension": {"mountain_beast_surge": {"pressure":+1, "progress":{"rally_sect":+10}}},
    "npc":     {"chenhao": {"mood":"eager","goal_progress":{"venture":+5}}},
    "faction": {"散修盟": {"trust":+2}}
  },
  "combat": null, "breakthrough": null, "npc_update": {...} }
```

`validate_dm_proposal(proposal, world_state, world_bible, player, engine_result) -> (clamped, violations, retry)` 逐项钳制：

1. **Canon 校验**（泛化「只述已有之物」）：story/world_delta 里点名的场景/地标/物品/NPC/敌人/势力/张力必须在活跃 WorldBible 内。出现断崖洞窟/三叶血兰/铁背蜥 → 丢弃该 world_delta 键；story 违规由提示词规则 12 预防 + 事后扫描记日志。
2. **人格一致**：NPC 心境/行动须与 BehaviorModel.motive/goals + 当前 npc_state 相容；明显矛盾（豪冲师兄突然怯战）→ 钳为人格内替代或丢弃。
3. **因果合理**：world_delta 须由玩家行动 + 活跃张力推出（无关 修炼 不能让某张力进度跳 +50）；**情感同样受约束**：失所有要有因果，不能无缘无故。
4. **数值边界**：progress 0..100、pressure ≥0、favorability 0..100；战斗/突破数值以 engine_result 为准（沿用现有铁律）。

**流式与校验的边界**：story 实时流、不能中途撤回 → **story 走预防（提示词规则 12）+ 事后扫描记日志**，不中途钳；**world_delta/state_delta/npc_update 不流式、在 LLM 完成后解析**，可**完整校验 + 钳制 + 重试一次**再应用。于是「骨」（世界态完整性）由 world_delta 校验守住，不受流式牵制。结构性违规 → 重试一次（提示词点名「你提到了不在设定中的『断崖洞窟』」），仍失败则钳 + 留有效部分 + 记日志。

---

## 9. 终态结局层

```python
class TerminalArchetype(BaseModel):
    id: str            # "ascension"
    name: str          # "飞升成仙"
    condition: dict    # 对 (player, world_state, resolved_tensions) 的判定
    finale_guidance: str  # 给终章 LLM 的指引（含情感主题）
    priority: int     # 平局时判定顺序
```

起始小集（可扩，横跨甜/苦/悲情感光谱）：`ascension`飞升 / `fall`陨落 / `hermit`归隐 / `demonic`入魔 / `unifier`一统 / `wanderer`行遍天下（兜底中性） / `unrequited`求不得（得道失人）。

`check_ending(player, world_state, archetypes)`——纯函数，按 priority 判定，返回首个命中或 None。命中即：`world_state.sealed=True`、`ending=id`，停止再生与应用 world_delta；一次**终章 LLM 调用**拿「resolved_tensions 全史 + 玩家态 + finale_guidance」生成终章（流式）；响应带 `ending:{id,name}` 供前端渲染结局卡、封存本轮。

---

## 10. 三轴主线编织 + 所务迁移

主线 = 世界圣经跨阶段的**张力脊柱**。每条张力带 `axis` 标签，一条可织多轴（「师姐身世」=陪伴+探索；「妖兽潮」=成长+探索）。里程碑再生把 `resolved_tensions` 喂回 worldgen，使新张力从旧张力结果长出——**因果链 + 终态倾向**给主线方向；玩家选择决定**哪些张力激活、按何序解决、走哪 path**——主线形态涌现，没预写。三轴不各成一线，而是每条张力天然带轴，玩家解张力时同时推三轴。

**所务系统迁移**：现有手写 `GOALS/current_goal` 退化为「当前最该关心的活跃张力」的引擎投影——仍从状态确定性推导，但数据源从固定 GOALS 换成活跃张力。phase-0 保留现有 4 个 venture_* 目标映射到 phase-0 张力；后续阶段从 LLM 张力派生。

---

## 11. 玩家体验三要素

### 11.1 挂机成长（离线世界继续转，角色自修）

天然贴合半自主 tick——**离线 = 把规则驱动世界模拟往前跑 N 个 tick，不调 LLM、零成本**：

- `last_seen` → 回归时算「离线 tick 预算」=真实经过×速率，**有上限**（防挂机刷穿，如封顶 8h 量）。
- 离线只跑**规则驱动**：玩家按预设「挂机策略」(闭关/历练/静养，默认闭关) 自修灵力(封顶)、npc_step、张力机——**张力可自升自解，世界在你不在时也走了**。**不调 LLM 结算**（无玩家行动）、**不触发终态**（结局要人在场）。
- **挂机策略只影响规则驱动的成长速率与被动推进的张力类型，不触发任何战斗结算**：闭关=最高灵力自修速率、不碰张力；历练=灵力速率中等、被动推进「探索/成长」轴张力进度（但不自动战斗、不结算遭遇）；静养=最低速率、缓慢恢复气血。三条策略都**不调 LLM、不破境、不触发终态**，保证离线体验可预期。
- 回归时一张「离线期间」catch-up 卡：灵力+X、世界发生了什么。一次轻量 LLM 概括或模板化。
- **突破不离线**：突破是时刻、要人玩；离线只攒灵力不破境。
- 新增：`engine/offline.py::advance_offline(player, world_state, now, directive)` 纯函数（可单测）；Player 加 `offline_directive` 字段；前端挂机策略选择 + 离线卡。

### 11.2 心流（在线时进入 flow）

设计原则 + 一个调节杠杆：
- **清晰近端目标**：所务=当前最该关心的张力，永远可见（panel 已有，强化成「下一步」）。
- **挑战-技能匹配（flow 通道）**：张力 `difficulty` 随境界/灵力标定；玩家碾压→再生加压（无聊侧）；吃力→软引导给更易路径（焦虑侧）。新增轻量「心流调节」：engine 记近期挑战结果，动态调 `world_pressure` 升速 / 张力 trigger 门槛。
- **即时反馈**：流式 story + 状态面板 + 战报/突破卡（已有），保低延迟。
- **低摩擦**：预填 chip、常驻场景面板、一键行动（已有，继续打磨）。
- **不被硬打断**：叙事连续、世界事件融进 story（规则 8）；只在有意义抉择处给介入选项。
- **掌控感+发现感**：选择可见地推张力进度 → 代理感。

### 11.3 情感纠葛（求不得/失所有…代入感）

结构性支持 + 内容主题：
- **张力带情感主题**：TensionSpec.`emotion`（求不得/爱别离/怨憎会/失所有/得而复失/背叛/牺牲/执念，八苦味）。worldgen 被指示编织这些；phase-0 手写张力也标主题。
- **NPC 弧线有悲剧潜能**：现有秘密（师姐私生女/陈浩禁术/杨老隐退）是种；行为模型 `tragic_potential` 字段标记 goals 可终结于失去/求不得。同伴可能陨落、离去、背叛——不总大团圆。
- **结局横跨情感光谱**：终态原型含甜/苦/悲（见 §9）；finale_guidance 带情感主题。
- **代入感**：师姐跨会话记忆(她记得你) + 情感 key_facts；情感权重由模拟涌现（玩家选择 + NPC 本性），**loss 必须 causally earned**，不强行卖惨——校验器的「因果合理」同样约束情感。

---

## 12. 错误处理

- **world_delta canon 违规**：钳制 + 记日志 + 重试一次（点名违规）；仍失败 → 留有效部分 + 记日志，继续。
- **story 违规（已流式）**：不能撤回 → 记日志 + 写入世界态上下文（供再生/终章知情）+ 可附一条矫正系统注。
- **worldgen 失败/产出非法 bible**：保留上一阶段 canon（世界不崩）+ 记日志，下次里程碑再试；绝不应用非法 bible。
- **里程碑再生撞上张力解决中途**：§7 已设闸——仅无活跃张力在解决中时再生；否则挂起等解决。
- **校验/LLM 重试耗尽**：退回引擎确定性 story（现有 `story_fallbacks`），该轮 `world_delta={}`（坏提议不污染世界）；规则驱动的 npc_step + 张力机仍照跑，世界不停滞。
- **终态误判**：终态条件是严格谓词、单测覆盖；sealed 不可逆，故判定保守。
- **状态漂移**：`resolved_tensions` + 轻量世界日志给再生/终章提供上下文，有界大小。
- **离线异常**：离线 tick 预算超上限则截断；离线不破境、不触发终态，保证回归体验可预期。

---

## 13. 测试策略

**单元（确定性、无 LLM）——主体**：
- `npc_step`（routine/schedule/goal_progress）、张力状态机（dormant→active→resolve、path 选择、progress）、`world_pressure` 累积与再生闸、`validate_dm_proposal` 各钳制规则与 retry 标志、`check_ending` 各原型与优先级、所务从活跃张力派生、canon 约束扩展到 world_delta 实体、`advance_offline`（预算截断、不破境、不触发终态、张力自走）。

**集成（MockLLM，不耗 token）**：
- worldgen 产出 → WorldBible 解析 + schema 校验；phase-0 从现有数据种子化；结算 + 校验用预设提议（合法通过 / 违规格化重试 / 因果断裂拒绝）；里程碑再生全流程；终态命中 → 终章 → sealed；完整一行动端到端（沿用现有 MockLLMClient 模式）；离线回归 catch-up 流程。

**实机（手动/可选，耗 token）**：跑到结局的一轮通关；长线漂移观察（世界是否保持自洽）；再生质量；心流/情感主观体验。

---

## 14. 范围 IN / OUT

**IN**：WorldBible canon（phase-0 种子 + LLM 再生）/ WorldState（张力·npc·势力·压力）/ 规则驱动半自主 NPC tick / 结算校验器（流式感知分流）/ 终态原型 + 终章 / 张力脊柱编织三轴 / 所务迁移到张力派生 / 挂机离线成长 / 心流调节杠杆 / 情感主题与悲剧弧 / **单机**。

**OUT（延后）**：每 tick LLM 生成式代理（方案三）、异步社交层 F、鉴权/支付/运营 G、向量 RAG（C 加深，记忆不足再上）、开局每玩家独立 worldgen（phase-0 用共享手写种子）、实时多人。

---

## 15. 落地里程碑（每个可独立测，LLM 风险后置）

- **M1 世界状态骨架**：WorldState/TensionRuntime/NPCRuntimeState 模型 + SQLite + 空世界 tick 接入管线（规则驱动 npc_step + 张力机桩）。phase-0=现有数据，行为不变。测：状态迁移、npc_step、压力。
- **M2 张力状态机 + 所务迁移**：TensionSpec/ResolutionPath、张力机、所务从张力派生（phase-0 映射现有 4 目标）；TensionSpec 加 emotion/difficulty。测：张力机、所务派生。仍无 LLM worldgen。
- **M3 结算校验器**：canon/人格/因果/数值钳制；DM 契约加 world_delta；流后校验接入。测：校验规则（MockLLM）。
- **M4 终态结局层**：原型集 + check_ending + 终章 LLM + sealed + 前端结局卡。测：谓词、sealed 流程。
- **M5 世界生成 + 里程碑再生**：worldgen/ 模块、WorldBible schema 校验、再生触发、phase-0 种子。**首次 LLM worldgen 上线**，风险隔离到最后。
- **M6 挂机离线成长**：advance_offline + offline_directive + catch-up 卡 + 前端。测：离线预算/不破境/不触发终态。
- **M7 涌现主线串起 + 心流/情感打磨**：resolved_tensions→再生跨阶段张力脊柱；phase-1+ NPC 行为模型 author；心流调节；情感主题落地；端到端通关 + 漂移观察；调压力/再生/心流阈值。

---

## 16. 待验证假设与风险

| 假设 | 验证 | 风险 |
|---|---|---|
| LLM 能稳定产出合规 WorldBible | M5 集成测试 + 实机 | bible 非法/漂移；缓解：schema 校验 + 保留旧 canon + 重试 |
| 校验器能挡住世界态漂移 | M3 单元 + 长线漂移观察 | 钳制过严卡死涌现、过松漂移；缓解：分级钳制 + 可调阈值 |
| 张力脊柱能产生「像主线」的体验 | M7 实机通关 | 张力散乱无主线感；缓解：因果链喂回 + 终态倾向收束 |
| 离线成长不破坏平衡 | M6 单元（预算封顶）+ 实机 | 挂机刷穿/世界在离线时失控；缓解：封顶 + 不破境 + 不触发终态 |
| 情感有因果不卖惨 | 校验器因果规则 + 实机 | 强行悲剧出戏；缓解：loss 必须 causally earned |
| 心流调节不振荡 | M7 实机 | 加压/减压反复横跳；缓解：滞回区 + 慢调节 |

---

## 17. 已决策项

| 编号 | 决策 | 理由 |
|---|---|---|
| D1 | 留存主轴=三轴混合主线串起 | 用户确认；陪伴不再独占变现抓手 |
| D2 | LLM 建世界 + 主要事件，涌现结局 | 用户核心诉求 |
| D3 | 世界生成时机=里程碑再生 | 生长感 + 分段锁一致性折中 |
| D4 | 结局=终态原型涌现 | 可工程化、分支不需各自结局 |
| D5 | 架构=方案二（半自主 NPC + 张力状态机） | 真涌现又可控可测，建在现有之上 |
| D6 | 本版本单机 | 异步社交 F 延后，沿用原 vision |
| D7 | phase-0 复用手写数据、不调 LLM worldgen | 零浪费 + 风险后置 |
| D8 | 校验器分流：story 预防+事后扫描、world_delta 完整校验 | 适配流式，守住骨 |
| E1 | 挂机离线成长（规则驱动、封顶、不破境、不终态） | 玩家体验诉求；零 LLM 成本 |
| E2 | 心流调节杠杆（动态调压力/门槛） | 在线 flow 体验 |
| E3 | 张力 emotion + NPC tragic_potential + 结局光谱 | 情感纠葛代入感，因果约束 |