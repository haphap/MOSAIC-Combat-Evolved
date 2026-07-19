from __future__ import annotations

import hashlib
import json
import sys
from copy import deepcopy
from pathlib import Path
from types import ModuleType

import pytest

from mosaic.autoresearch import private_knot_runtime as private_runtime
from mosaic.scorecard import knot_v2
from mosaic.autoresearch import domain_evaluator, domain_metrics
from mosaic.autoresearch.private_knot_runtime import clear_private_knot_runtime_cache
from scripts import check_private_knot_boundary as boundary_check


def test_public_tree_forbids_private_prompt_ir_assets() -> None:
    prompts_root = (
        Path(__file__).resolve().parents[1]
        / "mosaic-ts"
        / "src"
        / "agents"
        / "prompts"
    )

    for name in ("prompt_ir_registry.ts", "tool_metric_registry.ts"):
        private_asset = prompts_root / name
        assert private_asset in boundary_check.FORBIDDEN_PUBLIC_ASSETS
        assert not private_asset.exists()


def test_knot_runtime_fails_closed_without_private_repo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "MOSAIC_KNOT_RUNTIME_ROOT",
        "MOSAIC_PROMPTS_REPO",
        "MOSAIC_PRIVATE_PROMPT_REPO",
    ):
        monkeypatch.delenv(name, raising=False)
    clear_private_knot_runtime_cache()

    assert knot_v2.private_knot_runtime_available() is False
    with pytest.raises(RuntimeError, match="not configured"):
        knot_v2.__getattr__("private_export")

    clear_private_knot_runtime_cache()
    with pytest.raises(RuntimeError, match="not configured"):
        domain_evaluator.__getattr__("evaluate_domain_mutation")
    with pytest.raises(RuntimeError, match="not configured"):
        domain_metrics.__getattr__("calculate_rank_correlation")


