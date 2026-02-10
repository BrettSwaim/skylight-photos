"""Configuration management for Skylight Photos."""

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional


def get_config_path() -> Path:
    """Get the path to the settings.json config file."""
    backend_dir = Path(__file__).parent
    project_root = backend_dir.parent
    return project_root / "config" / "settings.json"


@lru_cache()
def get_settings() -> dict:
    """Load and cache settings from config file."""
    config_path = get_config_path()

    if not config_path.exists():
        raise FileNotFoundError(
            f"Config file not found at {config_path}. "
            "Copy config/settings.example.json to config/settings.json."
        )

    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_config_value(key: str, default: Optional[Any] = None) -> Any:
    """Get a config value by dot-notation key."""
    settings = get_settings()
    keys = key.split(".")
    value = settings

    for k in keys:
        if isinstance(value, dict):
            value = value.get(k)
        else:
            return default
        if value is None:
            return default

    return value
