"""Emergency rule hook for the API foundation."""
from typing import Any

def find_emergency_rules(answers: dict[str, dict[str, Any]]) -> list[str]:
    """Rules are supplied by the triage safety feature branch."""
    return []
