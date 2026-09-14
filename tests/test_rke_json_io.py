from dataclasses import dataclass
import json
from pathlib import Path

import pytest

from mosaic.rke.json_io import jsonable, write_json


@dataclass
class Report:
    labels: tuple[str, ...]
    counts: dict[int, int]


def test_registry_json_keeps_dataclasses_unicode_and_existing_format(tmp_path: Path):
    payload = {"report": Report(labels=("宏观",), counts={1: 2}), "values": {3}}
    expected = {"report": {"labels": ["宏观"], "counts": {"1": 2}}, "values": [3]}
    assert jsonable(payload) == expected
    path = tmp_path / "registry" / "report.json"
    assert write_json(path, payload) == {"path": str(path), "rows": 1}
    assert path.read_text(encoding="utf-8") == (
        json.dumps(expected, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )


def test_registry_json_rejects_unsupported_values(tmp_path: Path):
    with pytest.raises(TypeError):
        write_json(tmp_path / "report.json", {"unsupported": object()})
