"""Validated extraction plus independent lexical evidence preservation."""

import json

from pydantic import ValidationError

from .client import CompletionClient, MockGroqClient
from .exceptions import GroqError
from .fallback import extract_local
from .schemas import ExtractionResult, ModelExtraction


class SymptomExtractor:
    def __init__(self, client: CompletionClient) -> None:
        self.client = client

    async def extract(self, text: str) -> ExtractionResult:
        """Extract data only. Caller must run independent SafetyRules on raw input.

        Empty input returns unknown without a network call. Invalid input raises
        a fixed ValueError. No patient text is logged or retained on this object.
        """
        if not isinstance(text, str) or len(text) > 10000:
            raise ValueError("complaint must be a string of at most 10000 characters")
        mode = "mock" if isinstance(self.client, MockGroqClient) else "live"
        local = extract_local(text)
        reason = "empty_input" if not text.strip() else None
        model = None
        if reason is None:
            try:
                raw = await self.client.complete(text)
                model = ModelExtraction.model_validate(json.loads(raw))
                # Evidence grounding prevents invented text; semantics still require review.
                for item in [*model.symptoms, *model.details]:
                    if item.evidence not in text:
                        raise ValueError("ungrounded")
                for symptom in model.symptoms:
                    if any(value is not None and value not in text for value in (symptom.location, symptom.duration)):
                        raise ValueError("ungrounded")
                    if symptom.code == "dyspnea_rest" and "в покое" not in symptom.evidence.lower():
                        raise ValueError("ungrounded")
            except GroqError as exc:
                reason = exc.code if exc.code in {
                    "missing_configuration", "timeout", "network_error", "rate_limited",
                    "server_error", "http_error", "invalid_response",
                } else "provider_error"
            except (ValidationError, ValueError, TypeError):
                reason = "invalid_response"
        if reason is not None:
            return ExtractionResult(**local.model_dump(), source="fallback", mode=mode, fallback_reason=reason)
        assert model is not None
        merged = list(local.symptoms)
        for symptom in model.symptoms:
            # Never allow an LLM to remove or negate independently found evidence.
            if symptom not in merged:
                merged.append(symptom)
        # Preserve uncertainty from local context, not just the LLM's boolean.
        return ExtractionResult(
            symptoms=merged[:40], details=(local.details + [d for d in model.details if d not in local.details])[:20],
            needs_clarification=model.needs_clarification or local.needs_clarification,
            source="groq", mode=mode,
        )
