"""Settlement validator (M3). Pure functions — no LLM, no side effects.

Clamps DM-proposed world_delta against canon, numeric, causal, and personality
rules. Story violations are detected post-hoc (logged, never clamped — the
story was already streamed).
"""

from __future__ import annotations

from engine.models import DMResponse, WorldState, WorldBible, Player


# ---------------------------------------------------------------------------
# Canon entity name extraction (for story scanning)
# ---------------------------------------------------------------------------

def _canon_entity_names(bible: WorldBible) -> set[str]:
    """All named entities the world 'has' — used for story scanning."""
    names: set[str] = set()
    for scene in bible.scenes:
        names.add(scene.name)
        for lm in scene.landmarks:
            names.add(lm)
    for faction in bible.factions:
        names.add(faction.name)
    for item in bible.items:
        names.add(item.name)
    for skill in bible.skills:
        names.add(skill.name)
    for npc in bible.npc_models:
        # NPC profiles supply the display name
        pass  # names come from ALL_NPC_PROFILES, not BehaviorModel
    # Also pull from the global NPC profiles (canon block source)
    from engine.models import ALL_NPC_PROFILES, ENCOUNTER_CATALOG
    for p in ALL_NPC_PROFILES:
        names.add(p.name)
    for e in ENCOUNTER_CATALOG:
        names.add(e)
    return names


# Hard-coded common words that look like entities but aren't (stop-words for
# the story scanner — never flag these).
_STORY_SCAN_STOP_WORDS: set[str] = {
    "你", "我", "他", "她", "它", "们", "的", "了", "在", "是", "有", "和",
    "与", "或", "到", "从", "对", "把", "被", "让", "给", "向", "就", "也",
    "不", "没", "都", "还", "要", "会", "能", "可", "以", "得", "着", "过",
    "来", "去", "上", "下", "里", "外", "中", "前", "后", "左", "右",
    "大", "小", "多", "少", "一", "二", "三", "四", "五", "六", "七", "八",
    "九", "十", "百", "千", "万", "这", "那", "哪", "什么", "怎么", "如何",
    "一个", "一些", "这个", "那个", "自己", "知道", "觉得", "可以", "应该",
    "已经", "因为", "所以", "但是", "虽然", "如果", "的话", "之后", "之前",
    "时候", "地方", "东西", "事情", "感觉", "发现", "看到", "听到", "说道",
    "修仙", "修炼", "灵力", "灵气", "修士", "功法", "突破", "境界", "宗门",
    "弟子", "长老", "妖兽", "灵草", "丹药", "山脉", "竹林", "山谷", "洞府",
    "青云门", "练气", "筑基", "金丹",
    "丹田", "经脉", "灵根", "心法",  # cultivation body terms
    "盘膝", "而坐", "盘膝而坐",       # sitting posture
    "喃喃", "自语", "低声",           # speech mannerisms
    "缓缓", "渐渐", "微微", "轻轻", "慢慢",  # adverbs
    "仿佛", "似乎", "犹如", "宛若", "就像",  # simile markers
    "一股", "一阵", "一丝", "一缕", "一道", "一片",  # measure words
    "汇入", "步入", "踏入", "进入",  # movement verbs
    # Common Chinese narrative characters that should never be flagged as
    # unknown entities (they're general-purpose, not named entities)
    "正", "修", "再", "次", "身", "心", "神", "气", "力", "行",
    "盘", "膝", "而", "坐", "如", "般", "股", "阵", "丝", "缕", "片", "道",
    "丹", "汇", "入", "出", "步", "踏", "闪", "化", "变", "成",
    "微", "缓", "站", "轻", "点", "头", "笑", "目", "眉", "眼", "口", "手", "足",
    "惨", "嚎", "吼", "啸", "鸣", "啼",  # animal/combat sounds
    "深", "处", "苏", "醒", "感", "觉", "望", "见", "闻", "听", "说",  # perception
    "风", "雨", "雷", "电", "雾", "霜", "露", "雪",  # weather
    "很", "太", "极", "甚", "颇", "更", "越", "稍",  # degree
    "啊", "吗", "呢", "吧", "嘛", "哇", "哟", "哦", "嗯",  # particles
    "东", "西", "南", "北", "前", "后", "左", "右",  # directions
    "先", "后", "最", "已", "将", "刚", "才", "便", "随",  # time
    "啊", "呀", "哇", "哪", "吗", "嘛", "呢", "吧", "哦",  # more particles
}

