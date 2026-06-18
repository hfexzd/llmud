# 活世界设计：解决玩家漫无目的问题

**日期：** 2026-06-18
**状态：** 已批准
**范围：** MVP 阶段——小世界、软引导、事件池 + 场景状态

---

## 1. 问题

当前玩家只有修炼、打怪、对话三件事，缺少方向感。世界是静态的——只有一个场景、一个NPC、一个怪物，没有探索的动力和发现的惊喜。

## 2. 设计目标

通过"软引导"（情境诱惑）让玩家觉得是自己想去某个地方，实际上是被故事勾走的。三种引导渠道：

1. **环境叙事暗示**：修炼/移动时自然出现的线索
2. **随机遭遇事件**：休息或探索时触发的惊喜
3. **NPC主动搭话**：NPC主动提供方向

核心原则不变：**引擎决定发生了什么（骨头），LLM决定怎么讲（皮肤）。**

## 3. 方案选择

| 方案 | 描述 | 优点 | 缺点 |
|---|---|---|---|
| 场景图谱+NPC调度 | 世界模拟器，NPC有完整日程 | 最真实 | 复杂度最高 |
| **事件池+场景状态** | 精心编排事件，按条件触发 | 简单可控，最契合骨头+皮肤 | 重玩可能重复 |
| 叙事节拍 | 预定义主线节拍，填充小事件 | 戏剧张力强 | 最不自由，与软引导矛盾 |

**选择：事件池+场景状态（方案二）**。最契合现有架构，最可控，最容易迭代。

## 4. 架构

### 4.1 管道变更

现有管道：`classify → engine → dm → npc`

新管道：`classify → engine → world → dm → npc`

```
玩家输入
  ↓
classify（意图识别）
  ↓
engine（确定性结算：修炼/战斗/移动）
  ↓
world（世界状态更新：tick推进、事件检测、NPC位置）
  ↓
dm（LLM叙事：把所有发生的事写成故事）
  ↓
输出
```

`world` 层是新的"骨头"——确定性计算发生在引擎层，LLM只负责叙事。

### 4.2 叙事层次

每次响应给玩家的内容分三层：

1. **玩家行动结果**（必选）：你做了什么，结果如何
2. **环境感知**（事件触发时）：你注意到了什么
3. **介入选项**（可选）：你可以选择做什么

---

## 5. 场景系统

### 5.1 数据模型

```python
class Scene(BaseModel):
    id: str                          # "outer_gate"
    name: str                         # "青云门外门"
    description: str                  # 场景基调描述（给LLM用）
    atmosphere: str                   # 氛围关键词
    connections: list[str]            # 可达场景id列表
    available_actions: list[str]     # 本场景可做的事
    encounter_ids: list[str]          # 本场景可能遇到的怪物id
    npc_ids: list[str]                # 默认驻扎在此的NPC id
```

### 5.2 MVP 场景设计

| ID | 名称 | 氛围 | 连接 | 特色 |
|---|---|---|---|---|
| `outer_gate` | 青云门外门 | 清幽 | inner_gate, market | 修炼、入门引导 |
| `inner_gate` | 青云门内门 | 庄严 | outer_gate, bamboo_forest | 师姐常驻、修炼加速 |
| `bamboo_forest` | 幽竹林 | 神秘 | inner_gate, mountain_range | 奇遇、采药 |
| `market` | 修士集市 | 繁忙 | outer_gate | 交易、打听消息 |
| `mountain_range` | 妖兽山脉 | 危险 | bamboo_forest | 战斗、探险 |

### 5.3 移动规则

只能移动到相邻场景（connections里的）。`move` 意图需要带目标场景，引擎验证可达性。

---

## 6. 事件池系统

### 6.1 数据模型

```python
class EventTrigger(BaseModel):
    type: str                         # "location_enter"|"tick_interval"|"stat_threshold"|"random"
    conditions: dict                  # 条件参数
    probability: float = 1.0         # 触发概率

class WorldEvent(BaseModel):
    id: str                           # "bamboo_faint_light"
    name: str                         # "竹林微光"
    scene_id: str                     # 触发场景
    trigger: EventTrigger              # 触发条件
    narrative_hint: str               # 给LLM的叙述指引
    guidance: str                     # 玩家引导方向
    allow_intervene: bool = False     # 玩家是否可以介入
    intervene_options: list[str] | None = None
    one_time: bool = True             # 是否只触发一次
```

