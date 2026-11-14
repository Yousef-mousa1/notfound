"""Configuration loading.

All scientific parameters live in ``config/`` (see AGENTS.md, Code Standards).
Code reads them here instead of hardcoding values, so a run is reproducible
from its saved configuration snapshot.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = Path("config") / "default.yaml"


def project_root() -> Path:
    """Return the project root (the directory containing ``config/``)."""
    return Path(__file__).resolve().parents[2]


def default_config_path() -> Path:
    """Return the absolute path of the default configuration file."""
    return project_root() / DEFAULT_CONFIG_PATH


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load a YAML configuration file.

    Args:
        path: Configuration file to read. ``None`` loads ``config/default.yaml``.

    Returns:
        The parsed configuration as a dictionary.

    Raises:
        FileNotFoundError: If the configuration file does not exist.
        ValueError: If the file is empty or does not contain a mapping.
    """
    config_path = Path(path) if path is not None else default_config_path()
    if not config_path.is_file():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)

    if not isinstance(data, dict) or not data:
        raise ValueError(f"Configuration must be a non-empty mapping: {config_path}")
    return data


def snapshot_config(config: dict[str, Any]) -> dict[str, Any]:
    """Return a deep copy suitable for saving next to a run's outputs.

    The copy prevents later in-memory changes from silently altering the record
    of what a run actually used (reproducibility requirement).
    """
    return copy.deepcopy(config)


def resolve_path(config: dict[str, Any], *keys: str) -> Path:
    """Resolve a configured relative path against the project root.

    Args:
        config: Loaded configuration mapping.
        *keys: Path of the setting inside the configuration, e.g. ``("paths", "raw")``.

    Returns:
        Absolute path. Relative values are interpreted from the project root.

    Raises:
        KeyError: If the configuration key is missing.
        ValueError: If the configured value is empty.
    """
    node: Any = config
    for key in keys:
        if not isinstance(node, dict) or key not in node:
            raise KeyError(".".join(keys))
        node = node[key]

    if not isinstance(node, (str, Path)) or str(node).strip() == "":
        raise ValueError(f"Configuration value {'/'.join(keys)} is not a path")

    path = Path(node)
    return path if path.is_absolute() else project_root() / path
