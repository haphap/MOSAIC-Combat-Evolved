from __future__ import annotations

import json
import shutil
from pathlib import Path

from mosaic.rke.prompt_evolution_delivery import canonical_hash


ROOT = Path(__file__).resolve().parents[1]
PERFORMANCE_BUDGET = (
    ROOT
    / "registry/prompt_checks/prompt_evolution_performance_budget_v1.json"
)


def test_registry_copy_excludes_private_cache_and_stays_within_budget(
    tmp_path: Path,
) -> None:
    budget = json.loads(PERFORMANCE_BUDGET.read_text(encoding="utf-8"))
    declared_hash = budget.pop("manifest_hash")
    assert declared_hash == canonical_hash(budget)
    fixture_budget = budget["fixture_budget"]

    copied_registry = tmp_path / "registry"
    shutil.copytree(ROOT / "registry", copied_registry)
    copied_files = [path for path in copied_registry.rglob("*") if path.is_file()]
    copied_bytes = sum(path.stat().st_size for path in copied_files)
    print(
        "PROMPT_EVOLUTION_MEASUREMENTS="
        + json.dumps(
            {
                "pytest_registry_copy_bytes": copied_bytes,
                "pytest_registry_copy_files": len(copied_files),
            },
            sort_keys=True,
        )
    )

    assert len(copied_files) <= fixture_budget["max_copied_files"]
    assert copied_bytes <= fixture_budget["max_copied_bytes"]
    for prefix in fixture_budget["forbidden_private_prefixes"]:
        assert not (copied_registry / prefix).exists()
