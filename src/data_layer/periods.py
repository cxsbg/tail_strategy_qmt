from __future__ import annotations

from dataclasses import dataclass

from utils.exceptions import ConfigError


@dataclass(frozen=True)
class PeriodSpec:
    qmt_period: str
    storage_period: str


PERIOD_SPECS = {
    "daily": PeriodSpec(qmt_period="1d", storage_period="daily"),
    "minute": PeriodSpec(qmt_period="1m", storage_period="minute"),
}


def resolve_period(name: str) -> PeriodSpec:
    try:
        return PERIOD_SPECS[name]
    except KeyError as exc:
        valid = ", ".join(sorted(PERIOD_SPECS))
        raise ConfigError(f"Unsupported sync period: {name}. Expected one of: {valid}") from exc
