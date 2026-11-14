"""Check registry.

Every check declares what it needs and what it costs, so the runner can
order them (deterministic first), skip unchanged ones and respect the
profile (which checks are on, with which parameters).
"""

from dataclasses import dataclass, field
from typing import Callable

CATEGORIES = {
    "integrity":    "File integrity",
    "formatting":   "Formatting",
    "anonymity":    "Anonymity",
    "references":   "References",
    "manipulation": "Hidden text & manipulation",
    "numbers":      "Numbers",
    "figures":      "Figures & tables",
}

# deterministic: pure local computation on the document model
# network      : looks things up online (only allowed services, opt-in)
# llm          : calls the configured LLM (not used yet)
EXEC_KINDS = ("deterministic", "network", "llm")
COST_ORDER = {"deterministic": 0, "network": 1, "llm": 2}


@dataclass
class CheckSpec:
    id: str
    title: str
    category: str
    section: int                     # section number in the screening spec
    description: str
    fn: Callable
    version: int = 1                 # bump when the logic changes -> cached results are re-run
    exec_kind: str = "deterministic"
    kind: str = "technical"          # technical | scientific
    default_enabled: bool = True
    needs_double_blind: bool = False # only meaningful when the call is double-blind
    params: dict = field(default_factory=dict)        # default parameters
    param_help: dict = field(default_factory=dict)    # human labels for the parameters
    reads: tuple = ()                # paper/conference fields the check reads (for the skip hash)
    services: tuple = ()             # external hosts contacted (network checks)
    volatile: bool = False           # depends on other papers -> always re-run

    def public(self) -> dict:
        return {
            "id": self.id, "title": self.title, "category": self.category,
            "category_label": CATEGORIES.get(self.category, self.category),
            "section": self.section, "description": self.description,
            "version": self.version, "exec_kind": self.exec_kind, "kind": self.kind,
            "default_enabled": self.default_enabled, "needs_double_blind": self.needs_double_blind,
            "params": self.params, "param_help": self.param_help, "services": list(self.services),
        }


CHECKS: dict[str, CheckSpec] = {}


def check(id, title, category, section, description, **kw):
    def deco(fn):
        if id in CHECKS:
            raise ValueError(f"duplicate check id {id}")
        CHECKS[id] = CheckSpec(id=id, title=title, category=category, section=section,
                               description=description, fn=fn, **kw)
        return fn
    return deco


def ordered_checks() -> list[CheckSpec]:
    return sorted(CHECKS.values(), key=lambda c: (COST_ORDER.get(c.exec_kind, 9), c.section, c.id))