# Additional known-NPC-name variants the DM might use in narration (e.g.
# "林婉儿师姐" contains "林婉儿" which is already canon). This set only
# needs entries that AREN'T pure substrings of canon names.
_STORY_SCAN_ALLOWED: set[str] = {
    "师姐", "师兄", "师弟", "师妹", "道友", "前辈", "后辈",
    "杨老",   # short form of 杨老 (canon name matches this)
    # Common enemy/creature shortenings that reference canon names
    "妖狼", "血狼", "妖兽", "灵兽", "凶兽",
}


def scan_story_for_canon_violations(story: str, bible: WorldBible) -> list[str]:
    """Post-hoc scan: detect story references to named entities outside canon.

    Returns a list of human-readable violation strings. This is log-only —
    the story was already streamed and cannot be clamped. The validator
    prompt rule 12 prevents most violations; this is a safety net.
    """
    if not story or not story.strip():
        return []

    canon_names = _canon_entity_names(bible)
    violations: list[str] = []

    import re
    # Split on punctuation to get candidate phrases
    chunks = re.split(r'[，。！？、；：""''「」『』【】 \n]+', story)
    seen: set[str] = set()
    for chunk in chunks:
        if not chunk:
            continue
        # For each chunk, check if it contains any sub-sequence that could
        # be a named entity reference. We look for 3-4 char sequences.
        # (Length 2 is too noisy for CJK — produces too many false positives.)
        found = False
        for length in (4, 3):
            if found:
                break
            for i in range(len(chunk) - length + 1):
                candidate = chunk[i:i + length]
                if candidate in _STORY_SCAN_STOP_WORDS:
                    continue
                if candidate in _STORY_SCAN_ALLOWED:
                    continue
                if candidate in canon_names:
                    continue
                # Check if any canon name contains this candidate (e.g.
                # "婉儿" is part of "林婉儿")
                if any(candidate in cname for cname in canon_names):
                    continue
                # Check if this candidate contains any canon name (e.g.
                # "林婉儿正" contains "林婉儿")
                if any(cname in candidate for cname in canon_names):
                    continue
                # Check if this candidate contains any stop word character
                if any(sw in candidate for sw in _STORY_SCAN_STOP_WORDS):
                    continue
                # Deduplicate: skip if we already flagged something
                # overlapping in this chunk
                violation_key = f"{candidate}@{id(chunk)}"
                if violation_key in seen:
                    continue
                seen.add(violation_key)
                # This is a potential unknown entity. Flag it.
                violations.append(
                    f"story mentions unknown entity '{candidate}' — not in canon"
                )
                found = True
                break  # One violation per chunk position is enough
    return violations


# ---------------------------------------------------------------------------
# Validation passes (each returns (clamped_delta, violations))
# ---------------------------------------------------------------------------

def _validate_canon(
    world_delta: dict, bible: WorldBible,
) -> tuple[dict, list[str]]:
    """Check all referenced entity ids/names exist in the bible.

    Returns (clamped_world_delta, violations). Unknown tension/NPC/faction
    keys are removed; the violation list records each removal.
    """
    if not world_delta:
        return world_delta, []

    tension_ids = {t.id for t in bible.tensions}
    npc_ids = {m.npc_id for m in bible.npc_models}
    faction_names = {f.name for f in bible.factions}

    clamped = dict(world_delta)
    violations: list[str] = []

    # Validate tension keys
    if "tension" in clamped:
        td = dict(clamped["tension"])
        for tid in list(td):
            if tid not in tension_ids:
                violations.append(f"canon: unknown tension '{tid}' — removed")
                del td[tid]
        if td:
            clamped["tension"] = td
        else:
            del clamped["tension"]

    # Validate NPC keys
    if "npc" in clamped:
        nd = dict(clamped["npc"])
        for nid in list(nd):
            if nid not in npc_ids:
                violations.append(f"canon: unknown npc '{nid}' — removed")
                del nd[nid]
        if nd:
            clamped["npc"] = nd
        else:
            del clamped["npc"]

    # Validate faction keys (matched by name, not id)
    if "faction" in clamped:
        fd = dict(clamped["faction"])
        for fname in list(fd):
            if fname not in faction_names:
                violations.append(f"canon: unknown faction '{fname}' — removed")
                del fd[fname]
        if fd:
            clamped["faction"] = fd
        else:
            del clamped["faction"]

    return clamped, violations


