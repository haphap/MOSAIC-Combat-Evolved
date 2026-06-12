"""Temporary-directory helpers for RKE commands."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


RKE_OPERATOR_TMPDIR = "/home/hap/tmp/mosaic-rke"
RKE_OPERATOR_TMP_ENV_PREFIX = (
    f"MOSAIC_RKE_TMPDIR={RKE_OPERATOR_TMPDIR} TMPDIR={RKE_OPERATOR_TMPDIR}"
)


def operator_command(command: str) -> str:
    """Prefix each shell command segment with the RKE temp workspace."""
    return " && ".join(
        f"{RKE_OPERATOR_TMP_ENV_PREFIX} {segment.strip()}"
        for segment in command.split(" && ")
        if segment.strip()
    )


def rke_temporary_directory(prefix: str) -> tempfile.TemporaryDirectory[str]:
    """Create an RKE temporary directory outside the repo and system tmpfs."""
    tmp_parent = str(os.environ.get("MOSAIC_RKE_TMPDIR") or RKE_OPERATOR_TMPDIR).strip()
    parent = Path(tmp_parent).expanduser()
    parent.mkdir(parents=True, exist_ok=True)
    return tempfile.TemporaryDirectory(prefix=prefix, dir=str(parent))
