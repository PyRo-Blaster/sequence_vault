"""QC rule definitions loaded from the versioned registry (config/qc-rules.v*.json)."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from sequence_vault.domain.spans import BlockSpan


class Severity(StrEnum):
    INFO = "INFO"
    REVIEW = "REVIEW"
    BLOCK = "BLOCK"


@dataclass(frozen=True, slots=True)
class RuleDefinition:
    rule_id: str
    severity: Severity
    allowed_resolutions: frozenset[str]


@dataclass(frozen=True, slots=True)
class Issue:
    rule_id: str
    severity: Severity
    message: str
    evidence: tuple[BlockSpan, ...] = ()


@dataclass(frozen=True, slots=True)
class QcRegistry:
    version: str
    rules: Mapping[str, RuleDefinition]

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "QcRegistry":
        if data.get("generic_block_override_allowed") is not False:
            raise ValueError("The registry must forbid a generic override for BLOCK issues.")
        rules: dict[str, RuleDefinition] = {}
        for item in data["rules"]:
            rule = RuleDefinition(
                rule_id=item["rule_id"],
                severity=Severity(item["severity"]),
                allowed_resolutions=frozenset(item["allowed_resolutions"]),
            )
            if rule.rule_id in rules:
                raise ValueError(f"Duplicate rule {rule.rule_id}")
            if not rule.allowed_resolutions:
                raise ValueError(f"Rule {rule.rule_id} lists no resolutions")
            rules[rule.rule_id] = rule
        return cls(version=str(data["qc_version"]), rules=rules)

    def issue(self, rule_id: str, message: str, evidence: Iterable[BlockSpan] = ()) -> Issue:
        """Create an issue whose severity always comes from the registry."""
        return Issue(rule_id, self.rules[rule_id].severity, message, tuple(evidence))
