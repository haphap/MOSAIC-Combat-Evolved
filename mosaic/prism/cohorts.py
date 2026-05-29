"""PRISM 7-cohort definitions (Plan ss9).

Each cohort represents a distinct market regime in the A-share universe.
The date ranges define the training window for that regime's prompt evolution.
"""

from __future__ import annotations

COHORT_CONFIGS: dict[str, dict[str, str]] = {
    "bull_2007": {
        "start": "2006-01-04",
        "end": "2007-10-16",
        "description": "\u725b\u5e02\u9876 6124",
    },
    "crisis_2008": {
        "start": "2007-10-17",
        "end": "2008-10-28",
        "description": "\u66b4\u8dcc 70%, 1664 \u89c1\u5e95",
    },
    "bull_2016": {
        "start": "2016-01-29",
        "end": "2017-12-29",
        "description": "\u6162\u725b + \u767d\u9152",
    },
    "crisis_covid": {
        "start": "2018-10-19",
        "end": "2020-03-23",
        "description": "\u8d38\u6613\u6218 + \u75ab\u60c5\u5408\u5e76",
    },
    "recovery_2020": {
        "start": "2020-03-24",
        "end": "2020-12-31",
        "description": "\u75ab\u540e\u5bbd\u677e\u53cd\u5f39",
    },
    "euphoria_2021": {
        "start": "2020-07-01",
        "end": "2021-02-18",
        "description": "\u8305\u6307\u6570\u9ad8\u5cf0 (\u542f\u52a8 cohort)",
    },
    "rate_tightening": {
        "start": "2022-04-01",
        "end": "2023-12-31",
        "description": "\u4e2d\u7279\u4f30 + \u91cf\u5316\u9000\u6f6e + Fed \u52a0\u606f",
    },
}


def list_cohorts() -> list[dict[str, str]]:
    """Return all cohort configs as a list of {name, start, end, description}."""
    return [
        {"name": name, **config}
        for name, config in COHORT_CONFIGS.items()
    ]


def get_cohort(name: str) -> dict[str, str]:
    """Return a single cohort config or raise ValueError if not found."""
    config = COHORT_CONFIGS.get(name)
    if config is None:
        raise ValueError(
            f"unknown cohort '{name}'; valid cohorts: {list(COHORT_CONFIGS.keys())}"
        )
    return {"name": name, **config}


def get_cohort_prompt_dir(name: str) -> str:
    """Return the prompt directory name for a cohort (e.g. 'cohort_bull_2007')."""
    if name not in COHORT_CONFIGS:
        raise ValueError(
            f"unknown cohort '{name}'; valid cohorts: {list(COHORT_CONFIGS.keys())}"
        )
    return f"cohort_{name}"