def test_knot_runtime_rejects_unpinned_private_module(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module_path = tmp_path / "runtime" / "python" / "mosaic_knot" / "knot_v2.py"
    module_path.parent.mkdir(parents=True)
    module_path.write_text("private_export = 1\n", encoding="utf-8")
    monkeypatch.setenv("MOSAIC_KNOT_RUNTIME_ROOT", str(tmp_path))
    clear_private_knot_runtime_cache()

    with pytest.raises(RuntimeError, match="manifest is unavailable"):
        knot_v2.__getattr__("private_export")


def test_public_knot_reference_contains_hashes_only() -> None:
    root = Path(__file__).resolve().parents[1]
    ref = json.loads(
        (
            root
            / "registry"
            / "prompt_checks"
            / "knot_runtime_contract_ref_v2.json"
        ).read_text(encoding="utf-8")
    )

    assert set(ref) == {
        "knot_runtime_contract_manifest_id",
        "knot_runtime_contract_manifest_version",
        "knot_runtime_contract_manifest_hash",
        "private_runtime_manifest_hash",
        "research_score_contract_ref",
        "scheduler_contract_ref",
    }
    serialized = json.dumps(ref, sort_keys=True)
    assert "minimum_accountable_pairs" not in serialized
    assert "promotion_mean_delta_floor" not in serialized
    assert ref["private_runtime_manifest_hash"].startswith("sha256:")
    digest = ref["private_runtime_manifest_hash"].removeprefix("sha256:")
    assert len(bytes.fromhex(digest)) == hashlib.sha256().digest_size


def test_boundary_rejects_drifted_nested_knot_contract_reference(
    tmp_path: Path,
) -> None:
    score = {
        "research_score_contract_id": "knot-research-score",
        "research_score_contract_version": "knot_research_score_v2",
        "private_value": 1,
    }
    score_hash = boundary_check._canonical_hash(score)
    scheduler = {
        "scheduler_contract_id": "knot-scheduler",
        "scheduler_contract_version": "knot_scheduler_v2",
        "private_value": 2,
    }
    scheduler_hash = boundary_check._canonical_hash(scheduler)
    manifest_without_hash = {
        "knot_runtime_contract_manifest_id": "knot-runtime-contract",
        "knot_runtime_contract_manifest_version": "knot_runtime_contract_manifest_v2",
        "research_score_contract": {
            **score,
            "research_score_contract_hash": score_hash,
        },
        "scheduler_contract": {
            **scheduler,
            "scheduler_contract_hash": scheduler_hash,
        },
    }
    manifest = {
        **manifest_without_hash,
        "knot_runtime_contract_manifest_hash": boundary_check._canonical_hash(
            manifest_without_hash
        ),
    }
    path = tmp_path / "registry" / "knot" / "knot_runtime_contract_manifest_v2.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(manifest), encoding="utf-8")
    reference = {
        "knot_runtime_contract_manifest_id": manifest[
            "knot_runtime_contract_manifest_id"
        ],
        "knot_runtime_contract_manifest_version": manifest[
            "knot_runtime_contract_manifest_version"
        ],
        "knot_runtime_contract_manifest_hash": manifest[
            "knot_runtime_contract_manifest_hash"
        ],
        "research_score_contract_ref": {
            "research_score_contract_id": score["research_score_contract_id"],
            "research_score_contract_version": score[
                "research_score_contract_version"
            ],
            "research_score_contract_hash": score_hash,
        },
        "scheduler_contract_ref": {
            "scheduler_contract_id": scheduler["scheduler_contract_id"],
            "scheduler_contract_version": scheduler["scheduler_contract_version"],
            "scheduler_contract_hash": scheduler_hash,
        },
    }

    boundary_check._check_knot_contract_reference(tmp_path, reference)
    drifted = deepcopy(reference)
    drifted["scheduler_contract_ref"]["scheduler_contract_hash"] = f"sha256:{'0' * 64}"
    with pytest.raises(ValueError, match="nested contract reference mismatch"):
        boundary_check._check_knot_contract_reference(tmp_path, drifted)


def test_boundary_rejects_drifted_private_asset_metadata(tmp_path: Path) -> None:
    catalog = {
        "schema_version": "domain_knob_catalog_v1",
        "catalog_version": "domain_knob_catalog_v1",
        "agents": [],
    }
    catalog_path = tmp_path / "registry" / "knot" / "domain_knob_catalog_v1.json"
    catalog_path.parent.mkdir(parents=True)
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    schema_path = tmp_path / "schemas" / "domain_knob_evaluation_contract_v1.schema.json"
    schema_path.parent.mkdir(parents=True)
    schema_path.write_text("{}\n", encoding="utf-8")
    metrics = {"metric": {"direction": "higher_is_better"}}
    calculators = {"calculator": {"version": "1"}}
    contract_without_hash = {
        "schema_version": "domain_knob_evaluation_contract_v1",
        "contract_version": "domain_knob_evaluation_contract_v1",
        "catalog_version": "domain_knob_catalog_v1",
        "schema_hash": boundary_check._sha256(schema_path),
        "catalog_hash": boundary_check._ordered_json_hash(catalog),
        "metric_registry_hash": boundary_check._ordered_json_hash(metrics),
        "calculator_registry_hash": boundary_check._ordered_json_hash(calculators),
        "evaluation_metrics": metrics,
        "evaluation_calculators": calculators,
        "generic_bindings": [],
        "card_bindings": [],
    }
    contract = {
        **contract_without_hash,
        "contract_hash": boundary_check._ordered_json_hash(contract_without_hash),
    }
    contract_path = (
        tmp_path
        / "registry"
        / "knot"
        / "domain_knob_evaluation_contract_v1.json"
    )
    contract_path.write_text(json.dumps(contract), encoding="utf-8")
    reference = {
        "schema_version": "private_knot_assets_ref_v1",
        "domain_knob_catalog": {
            "private_relative_path": "registry/knot/domain_knob_catalog_v1.json",
            "file_hash": boundary_check._sha256(catalog_path),
            "catalog_version": catalog["catalog_version"],
            "catalog_hash": contract_without_hash["catalog_hash"],
        },
        "evaluation_contract": {
            "private_relative_path": (
                "registry/knot/domain_knob_evaluation_contract_v1.json"
            ),
            "file_hash": boundary_check._sha256(contract_path),
            "contract_version": contract["contract_version"],
            "schema_hash": contract["schema_hash"],
            "catalog_hash": contract["catalog_hash"],
            "metric_registry_hash": contract["metric_registry_hash"],
            "calculator_registry_hash": contract["calculator_registry_hash"],
            "contract_hash": contract["contract_hash"],
        },
    }

    boundary_check._check_private_asset_references(tmp_path, reference)
    drifted = deepcopy(reference)
    drifted["evaluation_contract"]["metric_registry_hash"] = f"sha256:{'0' * 64}"
    with pytest.raises(ValueError, match="reference metadata mismatch"):
        boundary_check._check_private_asset_references(tmp_path, drifted)


def test_private_knot_loader_rejects_unregistered_relative_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public_ref = _write_private_runtime_fixture(
        tmp_path,
        registered={
            "knot_engine": (
                "runtime/python/mosaic_knot/knot_v2.py",
                "from .domain_metrics import VALUE\nprivate_export = VALUE\n",
            ),
            "python_package": ("runtime/python/mosaic_knot/__init__.py", ""),
        },
        extra_files={"runtime/python/mosaic_knot/domain_metrics.py": "VALUE = 1\n"},
    )
    monkeypatch.setattr(private_runtime, "_PUBLIC_REF_PATH", public_ref)
    monkeypatch.setenv("MOSAIC_KNOT_RUNTIME_ROOT", str(tmp_path))
    clear_private_knot_runtime_cache()

    with pytest.raises(RuntimeError, match="unregistered modules"):
        knot_v2.__getattr__("private_export")
    clear_private_knot_runtime_cache()


def test_private_knot_loader_verifies_registered_relative_import_hashes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dependency_path = "runtime/python/mosaic_knot/domain_metrics.py"
    public_ref = _write_private_runtime_fixture(
        tmp_path,
        registered={
            "knot_engine": (
                "runtime/python/mosaic_knot/knot_v2.py",
                "from .domain_metrics import VALUE\nprivate_export = VALUE\n",
            ),
            "domain_metrics": (dependency_path, "VALUE = 1\n"),
            "python_package": ("runtime/python/mosaic_knot/__init__.py", ""),
        },
    )
    (tmp_path / dependency_path).write_text("VALUE = 2\n", encoding="utf-8")
    monkeypatch.setattr(private_runtime, "_PUBLIC_REF_PATH", public_ref)
    monkeypatch.setenv("MOSAIC_KNOT_RUNTIME_ROOT", str(tmp_path))
    clear_private_knot_runtime_cache()

    with pytest.raises(RuntimeError, match="integrity check failed"):
        knot_v2.__getattr__("private_export")
    clear_private_knot_runtime_cache()


@pytest.mark.parametrize(
    "extra_path",
    [
        "runtime/python/mosaic_knot/rogue.pyc",
        "runtime/python/mosaic_knot/rogue.so",
        "runtime/python/mosaic_knot/rogue.pyd",
    ],
)
def test_private_knot_loader_rejects_unregistered_importable_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    extra_path: str,
) -> None:
    public_ref = _write_private_runtime_fixture(
        tmp_path,
        registered={
            "knot_engine": (
                "runtime/python/mosaic_knot/knot_v2.py",
                "private_export = 1\n",
            ),
            "python_package": ("runtime/python/mosaic_knot/__init__.py", ""),
        },
        extra_files={extra_path: "not trusted\n"},
    )
    monkeypatch.setattr(private_runtime, "_PUBLIC_REF_PATH", public_ref)
    monkeypatch.setenv("MOSAIC_KNOT_RUNTIME_ROOT", str(tmp_path))
    clear_private_knot_runtime_cache()

    with pytest.raises(RuntimeError, match="unregistered importable file"):
        knot_v2.__getattr__("private_export")
    clear_private_knot_runtime_cache()


