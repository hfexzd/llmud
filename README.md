# 修仙 MUD — llmud

A text-based Chinese cultivation (修仙) MUD game with an emergent living world. Features LLM-driven DM narration, rule-driven tension state machine, NPC interactions, and a vanilla-JS mobile-friendly frontend.

## Quick Start

```bash
# 1. Set your API key
cp .env.example .env
# Edit .env and set DEEPSEEK_API_KEY=sk-your-key

# 2. Run
python main.py

# 3. Open
# http://localhost:8001
```

### Docker

```bash
docker compose up -d
# http://localhost:8001
```

## Features

### World
- **7 scenes** to explore: 青云门外门, 内门, 幽竹林, 修士集市, 妖兽山脉, 灵药谷, 雾隐湖
- **5 NPCs** with memory, favorability, schedules: 林婉儿, 陈浩, 杨老, 药老, 湖隐
- **3 enemies**: 赤眼妖狼, 毒鳞蟒, 玄水龟
- **24+ events**: scene triggers, random encounters, NPC interactions
- **10 items**: consumables (herbs, pills), equipment (weapons, armor), quest items

### Systems
| System | Description |
|--------|-------------|
| **DM Narrator** | LLM generates story text in Chinese cultivation style |
| **Tension Engine** | Rule-driven event progression with active/resolved states |
| **Validator** | 4-pass settlement validator (canon/numeric/causal/personality) |
| **Endings** | 7 terminal archetypes with finale narration (飞升/陨落/入魔/etc.) |
| **Offline Growth** | 3 directives (闭关/历练/静养) with budget-capped tick advance |
| **Flow Governor** | Dynamic difficulty adjustment based on player performance |
| **Item System** | Use, inspect, gift to NPCs, equip weapons/armor |
| **Shop** | Buy/sell items at market with spirit stones |
| **Equipment** | Weapon + armor slots with stat bonuses |
| **Panel UI** | Three-drawer interface (角色/地点/地图) with quest log |

### Frontend
- Vanilla HTML/CSS/JS (no framework)
- Mobile-friendly H5 layout
- Streaming story text
- Contextual action chips
- Toast notifications for breakthroughs, items, favorability
- Ending card overlay

## Development

```bash
make test       # Run all 277 tests
make test-quick # Quick test run
make run        # Start server
make clean      # Remove cache files
```

### Architecture

```
api/routes.py        → HTTP endpoints + pipeline orchestration
engine/models.py     → All data models + world content
engine/world.py      → World engine (tick, NPC step, tension, quests)
engine/validator.py  → 4-pass settlement validator
engine/rules.py      → Combat, cultivation, items, equipment
dm/prompt.py         → LLM prompt templates
dm/contract.py       → LLM response parsing
db/repository.py     → SQLite persistence
static/index.html    → Frontend (single file)
worldgen/            → LLM world generation
```

### API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/player/status` | Full player state for panels |
| GET | `/game/scenes` | World map (all scenes) |
| POST | `/game/action` | Process player action |
| POST | `/game/reset` | Reset all game state |

### Tech Stack
- **Backend**: Python 3.14, FastAPI, Pydantic v2, SQLite
- **LLM**: DeepSeek API (configurable)
- **Frontend**: Vanilla HTML/CSS/JS
- **Deploy**: Docker, docker-compose

## License

MIT
