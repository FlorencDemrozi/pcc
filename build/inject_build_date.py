"""
inject_build_date.py — replaces BUILD_DATE_PLACEHOLDER in trial.py
with today's date at build time. Run this before PyInstaller.
"""
import re
from datetime import date
from pathlib import Path

TRIAL_FILE = Path(__file__).parent.parent / "backend" / "trial.py"

content = TRIAL_FILE.read_text()
today = date.today().strftime("%Y-%m-%d")
content = re.sub(
    r'BUILD_DATE\s*=\s*"[^"]*"',
    f'BUILD_DATE = "{today}"',
    content,
)
TRIAL_FILE.write_text(content)
print(f"Build date injected: {today}")