### 6.2 事件分类

#### 环境暗示（给方向感）

| ID | 场景 | 触发 | 叙事 |
|---|---|---|---|
| `faint_spirit_sense` | outer_gate | 首次进入 | "你感到东方有灵气波动"→暗示去内门 |
| `bamboo_whisper` | inner_gate | 灵力≥20 | "竹林方向传来沙沙声"→暗示去竹林 |
| `market_rumor` | market | tick≥5 | "有人议论山脉异动"→暗示去山脉 |

#### NPC搭话（主动引导）

| ID | 场景 | 触发 | 叙事 |
|---|---|---|---|
| `waner_worry` | inner_gate | 首次遇到师姐 | "师姐似乎心事重重" |
| `merchant_gossip` | market | tick≥3 | "商贩主动搭话：山里出了好东西" |

#### NPC间互动（活世界感）

| ID | 场景 | 触发 | 叙事 |
|---|---|---|---|
| `waner_merchant_chat` | market | 师姐和商贩都在 | "师姐和商贩在交谈" |
| `elder_scolding` | inner_gate | tick≥8 | "长老训斥弟子关于竹林禁地" |

#### 随机遭遇（惊喜感）

| ID | 场景 | 触发 | 叙事 |
|---|---|---|---|
| `spirit_herb` | bamboo_forest | 随机10% | "发现一株散发微光的灵草" |
| `strange_traveler` | market | 随机15% | "一个神秘旅人坐在角落" |

### 6.3 触发流程

1. 玩家行动 → 引擎结算 → 世界tick+1
2. 世界状态层检查：当前场景有哪些事件的触发条件满足？
3. 按优先级和概率筛选触发事件（每次最多1个）
4. 事件信息注入DM prompt：`【世界事件】你正在竹林中发现一株灵草……`
5. LLM基于事件指引 + 玩家状态 → 生成叙事

### 6.4 一次性追踪

`one_time=True` 的事件触发后记入 `player.seen_events`，不再重复。

---

## 7. NPC 存在感 + 互动

### 7.1 NPC 设计

| ID | 名称 | 默认场景 | 人设 | 秘密 |
|---|---|---|---|---|
| `linwaner` | 林婉儿（师姐） | inner_gate | 温柔知心，修炼有成 | 宗门长老私生女 |
| `chenhao` | 陈浩（师兄） | market | 豪爽直率，爱冒险 | 偷偷修炼禁术 |
| `old_yang` | 杨老（守门人） | outer_gate | 话少但句句关键 | 曾是宗门最强剑修 |

### 7.2 NPC 位置规则

```python
class NPCPresence(BaseModel):
    npc_id: str
    default_scene: str
    schedule: list[SceneSchedule] = []

class SceneSchedule(BaseModel):
    tick_range: tuple[int, int]
    scene_id: str
```

- 没有schedule的NPC待在默认场景（MVP大部分NPC不移动）
- 师姐偶尔去集市（有schedule条目）
- 引擎计算：玩家进入场景时，哪些NPC在场

### 7.3 NPC 间互动

```python
class NPCInteraction(BaseModel):
    id: str
    npc_ids: list[str]              # 参与互动的NPC
    scene_id: str                   # 在哪个场景触发
    trigger_conditions: dict         # 触发条件
    narrative_hint: str             # LLM叙述指引
    allow_intervene: bool           # 是否允许玩家介入
    intervene_options: list[str] | None = None
```

**玩家介入流程：**

1. 事件触发时，如果 `allow_intervene=True`，响应中加 `intervention_options`
2. 前端展示为可点击的选项按钮
3. 玩家选择后，作为 `intent: "intervene"` 处理
4. 引擎根据选择产生不同的叙事分支（LLM生成）

---

## 8. 软引导链条

暗示必须有逻辑链，不是随机的。按玩家成长阶段递进：

