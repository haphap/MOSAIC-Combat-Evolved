"""Bridge handler modules.

Importing this package imports every handler submodule, which registers their
JSON-RPC methods via ``@method`` decorators. Add new handler modules here.

Phase 0 Day 1: tools / config / cache / paper / backtest are wired up.
Phase 3 Day 1: scorecard / darwinian added.
Phase 3.5 Day 1: calendar (PR #4 review hotfix) added.
Phase 4 (4B): prompts added.
Phase 6: janus added.
Later phases will add: mirofish.
"""

from __future__ import annotations

from . import autoresearch  # noqa: F401
from . import backtest  # noqa: F401
from . import cache  # noqa: F401
from . import calendar  # noqa: F401
from . import config  # noqa: F401
from . import darwinian  # noqa: F401
from . import janus  # noqa: F401
from . import paper  # noqa: F401
from . import prism  # noqa: F401
from . import prompts  # noqa: F401
from . import scorecard  # noqa: F401
from . import tools  # noqa: F401
