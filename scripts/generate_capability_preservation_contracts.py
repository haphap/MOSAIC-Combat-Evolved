"""Regenerate staged preservation and KNOT contract artifacts."""

from __future__ import annotations

from pathlib import Path

from mosaic.scorecard.capability_preservation import write_default_contract_artifacts


def main() -> None:
    write_default_contract_artifacts(Path(__file__).resolve().parents[1])


if __name__ == "__main__":
    main()
