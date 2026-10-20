"""Task 2.2: versioned, company-neutral YAML prompts, plus the check that fails if one names a company."""
from __future__ import annotations
import re
from pathlib import Path
from typing import Iterable, Optional

import yaml

PROMPT_DIR = Path(__file__).resolve().parent / "prompts"


def load(prompt_id: str) -> dict:
    p = PROMPT_DIR / f"{prompt_id}.yaml"
    if not p.exists():
        raise FileNotFoundError(f"unknown prompt: {prompt_id}")
    spec = yaml.safe_load(p.read_text(encoding="utf-8"))
    for k in ("id", "version", "purpose", "inputs", "system", "template"):
        if k not in spec:
            raise ValueError(f"prompt {prompt_id} is missing field: {k}")
    return spec


def list_ids() -> list[str]:
    return sorted(p.stem for p in PROMPT_DIR.glob("*.yaml"))


class _Safe(dict):
    def __missing__(self, key):
        raise KeyError(f"prompt input missing: {key}")


def render(spec: dict, inputs: dict) -> tuple[str, str]:
    missing = [k for k in spec["inputs"] if k not in inputs]
    if missing:
        raise KeyError(f"prompt {spec['id']} needs inputs: {', '.join(missing)}")
    return spec["system"].strip(), spec["template"].format_map(_Safe(inputs)).strip()


def check_company_neutral(names: Iterable[str], extra_forbidden: Optional[list[str]] = None) -> list[str]:
    """Return problems: any universe company name or a currency/large-number figure inside a prompt file."""
    problems: list[str] = []
    needles = [n.strip().lower() for n in names if n and len(n.strip()) > 3]
    for pid in list_ids():
        text = (PROMPT_DIR / f"{pid}.yaml").read_text(encoding="utf-8").lower()
        for n in needles + [x.lower() for x in (extra_forbidden or [])]:
            if re.search(r"\b" + re.escape(n) + r"\b", text):
                problems.append(f"{pid}: contains company name '{n}'")
        if re.search(r"₹|\brs\.?\s?\d|\b\d{4,}\b", text):
            problems.append(f"{pid}: contains a currency or large number")
    return problems
