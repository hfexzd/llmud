"""Schema-level validation for a generated WorldBible.

Checks structural integrity: required fields present, no duplicate ids,
references resolve within the bible. This is a safety net before accepting
an LLM-produced canon into the live pipeline.
"""

from engine.models import WorldBible


_MIN_SCENES = 3
_MIN_TENSIONS = 1
_MIN_NPC_MODELS = 1


def validate_bible(bible: WorldBible) -> list[str]:
    """Validate a WorldBible for structural integrity.

    Returns a list of error strings. Empty list = valid.
    """
    errors: list[str] = []

    if not bible.scenes or len(bible.scenes) < _MIN_SCENES:
        errors.append(f"bible must have at least {_MIN_SCENES} scenes (got {len(bible.scenes)})")

    if not bible.tensions:
        errors.append(f"bible must have at least {_MIN_TENSIONS} tension (got {len(bible.tensions)})")

    if not bible.npc_models or len(bible.npc_models) < _MIN_NPC_MODELS:
        errors.append(f"bible must have at least {_MIN_NPC_MODELS} npc_models (got {len(bible.npc_models)})")

    # Check for duplicate ids
    tension_ids = [t.id for t in bible.tensions]
    if len(tension_ids) != len(set(tension_ids)):
        dupes = {tid for tid in tension_ids if tension_ids.count(tid) > 1}
        errors.append(f"duplicate tension ids: {dupes}")

    scene_ids = [s.id for s in bible.scenes]
    if len(scene_ids) != len(set(scene_ids)):
        dupes = {sid for sid in scene_ids if scene_ids.count(sid) > 1}
        errors.append(f"duplicate scene ids: {dupes}")

    npc_ids = [m.npc_id for m in bible.npc_models]
    if len(npc_ids) != len(set(npc_ids)):
        dupes = {nid for nid in npc_ids if npc_ids.count(nid) > 1}
        errors.append(f"duplicate npc ids: {dupes}")

    # Check each tension has a trigger
    for t in bible.tensions:
        if not t.trigger or not t.trigger.type:
            errors.append(f"tension '{t.id}' has no trigger")

    # Check scene connections resolve
    scene_id_set = set(scene_ids)
    for s in bible.scenes:
        for conn in s.connections:
            if conn not in scene_id_set:
                errors.append(f"scene '{s.id}' connects to unknown scene '{conn}'")

    return errors
