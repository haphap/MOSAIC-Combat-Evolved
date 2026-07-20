from __future__ import annotations

import pytest

from mosaic.dataflows.cross_runtime_json import canonical_json


def test_canonical_json_matches_ecmascript_number_serialization() -> None:
    assert canonical_json(
        {
            "numbers": [
                333333333.33333329,
                1e30,
                4.50,
                2e-3,
                1e-27,
                1e-7,
                1e-6,
                1e20,
                1e21,
                -0.0,
            ]
        }
    ) == (
        '{"numbers":[333333333.3333333,1e+30,4.5,0.002,1e-27,'
        '1e-7,0.000001,100000000000000000000,1e+21,0]}'
    )


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_canonical_json_rejects_nonfinite_numbers(value: float) -> None:
    with pytest.raises(ValueError, match="non-finite"):
        canonical_json({"value": value})


def test_canonical_json_accepts_exact_and_rejects_inexact_large_integers() -> None:
    assert canonical_json({"value": 10**20}) == (
        '{"value":100000000000000000000}'
    )
    with pytest.raises(ValueError, match="not exactly representable"):
        canonical_json({"value": 2**53 + 1})
