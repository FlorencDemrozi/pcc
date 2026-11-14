"""
prereview — pre-review screening module.

Purpose: find submission problems and collect evidence for the chairs.
It never makes acceptance decisions and never infers misconduct on its own:
every finding is evidence for a person to confirm, dismiss or ask about.

Layout
  findings.py   one finding format shared by every check
  registry.py   @check decorator: what a check needs, costs and reads
  docmodel.py   extract once per PDF -> a cached document model
  store.py      SQLite (Python's built-in sqlite3) under ~/.pcc/prereview/
  runner.py     runs the enabled checks, reusing results whose inputs are unchanged
  checks_*.py   the checks themselves, one file per spec section group

Paper content is untrusted data: it is only ever matched with regexes and
measured, never executed and never treated as instructions.
"""

from . import checks_integrity, checks_format, checks_anonymity  # noqa: F401  (register checks)
from . import checks_references, checks_manipulation, checks_numbers, checks_figures  # noqa: F401
