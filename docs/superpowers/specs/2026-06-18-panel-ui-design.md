# 面板化 UI 设计：让场景的时间/地点/人物/事件可触达

**日期：** 2026-06-18
**状态：** 待评审
**范围：** 在现有「活世界」骨架之上，把当前场景的时间、地点、人物、事件做成可操作面板，并升级「所务」为可见的任务清单。不触碰引擎结算与叙事管道的核心逻辑。

---

## 1. 背景与目标

当前前端是仿微信聊天的单页 H5：顶部状态条（地点/境界/灵力/所务）+ 聊天气泡 + 输入栏。世界已经「活」了（5 场景、3 NPC、事件池、所务），但玩家只能通过自然语言输入触达一切——看不到在场的具体人物及其状态、看不到场景里有哪些可交互的物件、看不到地图全貌、看不到完整的所务线。信息全靠叙事文本带出，操作全靠玩家自己想词。

**目标：** 在不破坏叙事沉浸的前提下，把场景信息结构化成面板，让玩家「看得见、点得到」。面板操作仍走自然语言管道，引擎仍是唯一真源。

**核心原则不变：** 引擎决定发生了什么（骨头），LLM 决定怎么讲（皮肤）。面板只是「骨」的可视化与操作入口，不自行改状态。

---

## 2. 总体信息架构（布局 A · 叙事为脊柱）

聊天叙事始终占满全屏，保留现有微信式气泡 + 顶部状态条 + 输入栏。状态条下方新增一行 **三个 chip：角色 / 地点 / 地图**。点 chip 从底部上滑唤起对应**抽屉面板**（bottom sheet），覆盖在叙事之上；点遮罩或下拉即收起，回到叙事。一次只开一个面板。

- 叙事不被挤压，MUD 沉浸感保留。
- 面板是「按需呼出」的，不常驻、不抢空间。
- 桌面端不做分栏适配（见 §10 范围排除），仍按移动 H5 单列。

---

## 3. 交互模型（A · 预填输入栏）

所有面板里的可点项**只把自然语言预填进输入栏**，不自动发送。玩家可改可发。

| 点了什么 | 预填内容 |
|---|---|
| 地点面板 · 地标「柴房」 | `查看柴房` |
| 地点面板 ·「→ 青云门内门」 | `去内门` |
| 人物 · 林婉儿「搭话」 | `和林婉儿搭话` |
| 人物 · 林婉儿「自由聊天」 | `对林婉儿说：`（并聚焦输入栏） |
| 地图 · 点亮的「→前往」 | `去<场景短名>` |
| 角色 · 行囊「凝露草」 | `查看凝露草` |
| 角色 · 「打坐修炼」快捷 chip | `修炼` |
| 角色 · 所务条目 | 朝该所务方向的引导语（如 `静心修炼`） |

**为什么预填而非直发：** 所有操作仍走 `classify → engine → world → dm` 管道，引擎仍验证可达性、仍结算战斗、仍判定突破。面板不开后端分支、不引入结构化入参，骨架零改动。叙事连贯，玩家始终知道自己「说了什么」。

---

## 4. 三个面板

### 4.1 角色面板（合并：所务 + 我 + 人物）

自上而下三段：

**① 所务清单**（见 §5 机制）
- 每条所务一个条目：未完成空框、当前进行中蓝光高亮、已完成划掉并半透明。
- 已完成条目标「将隐去」，超过 6 个 tick 后从清单移除。
- 底部灰字预告下一条待解锁所务（如「突破后将解锁：深入妖兽山脉…」），暗示剧情会继续展开。

**② 我的属性**
- 境界、灵力（带至下境进度，如 `12 / 30 至练气二层`）、气血条、灵根、时辰（辰制，见 §8）、行囊（物品标签，可点预填查看）。
- 一个「打坐修炼」快捷 chip（最高频动作）。

**③ 人物**
- 在场 NPC 卡片：身份（师姐/师兄/守门人）、好感度条、关系阶段、状态描述、操作按钮（搭话 · 自由聊天 · 切磋[境界不足置灰]）。
- 不在场 NPC：半透明列出，标常驻场景（如「常驻 修士集市」）。

### 4.2 地点面板

- 场景名 + 氛围。
- 场景描述段落，其中**可交互地标**（柴房、练功场、祭坛、灵泉…）渲染为下划线链接，点击预填查看/前往。
- 「可交互物件」标签组：地标 + 可做动作（如「练功场 · 修炼」）。
- 「可前往」标签组：来自当前场景 `connections`，点击预填移动。
- 「当前异象」：上次 action 响应里的 `world_event`（前端持有），首次加载或无异象则隐藏该区。

### 4.3 地图面板

- 5 场景图谱（列表式节点，非图形连线——见 §10 排除图形化）。
- 当前场景蓝光高亮、标「你在此」。
- 相邻可达场景点亮、标「→ 前往」，点击预填移动。
- 不可达场景置灰、标「需经 X」，不可点。
- 可达性严格来自引擎 `connections`，前端只渲染、不判定。
- 底部「所在场景地标」一行（同地点面板的地标）。

