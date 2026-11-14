"""Tests for the configuration loader."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from harmonizer.config import default_config_path, load_config, snapshot_config


def test_default_config_loads_and_has_expected_sections() -> None:
    config = load_config()

    for section in ("project", "paths", "schema", "confidence", "temporal", "spatial", "matching"):
        assert section in config, f"missing config section: {section}"


def test_default_config_path_exists() -> None:
    assert default_config_path().is_file()


def test_placeholder_values_are_not_invented_science() -> None:
    """Phase 00 must not ship scientific values that look decided."""
    config = load_config()

    assert config["spatial"]["grid_km"] is None
    assert config["temporal"]["time_window_h"] is None
    assert config["matching"]["match_radius_m"] is None


def test_missing_file_raises() -> None:
    with pytest.raises(FileNotFoundError):
        load_config("config/does-not-exist.yaml")


def test_non_mapping_raises(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("- just\n- a\n- list\n", encoding="utf-8")

    with pytest.raises(ValueError):
        load_config(bad)


def test_snapshot_is_a_deep_copy() -> None:
    config = load_config()
    snapshot = snapshot_config(config)

    assert snapshot == config
    snapshot["project"]["name"] = "changed"
    assert config["project"]["name"] != "changed"


def test_config_roundtrip_to_yaml(tmp_path: Path) -> None:
    config = load_config()
    target = tmp_path / "snapshot.yaml"
    target.write_text(yaml.safe_dump(config), encoding="utf-8")

    assert load_config(target) == config
