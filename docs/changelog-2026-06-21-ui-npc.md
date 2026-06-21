# UI & 游戏系统改进记录

> 日期：2026-06-21
> 基于 M3 结算校验器上线后的玩家体验反馈

## 主菜单系统

- 进入游戏时显示主菜单（替代直接进入）
- **继续上次的故事** — 有存档续玩，无存档提示新建
- **重新开始** — 弹出名字输入框（默认"张铁柱"），确认后调用 `/game/reset` 重置
- **游戏历程回顾** — 列出 `saves/` 目录中的历史记录（玩家名、境界、回合数、结局）
- 结局卡片改为"返回主菜单"
- `/game/reset` 接受 `{name}` 参数设置新主角名，重置前保存当前记录到 `saves/run-时间戳.json`
- `/game/runs` API 返回历史记录列表

## 面板交互

- 场景面板 5 秒后自动收起，切换条显示 `▼/▲ 场景 · 场景名 · 氛围`
- 行动按钮面板默认收起，点击展开后 5 秒自动收起
- 收起后面板不会因场景切换自动展开，仅手动点击
- 箭头方向：场景面板（上方）展开→▲收起，行动面板（下方）展开→▼收起

## 行动按钮重构

- 移除 50+ 个无实际价值的场景按钮（观鸟/赏花/拾叶/画石/制陶/射箭/冥想/品茶等）
- 保留核心：**修炼、战斗、休息、去X、和NPC搭话**
- DM 建议行动置顶显示（`💬` 高亮）
- 服务端 `_generate_suggestions()` 根据故事文本自动生成建议（NPC、威胁、谜团分析）
- 点击行动按钮直接发送，无需回车
- 隐藏滚动条，仅支持触摸/鼠标拖动

## NPC 系统

### 位置跟踪（根因修复）
- **根因**: `get_npcs_in_scene()` 只读静态 `NPC_PRESENCES` 时间表，完全忽略 `world_state.npc_state` 动态位置
- **修复**: 优先读取 `world_state.npc_state`，静态 schedule 仅作回退
- `npc_step` 不再强制覆盖 DM 动态设置的 NPC 位置
- 正则同行检测（`与X并肩`、`X随你`、`X握紧/低声道`等），自动注入 `world_delta`
- 每次 DM 回复都检测（不限 MOVE 意图）

### NPC 行动提示
- 心境变化只在 NPC 在场时提示
- 聊天区绿色 `👤` 卡显示 NPC 移动和心境变化
- 移除聊天区重复的"在此处的有"（场景面板已有）

### 毒性蟒战斗修复
- 敌人识别从近期故事 + 玩家输入中提取（不只用默认敌人）
- 毒鳞蟒加入 bamboo_forest/mountain_range 遭遇池
- `ALL_ENEMIES` 映射 + `resolve_encounter_for_scene()` 故事感知选择

## 结局系统

- 行遍天下最低触发 tick 从 **20→500**（约 20 回合→数小时）

## 离线成长

- 挂机策略下拉框：闭关/历练/静养（已修复选项可见性）
- 离线回合 = 离线分钟数 × 速率，封顶 480 回合（8 小时）
- 不触发突破、不触发终态

## Bug 修复

| 问题 | 修复 |
|------|------|
| `Illegal return statement` | 补回 `function renderRolePanel()` 声明 |
| `Unexpected token ')'` | keydown handler 补缺失 `}` |
| `SCENE_ALIASES is not defined` | 改用硬编码 |
| `p is not defined` | 统一变量名 |
| AudioContext 警告 | 推迟到首次用户交互后创建 |
| `spirit_valley` 显示英文 | SCENE_NAMES 补充中文 |
| favicon 404 | 内联 SVG 图标 |
| `ERR_INCOMPLETE_CHUNKED_ENCODING` | LLM 流中断时的兜底处理 |
| 主菜单 `loading-screen` null | 元素被 remove 后加空值守卫 |
| 建议行动被状态刷新清除 | 状态更新时保留上次建议 |

## 相关文件

- `static/index.html` — 主菜单、面板、行动按钮、NPC 显示
- `dm/prompt.py` — rule 13 NPC 移动、rule 14 建议行动
- `api/routes.py` — NPC 同步、建议生成、重置/历程 API
- `engine/world.py` — `get_npcs_in_scene` 动态优先、`npc_step` 位置保留
- `engine/validator.py` — NPC scene_id 校验
- `engine/models.py` — `DMResponse.suggested_actions`、`ALL_ENEMIES`、`resolve_encounter_for_scene`、结局条件
- `engine/offline.py` — `advance_offline` 离线回合计算
- `dm/contract.py` — 解析 `suggested_actions`