**入门阶段（灵力<20）：**
- `faint_spirit_sense`：暗示去内门修炼
- `waner_worry`：暗示跟NPC对话
- `outer_gate_cultivate_hint`：确认当前位置也能修炼

**成长阶段（灵力20-50）：**
- `bamboo_whisper`：暗示去竹林探索
- `market_rumor`：暗示去集市打听
- `chenhao_challenge`：暗示去战斗

**探索阶段（灵力50+）：**
- `elder_scolding`：暗示探索竹林深处
- `spirit_herb`：奖励探索
- `waner_secret_hint`：暗示深入剧情

---

## 9. API 变更

### 9.1 GET /player/status — 新增返回

```json
{
  "player": { "name": "张铁柱", "current_scene": "inner_gate", ... },
  "scene": {
    "id": "inner_gate",
    "name": "青云门内门",
    "atmosphere": "庄严",
    "npcs_present": ["linwaner"],
    "connections": ["outer_gate", "bamboo_forest"]
  }
}
```

### 9.2 POST /game/action — 新增流程

在 engine 和 dm 之间加入 world 层：

```
1. classify → intent
2. engine → 结算
3. world → tick+1, 更新NPC位置, 检测事件, 检查NPC互动
4. dm → 把事件信息注入prompt, 生成叙事
5. 输出 → story + world_event + intervention
```

### 9.3 新增 GET /game/scenes

返回世界地图（场景列表+连接）供前端展示。

### 9.4 响应新增字段

```json
{
  "story": "...",
  "world_event": {
    "id": "bamboo_whisper",
    "guidance": "explore_bamboo_forest"
  },
  "intervention": {
    "description": "你可以选择：",
    "options": ["上前搭话", "继续偷听", "默默离开"]
  }
}
```

---

## 10. Player 模型变更

```python
class Player(BaseModel):
    # ... 现有字段 ...
    seen_events: list[str] = Field(default_factory=list)  # 已触发事件
    current_scene: str = "outer_gate"                      # 当前场景（替换location）
```

`location` 字段改为 `current_scene`，值从自由文本变为场景ID引用。

---

## 11. 文件结构变更

```
engine/
  models.py        # 扩展：Scene, WorldEvent, WorldState 等
  rules.py         # 扩展：move() 验证场景连通性
  world.py         # 新增：场景定义、事件池、世界状态管理

npc/
  models.py        # 扩展：NPCProfile 加 default_scene/schedule
  memory.py        # 不变

db/
  repository.py    # 扩展：场景/NPC配置的CRUD
  connection.py     # 扩展：新表

api/
  routes.py        # 扩展：注入 world 层到管道
  app.py           # 扩展：初始化世界状态

dm/
  prompt.py        # 扩展：注入世界事件到 DM prompt

static/
  index.html       # 扩展：场景信息、NPC列表、介入选项
```

---

## 12. 已决定的设计决策

| 编号 | 决策 | 理由 |
|---|---|---|
| D1 | 场景和事件数据硬编码在 Python 中 | MVP 阶段不需要数据库存场景配置 |
| D2 | NPC 不移动（MVP） | 只有师姐偶尔去集市，其他NPC固定位置 |
| D3 | 一次性事件用 player.seen_events 追踪 | 简单，避免重复 |
| D4 | 事件每次最多触发1个 | 避免信息过载 |
| D5 | 玩家介入作为新 intent 处理 | 复用现有管道 |
| D6 | 引导方向：软引导（情境诱惑） | 玩家觉得是自己想去的，其实是被引导的 |
| D7 | 世界规模：3-5个场景，2-3个NPC | MVP 小世界，足够验证核心循环 |

---

## 13. 验证假设与风险

| 假设 | 验证方式 | 风险 |
|---|---|---|
| 环境暗示能引导玩家探索 | 观察玩家是否在暗示后移动到目标场景 | 暗示太隐晦可能被忽略 |
| NPC互动让世界感觉活着 | 观察玩家是否主动观察NPC互动 | 互动太少或重复会失去新鲜感 |
| 事件池不会感觉重复 | 追踪玩家触发事件的多样性 | one_time 事件用完后只剩随机事件 |
| 介入选项增加参与感 | 观察玩家选择介入的比例 | 介入选项可能打断叙事节奏 |