def test_private_knot_loader_rejects_symlink_and_namespace_injection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public_ref = _write_private_runtime_fixture(
        tmp_path,
        registered={
            "knot_engine": (
                "runtime/python/mosaic_knot/knot_v2.py",
                "private_export = 1\n",
            ),
            "python_package": ("runtime/python/mosaic_knot/__init__.py", ""),
        },
    )
    package_root = tmp_path / "runtime" / "python" / "mosaic_knot"
    (package_root / "rogue_namespace").mkdir()
    monkeypatch.setattr(private_runtime, "_PUBLIC_REF_PATH", public_ref)
    monkeypatch.setenv("MOSAIC_KNOT_RUNTIME_ROOT", str(tmp_path))
    clear_private_knot_runtime_cache()

    with pytest.raises(RuntimeError, match="unregistered namespace"):
        knot_v2.__getattr__("private_export")
    clear_private_knot_runtime_cache()

    (package_root / "rogue_namespace").rmdir()
    (package_root / "rogue.py").symlink_to(package_root / "knot_v2.py")
    with pytest.raises(RuntimeError, match="symlink"):
        knot_v2.__getattr__("private_export")
    clear_private_knot_runtime_cache()


def test_private_knot_loader_never_executes_registered_module_bytecode_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public_ref = _write_private_runtime_fixture(
        tmp_path,
        registered={
            "knot_engine": (
                "runtime/python/mosaic_knot/knot_v2.py",
                "from .domain_metrics import VALUE\nprivate_export = VALUE\n",
            ),
            "domain_metrics": (
                "runtime/python/mosaic_knot/domain_metrics.py",
                "VALUE = 1\n",
            ),
            "python_package": ("runtime/python/mosaic_knot/__init__.py", ""),
        },
    )
    cache = (
        tmp_path
        / "runtime"
        / "python"
        / "mosaic_knot"
        / "__pycache__"
        / "domain_metrics.cpython-313.pyc"
    )
    cache.parent.mkdir()
    cache.write_bytes(b"malicious-bytecode-placeholder")
    monkeypatch.setattr(private_runtime, "_PUBLIC_REF_PATH", public_ref)
    monkeypatch.setenv("MOSAIC_KNOT_RUNTIME_ROOT", str(tmp_path))
    clear_private_knot_runtime_cache()

    assert knot_v2.__getattr__("private_export") == 1
    clear_private_knot_runtime_cache()