---

## 5. 所务任务清单机制（核心新增）

把现有「单条当前所务」升级为**可见、随剧情演化的任务清单**。仍完全由引擎确定性驱动，LLM 只叙事、不加任务。

### 5.1 任务定义

每个所务是数据-only 的 `QuestDef(id, label, guidance)`，其「解锁条件」与「达成条件」以函数形式按 id 注册在 `engine/world.py`（仿现有 `_goal_satisfied` 模式，不放进 Pydantic 模型）。

所务链（沿用现有 GOALS 内容，改用解锁门控可见性）：

| id | label | 解锁条件 | 达成条件 |
|---|---|---|---|
| `venture_bamboo` | 往内门寻林婉儿，同探幽竹林 | 游戏开始即解锁 | 到过 `bamboo_forest` |
| `probe_anomaly` | 查探竹林中的灵草异气 | 到过 `bamboo_forest` | 见过 `spirit_herb` 事件 |
| `cultivate_breakthrough` | 参悟机缘，突破练气期二层 | 见过 `spirit_herb` | 境界 == 练气期二层 |
| `venture_mountain` | 深入妖兽山脉，试炼身手 | 境界 == 练气期二层 | 到过 `mountain_range` |

「解锁条件」由引擎按玩家状态判定：满足且尚未在清单中 → 新增为 `active`。这就是「根据故事发展会增加」，完全确定性，不靠 LLM。

### 5.2 运行时状态（持久化）

`Player` 新增 `quests: list[QuestState]`：

```python
class QuestState(BaseModel):
    id: str
    status: str            # "active" | "completed"
    unlocked_tick: int
    completed_tick: int | None = None
```

`db/connection.py` 加迁移 `_migrate_add_column(conn, "players", "quests", "TEXT", "'[]'")`；`db/repository.py` 读写 JSON。

### 5.3 每次 action 的所务结算（在 world 层，确定性）

1. **解锁**：对每个 `QuestDef`，若解锁条件满足且不在 `player.quests` → 追加 `QuestState(status="active", unlocked_tick=tick)`。
2. **达成**：对每个 `active` 所务，若达成条件满足 → 改 `status="completed"`、记 `completed_tick=tick`。
3. **过期**：移除 `completed` 且 `tick - completed_tick >= 6` 的条目（从可见清单消失，状态仍由引擎掌控，不再计入当前所务）。
4. **当前所务**：`current_goal =` 清单中第一条 `active`（按所务链优先序）——与旧「第一条未满足」行为一致，供 DM 引导与状态条单行展示。

### 5.4 DM 引导不变

DM prompt 仍只收「第一条 active 所务」的 `guidance`（§现有规则 10）。已完成/未解锁的不进 prompt。突破仍由引擎决定（规则 11）不变。

---

## 6. 命名 NPC 定向（小增强，随「自由聊天」纳入）

「对林婉儿说」需定向到林婉儿，但当前 TALK 意图只取 `npcs_in_scene[0]`。多 NPC 同场（仅林婉儿按 schedule 去集市时出现）会指错。

**做法：** 在 `engine/classify.py` 的 TALK 分支加轻量命名 NPC 解析——从输入里匹配在场 NPC 名（仿 `resolve_scene_id` 的关键词匹配），命中则 `params["target_npc"] = <id>`；`api/routes.py` 的 TALK 阶段优先用该 id，未命中仍回落首位。

MVP 多数场景只 1 NPC，影响面小，但「自由聊天」体验依赖它，故纳入本切片。

---

## 7. API 变更

### 7.1 富化 `GET /player/status`

在现有返回基础上：

- `scene` 增加 `description`、`landmarks`（来自 `SCENE_MAP`，静态）。
- `npcs_present` 由 id 列表升级为 NPC 卡片数组：`{id, name, role, favorability, relationship_stage, status_hint, present:true}`，数据来自 `npc_repo` profile。
- 新增 `npcs_all`：全部 NPC 的 `{id, name, role, favorability, relationship_stage, default_scene, present}` 摘要，供「不在场」渲染。`present` 由 `get_npcs_in_scene` 判定。
- 新增 `next_threshold`：当前境界在 `LEVEL_TABLE` 的下一档 `spirit_threshold`，供灵力进度条。
- 新增 `quests`：可见所务列表 `[{id, label, status}]`（`active` + 未过期的 `completed`，过期已移除）。
- 新增 `next_quest`：下一条待解锁所务的 `{label}`（所务链中第一个不在 `quests` 里的），供清单底部「将解锁…」预告行；全部解锁后为 `null`。
- `goal` 保留（第一条 active 所务），供状态条单行。
- `tick` 保留，供前端推演时辰（不落库辰制）。

读端**不跑 world 层**（不 advance_tick、不 check_events），保持读纯净。「当前异象」由前端持有上次 action 的 `world_event`，不在此端点算。

### 7.2 富化 `POST /game/action` 响应

- `scene` 同步增加 `description`、`landmarks`，让 action 后面板数据也准。
- `quests` 同 `status`（结算后所务清单）。
- 其余字段（world_event/combat/npc/goal）不变。