def _validate_numeric(
    world_delta: dict,
) -> tuple[dict, list[str]]:
    """Clamp numeric values to valid ranges.

    - tension progress: 0..100
    - tension pressure: >= 0
    - faction trust: 0..100
    - NPC goal_progress: 0..100

    Returns (clamped_world_delta, violations).
    """
    if not world_delta:
        return world_delta, []

    clamped = dict(world_delta)
    violations: list[str] = []

    # Clamp tension progress/pressure
    if "tension" in clamped:
        td = dict(clamped["tension"])
        for tid, tdelta in td.items():
            td_clamped = dict(tdelta)
            if "pressure" in td_clamped and td_clamped["pressure"] < 0:
                violations.append(
                    f"numeric: tension '{tid}' pressure {td_clamped['pressure']} clamped to 0"
                )
                td_clamped["pressure"] = 0
            if "progress" in td_clamped:
                prog = dict(td_clamped["progress"])
                for pid, val in list(prog.items()):
                    if val < 0:
                        violations.append(
                            f"numeric: tension '{tid}' progress '{pid}' {val} clamped to 0"
                        )
                        prog[pid] = 0
                    elif val > 100:
                        violations.append(
                            f"numeric: tension '{tid}' progress '{pid}' {val} clamped to 100"
                        )
                        prog[pid] = 100
                td_clamped["progress"] = prog
            td[tid] = td_clamped
        clamped["tension"] = td

    # Clamp faction trust
    if "faction" in clamped:
        fd = dict(clamped["faction"])
        for fname, fdelta in fd.items():
            fd_clamped = dict(fdelta)
            if "trust" in fd_clamped:
                if fd_clamped["trust"] < 0:
                    violations.append(
                        f"numeric: faction '{fname}' trust {fd_clamped['trust']} clamped to 0"
                    )
                    fd_clamped["trust"] = 0
                elif fd_clamped["trust"] > 100:
                    violations.append(
                        f"numeric: faction '{fname}' trust {fd_clamped['trust']} clamped to 100"
                    )
                    fd_clamped["trust"] = 100
            if "dominance" in fd_clamped:
                if fd_clamped["dominance"] < 0:
                    violations.append(
                        f"numeric: faction '{fname}' dominance {fd_clamped['dominance']} clamped to 0"
                    )
                    fd_clamped["dominance"] = 0
            fd[fname] = fd_clamped
        clamped["faction"] = fd

    # Clamp NPC goal_progress
    if "npc" in clamped:
        nd = dict(clamped["npc"])
        for nid, ndelta in nd.items():
            nd_clamped = dict(ndelta)
            if "goal_progress" in nd_clamped:
                gp = dict(nd_clamped["goal_progress"])
                for gid, val in list(gp.items()):
                    if val < 0:
                        violations.append(
                            f"numeric: npc '{nid}' goal_progress '{gid}' {val} clamped to 0"
                        )
                        gp[gid] = 0
                    elif val > 100:
                        violations.append(
                            f"numeric: npc '{nid}' goal_progress '{gid}' {val} clamped to 100"
                        )
                        gp[gid] = 100
                nd_clamped["goal_progress"] = gp
            nd[nid] = nd_clamped
        clamped["npc"] = nd

    return clamped, violations


