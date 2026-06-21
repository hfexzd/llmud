# UI & NPC 交互改进记录

> 日期：2026-06-21
> 基于 M3 结算校验器上线后的玩家体验反馈

## 面板交互

### 场景面板
- 5 秒后自动收起，释放空间给故事区
- 底部新增切换条，收起时显示 `▼ 场景 · 灵药谷 · 清幽`（含场景名+氛围），展开时显示 `▲`
- 收起后不会因场景切换自动展开，仅手动点击展开
- 展开后重新计时 5 秒自动收起

### 行动按钮面板
- 默认收起，显示 `▼ 行动`/`▲ 行动` 切换条
- 点击展开后 5 秒自动收起
- 隐藏滚动条（`scrollbar-width: none` + `::-webkit-scrollbar`），仅支持触摸/鼠标拖动
- 切换场景时先清空再根据当前场景重建
- 高度自适应（`max-height: none`），文字不被截断

### 箭头逻辑
- 场景面板（上方）：展开→`▲`（向上收起），收起→`▼`（向下展开）
- 行动面板（下方）：展开→`▼`（向下收起），收起→`▲`（向上展开）
- 箭头方向均指向面板本体位置，符合物理直觉

## NPC 系统

### 位置跟踪
- `npc_step` 不再强制覆盖 DM 动态设置的 NPC 位置：若 NPC 当前位置与静态 schedule 不同，保留动态位置
- 移动后故事中提及的 NPC（且在玩家上一个场景）自动同步到新场景
- DM 提示词强化：要求 NPC 跟随/离开时通过 `world_delta.scene_id` 更新位置

### NPC 行动提示
- 后端从 `world_delta.npc` 生成人类可读的行动字符串（如"林婉儿从内门来到了幽竹林"）
- 前端在聊天区显示绿色 `👤` NPC 行动卡片
- API 响应新增 `npc_actions` 字段

### DM 建议行动
- DM 可在 JSON 中附带 `suggested_actions` 数组（2-4 个中文短句）
- 前端以 `💬` 高亮样式显示在行动按钮栏最前面
- 适用场景：NPC 对话后提示下一步可选行动

## Bug 修复

| 问题 | 修复 |
|------|------|
| `Illegal return statement` (line 434) | 补回 `function renderRolePanel()` 声明 |
| `Unexpected token ')'` (line 1313) | keydown handler 缺少闭合 `}`，补上 |
| `SCENE_ALIASES is not defined` | 改用硬编码 `7`（共 7 个场景） |
| `p is not defined` in renderActionChips | 统一使用 `const p = panelData.player` |
| AudioContext 警告 | 推迟 AudioContext 创建到首次用户交互后 |
| `spirit_valley` 显示为英文 | `SCENE_NAMES` 补充 `spirit_valley: '灵药谷'`、`misty_lake: '雾隐湖'` |
| favicon 404 | 添加内联 SVG 图标 |

## 相关文件

- `static/index.html` — 前端 UI 交互
- `dm/prompt.py` — DM 提示词（rule 13 NPC 移动, rule 14 建议行动）
- `api/routes.py` — NPC 同步逻辑、suggested_actions 传递
- `engine/world.py` — `npc_step` 位置保留、`apply_world_delta` scene_id
- `engine/validator.py` — NPC scene_id 校验
- `engine/models.py` — DMResponse 新增 `suggested_actions`
- `dm/contract.py` — 解析 `suggested_actions`
