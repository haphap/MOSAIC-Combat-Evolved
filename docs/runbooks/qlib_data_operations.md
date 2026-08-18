# Qlib Data Operations Runbook

Use this procedure for stock or ETF incremental updates. It is deliberately
staging-first: never run an ingest against the active Qlib root.

## 1. Gate the checkout and environment

Run from the checkout whose code will perform the update. The collector child
uses the same `sys.executable` as the parent, so both the module path and the
declared extras must pass before any data operation:

```bash
cd "${REPO:?set the MOSAIC checkout}"

uv run python -c '
import sys
print(sys.version)
if sys.version_info[:2] != (3, 12):
    raise SystemExit("Qlib operations require Python 3.12")
'
uv run python -c '
from pathlib import Path
import mosaic.dataflows.qlib_ingest as module

actual = Path(module.__file__).resolve()
expected = (Path.cwd() / "mosaic/dataflows/qlib_ingest.py").resolve()
print(f"qlib_ingest={actual}")
if actual != expected:
    raise SystemExit(f"wrong checkout: expected {expected}")
'
uv run python -c \
  'import bs4, fire, joblib, loguru, qlib, tushare, yahooquery; print("qlib ingest dependencies: ok")'
```

If the version gate fails, stop and select Python 3.12. Then install the
complete declared set; do not try to repair a Python 3.13 environment by
installing only the first missing import:

```bash
uv venv --python 3.12
uv pip install -e '.[data,backtest,ingest]'
```

Do not launch a helper by a deep filesystem path. A deep script directory can
take `sys.path[0]` and make an editable install from another checkout win.

## 2. Resolve roots and take the baseline

Set a fixed target and new sibling paths. `ROOT` may initially be a symlink;
resolve it before fingerprinting or renaming.

```bash
set -euo pipefail

KIND="${KIND:?stock or etf}"
TARGET="${TARGET:?YYYY-MM-DD}"
ROOT_INPUT="${ROOT:?active stock or ETF Qlib root}"
ROOT="$(realpath -e "$ROOT_INPUT")"
STAGING="$(realpath -m "${STAGING:?new same-filesystem sibling}")"
BACKUP="$(realpath -m "${BACKUP:?new same-filesystem sibling}")"
AUDIT="$(realpath -m "${AUDIT:?private or gitignored audit directory}")"

test "$KIND" = stock || test "$KIND" = etf
test "$(dirname "$ROOT")" = "$(dirname "$STAGING")"
test "$(dirname "$ROOT")" = "$(dirname "$BACKUP")"
test ! -e "$STAGING"
test ! -e "$BACKUP"
case "$AUDIT/" in
  "$ROOT/"*|"$STAGING/"*|"$BACKUP/"*)
    echo "AUDIT must be outside all Qlib roots" >&2
    exit 1
    ;;
esac
if pgrep -af '[q]lib_ingest|[u]pdate_data_to_bin|[D]umpDataUpdate|[d]aily-cycle|[b]acktest'; then
  echo "Qlib or consumer process is active; stop" >&2
  exit 1
fi

mkdir -p "$AUDIT"
printf 'input=%s\nresolved=%s\ndevice=%s\n' \
  "$ROOT_INPUT" "$ROOT" "$(stat -c %d "$ROOT")"
du -sb "$ROOT"
df -B1 "$ROOT"
(cd "$ROOT" && find . -type f -print0 | sort -z | xargs -0 sha256sum) \
  > "$AUDIT/active-files.sha256"
sha256sum "$AUDIT/active-files.sha256"
sha256sum "$ROOT/calendars/day.txt" "$ROOT/instruments/all.txt"
```

Confirm free space for a full ordinary copy, even when reflinks are available.
Then create exactly one staging root; `--reflink=auto` uses reflinks where the
filesystem supports them and otherwise copies normally:

```bash
cp --reflink=auto -a "$ROOT" "$STAGING"
test "$(stat -c %d "$ROOT")" = "$(stat -c %d "$STAGING")"
```

Keep the active fingerprint, resolved roots, process result, root size, free
space, calendar, instrument metadata, and staging-copy result in `AUDIT`.

## 3. Run one isolated staging update

Use fresh raw and normalized directories for this attempt. The CLI does not
currently expose those paths, so call its public Python function directly:

