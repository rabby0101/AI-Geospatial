import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

_SKILLS_DIR = Path(__file__).parent.parent / "skills"
_skills_cache: Dict[str, Dict[str, Any]] = {}


def load_skills() -> None:
    """Load all skill JSON files from app/skills/ into memory cache."""
    global _skills_cache
    _skills_cache = {}

    if not _SKILLS_DIR.exists():
        logger.warning(f"Skills directory not found: {_SKILLS_DIR}")
        return

    for skill_file in sorted(_SKILLS_DIR.glob("*.json")):
        try:
            with open(skill_file, "r", encoding="utf-8") as f:
                skill = json.load(f)

            skill_id = skill.get("id")
            if not skill_id:
                logger.warning(f"Skill file missing 'id' field: {skill_file.name}")
                continue

            if not skill.get("enabled", True):
                logger.info(f"Skill '{skill_id}' is disabled, skipping.")
                continue

            _skills_cache[skill_id] = skill
            logger.info(f"Loaded skill: {skill_id} ({skill.get('name', skill_id)})")

        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"Failed to load skill file {skill_file.name}: {e}")

    logger.info(f"Skills loaded: {list(_skills_cache.keys())}")


def list_skills() -> List[Dict[str, str]]:
    """Return summary of all enabled skills for the frontend."""
    return [
        {
            "id": s["id"],
            "name": s.get("name", s["id"]),
            "description": s.get("description", ""),
            "icon": s.get("icon", "🔧"),
        }
        for s in _skills_cache.values()
    ]


def get_skill(skill_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """
    Return full skill config for the given skill_id.
    Returns None if skill_id is None, empty, or unknown —
    which means the pipeline runs in full/default mode.
    """
    if not skill_id:
        return None
    skill = _skills_cache.get(skill_id)
    if skill is None:
        logger.warning(f"Unknown skill requested: '{skill_id}'. Running in full mode.")
    return skill


def get_skill_prompt_injection(skill: Optional[Dict[str, Any]]) -> str:
    """
    Build the skill-specific text to inject into system prompts.
    Returns an empty string if no skill is active.
    """
    if not skill:
        return ""

    domain = skill.get("domain", {})
    focus = domain.get("focus", "")
    exclude = domain.get("exclude", "")
    prompt_focus = skill.get("prompt_focus", "")
    max_tables = skill.get("max_tables")

    lines = []
    if focus:
        lines.append(f"SKILL DOMAIN FOCUS: {focus}")
    if exclude:
        lines.append(f"SKILL DOMAIN EXCLUDE: {exclude}")
    if max_tables:
        lines.append(f"TABLE SELECTION LIMIT: Select at most {max_tables} tables.")
    if prompt_focus:
        lines.append(f"\n{prompt_focus}")

    return "\n".join(lines)


def get_allowed_operations(skill: Optional[Dict[str, Any]]) -> Optional[List[str]]:
    """
    Return the list of allowed operation types for this skill.
    Returns None if no skill is active (all operations allowed).
    """
    if not skill:
        return None
    return skill.get("operations", {}).get("allowed")


def phase_enabled(skill: Optional[Dict[str, Any]], phase_key: str) -> bool:
    """
    Check if a pipeline phase is enabled for the active skill.
    phase_key examples: 'phase_0_business_intel', 'phase_3_planning', 'phase_5_evaluation'
    Returns True if no skill is active (full mode) or if the phase is not restricted.
    'auto' is treated as True (pipeline decides at runtime).
    """
    if not skill:
        return True
    value = skill.get("pipeline", {}).get(phase_key, True)
    if isinstance(value, bool):
        return value
    return True  # 'auto' or any other value → enabled
