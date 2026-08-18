"""Regenerate staged preservation and KNOT contract artifacts."""

from __future__ import annotations

from pathlib import Path

from mosaic.scorecard.capability_preservation import write_default_contract_artifacts
from mosaic.scorecard.l3_l4_preservation import write_l3_l4_preservation_overlay
from mosaic.scorecard.macro_europe_preservation import (
    write_macro_europe_preservation_overlay,
)
from mosaic.scorecard.macro_us_preservation import write_macro_us_preservation_overlay
from mosaic.scorecard.sector_relationship_preservation import (
    write_sector_relationship_preservation_overlay,
)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    write_sector_relationship_preservation_overlay(root)
    write_l3_l4_preservation_overlay(root)
    write_macro_us_preservation_overlay(root)
    write_macro_europe_preservation_overlay(root)
    write_default_contract_artifacts(root)


if __name__ == "__main__":
    main()
