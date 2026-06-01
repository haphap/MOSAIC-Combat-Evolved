"""MkDocs build hooks for the MOSAIC docs site.

``docs/wiki/`` is also browsed directly on github.com, so its pages link to
repo files (``../../README.md``, ``../../mosaic-tsplan.md``, …) with relative
paths that *escape* ``docs_dir``. Those don't resolve on the built site, so we
rewrite any link that points outside ``docs/wiki/`` to an absolute GitHub blob
URL. Links that stay inside ``docs/wiki/`` (incl. the ``../Home.md`` /
``zh/Home.md`` language switchers) are left untouched for MkDocs to resolve.
"""

from __future__ import annotations

import os
import re

BLOB_BASE = "https://github.com/haphap/MOSAIC-Agents/blob/main"
DOCS_DIR = "docs/wiki"

# Relative Markdown links only (skip absolute URLs, in-page anchors, abs paths).
_LINK = re.compile(r"\]\((?!https?:|/|#)([^)#]+\.md)((?:#[^)]*)?)\)")


def on_page_markdown(markdown: str, *, page, **_: object) -> str:
    page_dir = os.path.dirname(os.path.join(DOCS_DIR, page.file.src_path))

    def _repl(m: re.Match[str]) -> str:
        target, anchor = m.group(1), m.group(2)
        repo_path = os.path.normpath(os.path.join(page_dir, target))
        inside = repo_path == DOCS_DIR or repo_path.startswith(DOCS_DIR + os.sep)
        if inside:
            return m.group(0)  # internal page link — let MkDocs resolve it
        return f"]({BLOB_BASE}/{repo_path}{anchor})"

    return _LINK.sub(_repl, markdown)