```bash
RAW_DIR="$AUDIT/raw"
NORM_DIR="$AUDIT/norm"
mkdir -p "$RAW_DIR" "$NORM_DIR"

uv run python -c '
import sys
from pathlib import Path
from mosaic.dataflows.qlib_ingest import ingest_incremental

outcome = ingest_incremental(
    end=sys.argv[1],
    kind=sys.argv[2],
    qlib_dir=Path(sys.argv[3]),
    raw_dir=Path(sys.argv[4]),
    normalize_dir=Path(sys.argv[5]),
)
raise SystemExit(outcome.returncode)
' "$TARGET" "$KIND" "$STAGING" "$RAW_DIR" "$NORM_DIR"
```

Run this once. On the first error, stop: do not retry, fetch again, or fall back
to a full ingest automatically.

Raw/normalized CSVs are bounded update inputs, not full-history authority. For
stock forced rebuilds caused by retroactive factor detection, compare every
selected CSV's first date with the existing bin's first date. If a CSV starts
later, fail the staging attempt; never replace historical bins with that CSV.
Prefer a tag-bound official release or a verified backup restored to staging.

For existing symbols, the append calendar is the complete market-calendar
slice after the old end through the symbol's real new end. Missing symbol
sessions must be written as `NaN`; later values must remain on their true dates.
New-symbol semantics remain separate.

## 4. Validate before publication

First run the repository validator with a private or gitignored manifest. It
normalizes uppercase metadata codes to lowercase feature paths:

```bash
SKIP_MANIFEST="$AUDIT/skipped.txt"
uv run python -c '
import json
import sys
from pathlib import Path
from mosaic.dataflows.qlib_ingest import validate_after_ingest

report = validate_after_ingest(Path(sys.argv[1]), skip_manifest=Path(sys.argv[2]))
print(json.dumps(report, sort_keys=True))
if report["checked"] != report["instruments"] or report["format_errors"] != 0:
    raise SystemExit(1)
' "$STAGING" "$SKIP_MANIFEST"
```

`checked == instruments` and `format_errors == 0` are mandatory. `skipped` can
include legitimate historical coverage gaps, so classify every skipped row;
do not require zero blindly or hide missing feature files as ordinary gaps.

The structural validator is necessary but not sufficient. Before publication,
a read-only audit must also prove:

- calendar ordering, target coverage, and exact instrument/feature closure;
- every enabled OHLCV/amount/factor bin is present and parseable;
- each pre-update bin is a byte-for-byte prefix of its staged counterpart;
- every normalized row matches the bin value on the same date at float32
  tolerance, and every missing market session inside an append span is `NaN`;
- no bounded-cache rebuild shortened history or caused unexplained instrument
  growth/root shrinkage;
- representative core instruments load through `qlib_local` over a fixed
  historical window and on `TARGET`.

There is no repository CLI for this deep reconciliation. Keep its audit code
and results private/gitignored; if the evidence is unavailable, do not publish.

## 5. Publish and verify

Recheck processes, fingerprints, free space, the deep audit, same-device
identity, and that `BACKUP` is still absent. Publish with two renames and restore
the first immediately if the second fails:

```bash
mv -- "$ROOT" "$BACKUP"
if ! mv -- "$STAGING" "$ROOT"; then
  mv -- "$BACKUP" "$ROOT"
  exit 1
fi
```

Keep every old root. After publication, rerun the checkout/import gate, standard
validator, deep reconciliation, fixed-window/core-reader checks, and process
guard against the new `ROOT`. Confirm `BACKUP` matches the original active
fingerprint and that unrelated stock/ETF roots did not change.

Finally, reissue the existing freeze receipt with the same schema and trading
day list. Update resolved roots, calendar identity, counts, byte totals, and the
canonical relative-file/content hash; then record the receipt's own SHA-256.
Do not invent a new receipt field or publish until stock and ETF calendar bytes
match where the frozen test requires a shared calendar.

## 2026-08-18 incident lessons

- A bounded stock cache was treated as rebuild authority after widespread
  factor mismatches, replacing long histories with short CSV spans. Recovery
  used the official release in staging; future late-start forced rebuilds must
  fail at the operator staging gate.
- Sparse ETF rows were appended against per-symbol dates, shifting later values
  forward. Existing symbols now append on the complete market calendar with
  `NaN` gaps; recovery replayed a complete verified normalized cache onto a
  preserved baseline staging root.
- Uppercase instrument metadata was looked up as an uppercase feature path,
  producing `checked=0`. Validation now normalizes the code and requires full
  checked coverage rather than accepting zero format errors alone.
- A deep helper imported another editable checkout because its script directory
  won `sys.path[0]`. Running from the intended checkout and gating
  `module.__file__` prevents that fallback.
