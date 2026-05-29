"""Bridge handler modules.

Importing this package imports every handler submodule, which registers their
JSON-RPC methods via ``@method`` decorators. Add new handler modules here.

Phase 0 Day 1: tools / config / cache / paper / backtest are wired up.
Phase 3 Day 1: scorecard / darwinian added.
Later phases will add: autoresearch, prism, janus, mirofish, prompts.
"""

from __future__ import annotations

from . import backtest  # noqa: F401
from . import cache  # noqa: F401
from . import config  # noqa: F401
from . import darwinian  # noqa: F401
from . import paper  # noqa: F401
from . import scorecard  # noqa: F401
from . import tools  # noqa: F401
