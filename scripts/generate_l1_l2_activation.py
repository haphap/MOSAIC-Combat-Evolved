#!/usr/bin/env python3
"""Publish the validated PR12 L1/L2 tool and route fixed point."""

from __future__ import annotations

from pathlib import Path

from mosaic.scorecard.l1_l2_activation import write_l1_l2_active_manifests


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    for name, path in write_l1_l2_active_manifests(root).items():
        print(f"{name}: {path.relative_to(root)}")


if __name__ == "__main__":
    main()
