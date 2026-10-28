"""Regression guards for Home Assistant 2026.11 compatibility."""

from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "rejuvenation_bed"
FLOW_RESULT_METHODS = {
    "async_show_form",
    "async_show_menu",
    "async_show_progress",
    "async_external_step",
}


def _source_files() -> list[Path]:
    return sorted(INTEGRATION.rglob("*.py"))


def test_config_flow_results_pass_step_id() -> None:
    """Newer Core warns when custom flows omit the current step ID."""
    failures: list[str] = []
    for path in _source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in FLOW_RESULT_METHODS:
                continue
            if any(keyword.arg == "step_id" for keyword in node.keywords):
                continue
            failures.append(
                f"{path.relative_to(INTEGRATION)}:{node.lineno} "
                f"{node.func.attr}() without step_id"
            )

    assert not failures, "\n".join(failures)


def test_device_info_does_not_pass_deprecated_via_device_keyword() -> None:
    """Modern DeviceInfo uses via_device_id; older Core fallback is feature-gated."""
    failures: list[str] = []
    for path in _source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Name) or node.func.id != "DeviceInfo":
                continue
            if any(keyword.arg == "via_device" for keyword in node.keywords):
                failures.append(
                    f"{path.relative_to(INTEGRATION)}:{node.lineno} "
                    "DeviceInfo(via_device=...)"
                )

    assert not failures, "\n".join(failures)


def test_climate_temperature_api_is_version_gated() -> None:
    """Use native property names only when the running Core provides them."""
    source = (INTEGRATION / "climate.py").read_text(encoding="utf-8")
    assert 'if hasattr(ClimateEntity, "native_current_temperature"):' in source
    assert "def native_current_temperature(" in source
    assert "def native_target_temperature(" in source
    assert "def current_temperature(" in source
    assert "def target_temperature(" in source
    assert "_attr_native_temperature_unit = UnitOfTemperature.CELSIUS" in source
    assert "_attr_temperature_unit = UnitOfTemperature.CELSIUS" in source

def test_manifest_declares_a_home_assistant_category() -> None:
    """Keep the custom integration discoverable in the HACS catalog."""
    manifest = json.loads(
        (INTEGRATION / "manifest.json").read_text(encoding="utf-8")
    )
    categories = manifest.get("categories", [])
    assert 1 <= len(categories) <= 3
    assert "climate.thermostats_heating" in categories
