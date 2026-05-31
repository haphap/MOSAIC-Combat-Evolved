"""Real-engine adapter: drive a deployed 666ghj/MiroFish service over HTTP.

7M Step 3 — the third ``SwarmEngine`` implementation. The real engine
(666ghj/MiroFish) is a full-stack service (Vue + Python :5001, OASIS + Zep +
GraphRAG); it is NOT importable and NOT vendored (AGPL-3.0, 200MB+ deps). So
this is a thin HTTP client, not the engine.

Contract (deployer's responsibility): the service exposes
``POST {MOSAIC_MIROFISH_URL}/scenarios`` accepting
``{seed, num_days, scenarios, start_prices}`` and returning
``{"scenarios": [<montecarlo-shaped scenario dict>, ...]}`` — i.e. each scenario
carries the same keys our Monte-Carlo engine emits (scenario_type / price_paths
/ final_state / ...). A thin server-side translator from MiroFish's native
prediction report to that shape lives on the deployment side, since the report
schema is the service's concern and varies by version. This adapter validates
the shape it gets back and stamps ``engine='oasis'``.

Honest scope: there is no live service in this environment (no endpoint / LLM /
Zep keys / budget), so only the request construction, response mapping, and
failure modes are unit-tested with a fake transport — NOT a real integration.
Pure stdlib (``urllib``), no new dependency; deps-light importable (no numpy).
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Mapping, Optional

DEFAULT_TIMEOUT = 120  # real simulations are slow (README: <40 rounds to start)
_REQUIRED_KEYS = {"scenario_type", "price_paths", "final_state"}


class MiroFishUnavailable(RuntimeError):
    """Raised when the real MiroFish service can't be reached or returns a
    response that doesn't match the expected scenario contract."""


class OasisMiroFishEngine:
    """``SwarmEngine``-shaped HTTP client for a deployed MiroFish service.

    ``base_url`` defaults to ``$MOSAIC_MIROFISH_URL``. Raises
    ``MiroFishUnavailable`` (never silently substitutes Monte-Carlo) so a caller
    that asked for ``engine='oasis'`` is told plainly when the service is down —
    the handler decides whether to surface or fall back.
    """

    def __init__(self, base_url: Optional[str] = None, timeout: int = DEFAULT_TIMEOUT) -> None:
        self._base_url = (base_url or os.environ.get("MOSAIC_MIROFISH_URL") or "").rstrip("/")
        self._timeout = timeout

    def generate_all_scenarios(
        self,
        start_prices: Optional[Mapping[str, float]],
        num_days: int,
        seed: Optional[int],
        scenarios: Optional[list[str]],
    ) -> list[dict[str, Any]]:
        if not self._base_url:
            raise MiroFishUnavailable(
                "engine='oasis' needs a deployed MiroFish service: set MOSAIC_MIROFISH_URL "
                "(e.g. http://localhost:5001)."
            )
        payload = {
            "seed": seed,
            "num_days": num_days,
            "scenarios": scenarios,
            "start_prices": dict(start_prices) if start_prices else None,
        }
        data = self._post("/scenarios", payload)
        out = data.get("scenarios") if isinstance(data, dict) else None
        if not isinstance(out, list) or not out:
            raise MiroFishUnavailable("MiroFish service returned no scenarios")
        for s in out:
            if not isinstance(s, dict) or not _REQUIRED_KEYS.issubset(s):
                raise MiroFishUnavailable(
                    f"MiroFish scenario missing required keys {_REQUIRED_KEYS}; got "
                    f"{sorted(s) if isinstance(s, dict) else type(s).__name__}"
                )
            s["engine"] = "oasis"
        return out

    def _post(self, path: str, payload: dict[str, Any]) -> Any:
        req = urllib.request.Request(
            self._base_url + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                if not (200 <= resp.status < 300):
                    raise MiroFishUnavailable(f"MiroFish service HTTP {resp.status}")
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise MiroFishUnavailable(f"MiroFish service HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise MiroFishUnavailable(f"MiroFish service unreachable: {exc}") from exc
        except (ValueError, json.JSONDecodeError) as exc:
            raise MiroFishUnavailable(f"MiroFish service returned invalid JSON: {exc}") from exc
