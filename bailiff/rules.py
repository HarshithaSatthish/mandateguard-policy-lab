from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RuleCatalog:
    version: str
    effective_date: str
    rules: dict[str, dict[str, Any]]

    @classmethod
    def load(cls, path: str | Path | None = None) -> "RuleCatalog":
        target = Path(path) if path else Path(__file__).with_name("rules.json")
        payload = json.loads(target.read_text())
        return cls(
            version=str(payload["version"]),
            effective_date=str(payload["effective_date"]),
            rules={str(key): dict(value) for key, value in payload["rules"].items()},
        )

    def value(self, rule_id: str) -> Any:
        return self.rules[rule_id]["value"]

    def provenance(self, rule_id: str) -> str:
        rule = self.rules[rule_id]
        return f"{rule['classification']}:{rule['source']}"

    def provenance_map(self) -> dict[str, str]:
        return {rule_id: self.provenance(rule_id) for rule_id in self.rules}

    def sha256(self) -> str:
        from hashlib import sha256

        canonical = json.dumps(
            {"version": self.version, "effective_date": self.effective_date, "rules": self.rules},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return sha256(canonical).hexdigest()
