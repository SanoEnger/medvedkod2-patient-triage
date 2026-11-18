import hashlib
import json
from functools import lru_cache
from inspect import getsource

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import DataEncryptionError, JsonCipher, rule_context
from app.db.models import SafetyRuleVersionRecord
from app.services import safety
from app.services.sessions import DISCLAIMER, EMERGENCY_MESSAGE, SessionService


def fingerprint(value) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode()
    ).hexdigest()


@lru_cache(maxsize=1)
def runtime_rules() -> tuple[dict, ...]:
    implementation = fingerprint(
        {
            "safety": getsource(safety.find_emergency_rules),
            "text_matching": getsource(safety._match_confirmed),
            "routing": getsource(SessionService._triage),
            "negation": safety._NEGATION_RE.pattern,
            "uncertainty": safety._UNCERTAIN_RE.pattern,
            "disclaimer": DISCLAIMER,
            "emergency_message": EMERGENCY_MESSAGE,
        }
    )
    codes = sorted(
        set(safety._RULE_FIELDS.values())
        | set(safety._PATTERNS)
        | {"RF_CHILD_FEVER_39_5", "DEMO_SKIN_MILD_V0"}
    )
    rules = []
    for code in codes:
        predicates = {
            "review_status": "synthetic_only",
            "implementation_sha256": implementation,
            "implementation": "SessionService._triage"
            if code.startswith("DEMO_")
            else "find_emergency_rules",
            "red_flag_fields": [
                field for field, value in safety._RULE_FIELDS.items() if value == code
            ],
            "confirmed_text_patterns": safety._PATTERNS.get(code, []),
        }
        severity = "P2" if code.startswith("DEMO_") else "P0"
        version = fingerprint(
            {"predicates": predicates, "severity": severity, "enabled": True}
        )
        rules.append(
            {
                "code": code,
                "version": version,
                "severity": severity,
                "enabled": True,
                "predicates": predicates,
            }
        )
    return tuple(rules)


def result_version(codes: list[str]) -> tuple[str, dict[str, str]]:
    versions = {rule["code"]: rule["version"] for rule in runtime_rules()}
    if any(code not in versions for code in codes):
        raise DataEncryptionError("Result refers to an unregistered safety rule")
    return "synthetic-v0-" + fingerprint(versions), {
        code: versions[code] for code in codes
    }


async def verify_runtime_catalog(db: AsyncSession, cipher: JsonCipher) -> None:
    rows = {row.code: row for row in await db.scalars(select(SafetyRuleVersionRecord))}
    expected = {rule["code"]: rule for rule in runtime_rules()}
    if set(expected) - set(rows) or any(
        row.enabled for code, row in rows.items() if code not in expected
    ):
        raise DataEncryptionError(
            "Safety rule catalog does not match the running implementation"
        )
    for code, rule in expected.items():
        row = rows[code]
        if (row.version, row.severity, row.enabled) != (
            rule["version"],
            rule["severity"],
            rule["enabled"],
        ):
            raise DataEncryptionError(
                "Safety rule catalog does not match the running implementation"
            )
        if (
            cipher.decrypt(row.predicates, rule_context(row.code, row.version))
            != rule["predicates"]
        ):
            raise DataEncryptionError("Safety rule catalog authentication failed")
