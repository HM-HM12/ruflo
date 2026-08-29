"""YAML config loaders for risk.yaml and strategy.yaml, with validation."""
from __future__ import annotations

from pathlib import Path

import yaml

CONFIG_DIR = Path(__file__).resolve().parent


def load_yaml(filename: str) -> dict:
    path = CONFIG_DIR / filename
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_risk_config() -> dict:
    return load_yaml("risk.yaml")


def load_strategy_config() -> dict:
    cfg = load_yaml("strategy.yaml")
    weights = cfg.get("scoring_weights", {})
    total = sum(weights.values())
    if abs(total - 1.0) > 1e-6:
        raise ValueError(f"strategy.yaml scoring_weights must sum to 1.0, got {total}")
    return cfg