### 7.3 `GET /game/scenes` 不变

地图静态数据（场景 + connections）加载时取一次即可。当前场景与可达性由前端结合 `current_scene` + `connections` 推导。

---

## 8. 前端结构

仍**单文件 vanilla `static/index.html`**（不引框架，匹配现状与 H5 体积）。在现有结构上：

- 状态条 + chip 行（角色/地点/地图）+ 聊天区 + 输入栏（现有）。
- 新增**抽屉容器**：三个面板按 chip 切换渲染，遮罩 + 下滑收起。
- 新增 `panels` 渲染模块：从 `updateStatus(data)` 缓存的 `scene/npcs_all/quests/player` 渲染各面板；action 响应到来时刷新缓存。
- 新增 `prefill(text, focus=false)`：填输入栏、可选聚焦，**不发送**。
- 时辰映射：纯函数 `tick_to_shichen(tick)`，`tick % 12` 映射到十二时辰（子丑寅卯辰巳午未申酉戌亥）并带一句描述（如辰时 → `辰时 · 晨光初照`），随行动循环推进，永不外露 tick 数字。
- 地图可达性：`reachable = SCENE_MAP[current].connections`，仅这些节点点亮。

---

## 9. 沉浸约束（继承现有铁律）

- 面板文案全中文，无英文 id 外泄（场景短名、NPC 名、所务 label 均为中文）。
- 时辰用辰制，不用 tick 数字。
- 地图不可达项置灰不可点，避免「点了走不了」。
- 境界/灵力/所务/好感度均以引擎为准，面板只读展示，不自行改状态。
- NPC 切磋等不满足前置的按钮置灰，不诱导无效操作。

---

## 10. 范围排除（YAGNI）

不做：

- 面板直发结构化指令（交互 B 已否决）。
- 地图图形化节点连线（用列表式节点）。
- NPC 头像/立绘图片。
- 桌面端分栏布局、面板拖拽排列。
- 真逐字 token 流式。
- 向量 RAG、多 NPC 调度扩展。
- 所务的「放弃/隐藏手动操作」——全自动，不给玩家管理按钮。

以上归后续子项目。

---

## 11. 测试

前端 vanilla 难单测，重点测**后端富化与管道不变性**：

- `tests/test_api.py`：
  - `GET /player/status` 含 `scene.description/landmarks`、`npcs` 卡片数组（含 `favorability`）、`npcs_all`、`next_threshold`、`quests`。
  - `POST /game/action` 响应 `scene` 含 `description/landmarks`、含 `quests`。
  - 预填路径不绕过管道：`去内门` 仍经 classify→move→可达性校验（已有测试，确保不回归）。
  - 命名 NPC 定向：`对林婉儿说…` 在多 NPC 场景定向到 `linwaner`。
- `tests/test_world.py`：
  - 所务解锁：到竹林后 `probe_anomaly` 出现在 `quests`。
  - 所务达成：满足条件后 `status=="completed"`、`completed_tick` 记录。
  - 所务过期：完成 6 tick 后从 `quests` 移除。
  - `current_goal` 仍为第一条 `active`，且完成的不计入。
- `tests/test_rules.py` 或新 `test_shichen`：`tick_to_shichen` 纯函数单测。

---

## 12. 已决策项

| 编号 | 决策 | 理由 |
|---|---|---|
| D1 | 布局 A · 叙事为脊柱 + 抽屉面板 | 修仙 MUD 卖点是叙事沉浸，叙事始终在场 |
| D2 | 交互 A · 预填输入栏 | 操作仍走自然语言管道，骨架零改动 |
| D3 | 角色 + 人物面板合并，三 chip | 减少切换；所务置顶强化目标感 |
| D4 | 所务为引擎驱动任务清单 | 确定性解锁/达成，LLM 不加任务，符合骨/皮 |
| D5 | 完成所务 6 tick 自动隐去 | 够展示满足感又不长期占位 |
| D6 | 地图列表式节点，非图形连线 | YAGNI，MVP 够用 |
| D7 | 单文件 vanilla 前端 | 匹配现状与 H5 体积 |
| D8 | 纳入命名 NPC 定向 | 「自由聊天」体验依赖，影响面小 |

---

## 13. 风险与验证

| 假设 | 验证 | 风险 |
|---|---|---|
| 预填输入栏玩家会接受并修改 | 观察面板点击后是否直接发送 vs 改写 | 玩家可能不习惯「填了还要自己发」，需引导 |
| 所务清单的解锁节奏不突兀 | 观察新所务出现时机是否贴合剧情 | 解锁条件设错会让任务过早/过晚出现 |
| 6 tick 隐去窗口合适 | 观察玩家是否在完成条目消失前看到 | 节奏快的玩家可能没注意到「将隐去」 |
| 三面板合并不显拥挤 | 在真机看角色面板滚动长度 | 内容多需滚动，但抽屉可滚，可接受 |
| 富化 status 不拖慢读 | 端点响应时延 | npc_repo 多读几次 profile，量小可忽略 |