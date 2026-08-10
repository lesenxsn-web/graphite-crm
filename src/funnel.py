from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_stages(path: str | Path = "config/stages.yaml") -> list[dict[str, Any]]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return payload["stages"]


def stage_names(active_only: bool = False) -> list[str]:
    stages = load_stages()
    if active_only:
        stages = [stage for stage in stages if stage.get("active")]
    return [stage["name"] for stage in stages]


def probability_for(stage_name: str) -> float:
    for stage in load_stages():
        if stage["name"] == stage_name:
            return float(stage["probability"])
    return 0.0