def test_private_knot_loader_verifies_non_python_runtime_assets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract_path = "registry/knot/knot_runtime_contract_manifest_v2.json"
    public_ref = _write_private_runtime_fixture(
        tmp_path,
        registered={
            "knot_engine": (
                "runtime/python/mosaic_knot/knot_v2.py",
                "private_export = 1\n",
            ),
            "python_package": ("runtime/python/mosaic_knot/__init__.py", ""),
            "knot_runtime_contract": (contract_path, "{}\n"),
        },
    )
    (tmp_path / contract_path).write_text('{"tampered":true}\n', encoding="utf-8")
    monkeypatch.setattr(private_runtime, "_PUBLIC_REF_PATH", public_ref)
    monkeypatch.setenv("MOSAIC_KNOT_RUNTIME_ROOT", str(tmp_path))
    clear_private_knot_runtime_cache()

    with pytest.raises(RuntimeError, match="integrity check failed"):
        knot_v2.__getattr__("private_export")
    clear_private_knot_runtime_cache()


def test_private_knot_loader_discards_preloaded_private_dependencies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public_ref = _write_private_runtime_fixture(
        tmp_path,
        registered={
            "knot_engine": (
                "runtime/python/mosaic_knot/knot_v2.py",
                "from .domain_metrics import VALUE\nprivate_export = VALUE\n",
            ),
            "domain_metrics": (
                "runtime/python/mosaic_knot/domain_metrics.py",
                "VALUE = 1\n",
            ),
            "python_package": ("runtime/python/mosaic_knot/__init__.py", ""),
        },
    )
    monkeypatch.setattr(private_runtime, "_PUBLIC_REF_PATH", public_ref)
    monkeypatch.setenv("MOSAIC_KNOT_RUNTIME_ROOT", str(tmp_path))
    clear_private_knot_runtime_cache()
    stale_dependency = ModuleType("mosaic_knot.domain_metrics")
    stale_dependency.VALUE = 999  # type: ignore[attr-defined]
    sys.modules[stale_dependency.__name__] = stale_dependency

    assert knot_v2.__getattr__("private_export") == 1
    clear_private_knot_runtime_cache()


def _write_private_runtime_fixture(
    root: Path,
    *,
    registered: dict[str, tuple[str, str]],
    extra_files: dict[str, str] | None = None,
) -> Path:
    entries: dict[str, dict[str, str]] = {}
    for logical_name, (relative_path, content) in registered.items():
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        entries[logical_name] = {
            "relative_path": relative_path,
            "sha256": f"sha256:{hashlib.sha256(content.encode()).hexdigest()}",
        }
    for relative_path, content in (extra_files or {}).items():
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    manifest = {
        "schema_version": "private_knot_runtime_manifest_v1",
        "files": entries,
    }
    manifest_raw = f"{json.dumps(manifest, indent=2)}\n"
    manifest_path = root / "registry" / "knot" / "private_runtime_manifest_v1.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(manifest_raw, encoding="utf-8")
    public_ref = root / "public-knot-ref.json"
    public_ref.write_text(
        json.dumps(
            {
                "private_runtime_manifest_hash": (
                    f"sha256:{hashlib.sha256(manifest_raw.encode()).hexdigest()}"
                )
            }
        ),
        encoding="utf-8",
    )
    return public_ref
