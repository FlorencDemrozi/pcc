"""One finding format, used by every check."""

import hashlib
from dataclasses import dataclass, field, asdict
from typing import Optional

# How much attention a finding deserves (not a verdict).
SEVERITIES = ("high", "medium", "low", "info")

# issue    : the check found a concrete problem (evidence attached)
# possible : something a person should look at; may be harmless
# info     : recorded for context only
OUTCOMES = ("issue", "possible", "info")

# technical : compliance with the call (format, files, anonymity, references)
# scientific: concerns about the content (numbers, claims) -- kept separate
KINDS = ("technical", "scientific")


@dataclass
class Evidence:
    page: Optional[int] = None      # 1-based page number, None = whole document
    excerpt: str = ""               # short quote from the paper
    source: str = ""                # where it came from: "text", "pdf-metadata", "annotation", "crossref", ...

    def to_dict(self):
        return asdict(self)


@dataclass
class Finding:
    check_id: str
    title: str                      # short label, e.g. "Acknowledgement section in a double-blind paper"
    outcome: str = "issue"
    severity: str = "medium"
    detail: str = ""                # one or two sentences explaining what was found
    evidence: list = field(default_factory=list)   # list[Evidence]
    confidence: float = 0.8         # 0..1, how sure the check is that this is real
    limitations: str = ""           # what the check cannot see
    suggested_action: str = ""      # what the chair might do
    # Filled by the runner from the check spec
    category: str = ""
    kind: str = "technical"
    section: int = 0

    def key(self) -> str:
        """Stable id so a chair decision survives re-runs. Built from the check
        and the evidence (not the wording), so rewording a message keeps it."""
        ev = "|".join(f"{e.page}:{e.excerpt[:80]}" for e in self.evidence[:3])
        raw = f"{self.check_id}|{self.title}|{ev}"
        return self.check_id + ":" + hashlib.sha1(raw.encode("utf-8", "ignore")).hexdigest()[:12]

    def to_dict(self):
        d = asdict(self)
        d["evidence"] = [e.to_dict() if isinstance(e, Evidence) else e for e in self.evidence]
        d["key"] = self.key()
        return d


def ev(page=None, excerpt="", source="text") -> Evidence:
    excerpt = " ".join(str(excerpt or "").split())
    if len(excerpt) > 300:
        excerpt = excerpt[:297] + "..."
    return Evidence(page=page, excerpt=excerpt, source=source)