def _validate_causal(
    world_delta: dict, world_state: WorldState,
) -> tuple[dict, list[str]]:
    """Check causal plausibility: only active tensions can receive changes.

    Returns (clamped_world_delta, violations).
    """
    if not world_delta or "tension" not in world_delta:
        return world_delta, []

    clamped = dict(world_delta)
    violations: list[str] = []
    td = dict(clamped.get("tension", {}))

    for tid in list(td):
        rt = world_state.tensions.get(tid)
        if rt is None:
            # Not in world_state at all — canon check should have caught this,
            # but be defensive.
            continue
        if rt.status == "dormant":
            violations.append(
                f"causal: tension '{tid}' is dormant — cannot receive progress/pressure"
            )
            del td[tid]
        elif rt.status == "resolved":
            violations.append(
                f"causal: tension '{tid}' is already resolved — delta removed"
            )
            del td[tid]

    if td:
        clamped["tension"] = td
    else:
        clamped.pop("tension", None)

    return clamped, violations


def _validate_personality(
    world_delta: dict, bible: WorldBible, world_state: WorldState,
) -> tuple[dict, list[str]]:
    """Check NPC updates are consistent with behavior models.

    For M3 phase-0, this is a lightweight check: the NPC must exist in the
    bible (already covered by canon check), and mood changes must be
    non-empty strings (basic sanity). Richer personality checks (motive
    compatibility, goal consistency) arrive in M7 when behavior models are
    more developed.

    Returns (clamped_world_delta, violations).
    """
    if not world_delta or "npc" not in world_delta:
        return world_delta, []

    clamped = dict(world_delta)
    violations: list[str] = []
    nd = dict(clamped.get("npc", {}))

    for nid, ndelta in list(nd.items()):
        nd_clamped = dict(ndelta)
        # scene_id must be a known scene if present
        if "scene_id" in nd_clamped:
            valid_scene_ids = {s.id for s in bible.scenes}
            if nd_clamped["scene_id"] not in valid_scene_ids:
                violations.append(f"personality: npc '{nid}' scene_id '{nd_clamped['scene_id']}' unknown — removed")
                del nd_clamped["scene_id"]
        # mood must be a non-empty string if present
        if "mood" in nd_clamped:
            if not isinstance(nd_clamped["mood"], str) or not nd_clamped["mood"].strip():
                violations.append(f"personality: npc '{nid}' mood is empty — removed")
                del nd_clamped["mood"]
        # goal_progress keys must reference goals that exist in the behavior model
        if "goal_progress" in nd_clamped:
            model = next((m for m in bible.npc_models if m.npc_id == nid), None)
            if model:
                valid_goal_ids = {g.id for g in model.goals}
                gp = dict(nd_clamped["goal_progress"])
                for gid in list(gp):
                    if gid not in valid_goal_ids:
                        violations.append(
                            f"personality: npc '{nid}' has no goal '{gid}' — removed"
                        )
                        del gp[gid]
                nd_clamped["goal_progress"] = gp
        nd[nid] = nd_clamped

    clamped["npc"] = nd
    return clamped, violations


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def validate_dm_proposal(
    proposal: DMResponse,
    world_state: WorldState,
    world_bible: WorldBible,
    player: Player,
) -> tuple[DMResponse, list[str], bool]:
    """Validate and clamp a DM proposal's world_delta.

    Per spec §8: checks canon, numeric bounds, causal plausibility, and
    personality consistency on world_delta. Story is NOT checked here (use
    scan_story_for_canon_violations separately for post-hoc logging).

    Returns:
        clamped: DMResponse with violations removed/clamped
        violations: list of human-readable violation strings (for logging)
        should_retry: True if a structural (canon) violation warrants one retry
    """
    if not proposal.action_valid:
        return proposal, [], False

    wd = proposal.world_delta
    if not wd:
        return proposal, [], False

    all_violations: list[str] = []
    should_retry = False

    # Pass 1: canon (structural — triggers retry)
    wd, v = _validate_canon(wd, world_bible)
    all_violations.extend(v)
    if v:
        should_retry = True

    # Pass 2: numeric bounds (clamp only)
    wd, v = _validate_numeric(wd)
    all_violations.extend(v)

    # Pass 3: causal plausibility
    wd, v = _validate_causal(wd, world_state)
    all_violations.extend(v)

    # Pass 4: personality consistency
    wd, v = _validate_personality(wd, world_bible, world_state)
    all_violations.extend(v)

    # If world_delta became empty after clamping, set to None
    if wd == {}:
        wd = None

    clamped = proposal.model_copy(update={"world_delta": wd})
    return clamped, all_violations, should_retry
