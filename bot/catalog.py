"""Салон: услуги, мастера и их рабочие часы. Читается из data/salon.json."""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Service:
    id: str
    name: str
    minutes: int
    price: int


@dataclass(frozen=True)
class Master:
    id: str
    name: str
    services: frozenset[str]
    hours: dict[int, tuple[dt.time, dt.time]]

    def works(self, date: dt.date) -> tuple[dt.time, dt.time] | None:
        return self.hours.get(date.isoweekday())


@dataclass(frozen=True)
class Catalog:
    name: str
    address: str
    services: dict[str, Service]
    masters: dict[str, Master]
    slot_step: int = 30
    min_lead: int = 60
    days_ahead: int = 14

    @classmethod
    def from_json(cls, path: str | Path) -> Catalog:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        services = {item["id"]: Service(**item) for item in data["services"]}
        masters = {}
        for item in data["masters"]:
            unknown = set(item["services"]) - services.keys()
            if unknown:
                raise ValueError(f"у мастера {item['name']} неизвестные услуги: {', '.join(sorted(unknown))}")
            masters[item["id"]] = Master(
                item["id"], item["name"], frozenset(item["services"]),
                {int(day): _hours(span) for day, span in item["hours"].items()},
            )
        return cls(data["name"], data.get("address", ""), services, masters,
                   data.get("slot_step_minutes", 30), data.get("min_lead_minutes", 60), data.get("days_ahead", 14))

    def masters_for(self, service_id: str) -> list[Master]:
        return [master for master in self.masters.values() if service_id in master.services]


def _hours(span: str) -> tuple[dt.time, dt.time]:
    start, end = (dt.time.fromisoformat(part.strip()) for part in span.split("-"))
    if end <= start:
        raise ValueError(f"рабочие часы {span}: конец раньше начала")
    return start, end
