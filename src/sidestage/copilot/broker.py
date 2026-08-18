"""Application-owned validation of untrusted livesell reply intents."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
from hashlib import sha256
import json
import re
import sqlite3
from typing import Annotated, Callable, Iterable, Literal, Optional, Sequence
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator

from sidestage.agent_core import AgentRunResult, RunStatus
from sidestage.copilot.contracts import EvidenceRecord, EvidenceSnapshot
from sidestage.copilot.profile import LivesellIntentError, decode_livesell_intent
from sidestage.copilot.retrieval import EvidenceRetriever, RetrievalStatus
from sidestage.copilot.routing import RoutingDecision
from sidestage.domain.replies import (
    AbstainIntent,
    AbstentionReason,
    AnswerCategory,
    BrokerDecision,
    BrokerOutcome,
    FactType,
    ReplyRoute,
    R3Authorization,
    R3ValidatedFact,
    RenderedTemplateReply,
    ReplyTemplateId,
    RequestReplySendIntent,
    TemplateSelectionIntent,
)
from sidestage.fixtures.loader import SellerCatalog
from sidestage.marketplace.authority import SellerAuthority
from sidestage.storage.database import MarketplaceDatabase
from sidestage.streaming.hub import SseHub, StreamEventStore


_FACT_CATEGORY = {
    FactType.LISTING_IDENTITY: AnswerCategory.PRODUCT_RESEARCH,
    FactType.CURRENT_PRICE: AnswerCategory.PRICE,
    FactType.VARIANT_AVAILABILITY: AnswerCategory.AVAILABILITY,
    FactType.SHIPPING_POLICY: AnswerCategory.SHIPPING,
    FactType.PAYMENT_POLICY: AnswerCategory.PAYMENT,
    FactType.RETURNS_POLICY: AnswerCategory.RETURNS,
    FactType.CONDITION: AnswerCategory.CONDITION,
    FactType.AUTHENTICITY: AnswerCategory.AUTHENTICITY,
    FactType.SIZING: AnswerCategory.SIZING,
    FactType.RELEASE_DATE: AnswerCategory.PRODUCT_RESEARCH,
    FactType.MSRP: AnswerCategory.PRODUCT_RESEARCH,
    FactType.MATERIALS: AnswerCategory.PRODUCT_RESEARCH,
}
_NO_RESPONSE_ABSTENTIONS = {
    AbstentionReason.NO_RESPONSE_NEEDED,
    AbstentionReason.PROMPT_INJECTION,
}
_R3_POLICY_QUESTIONS = {
    AnswerCategory.SHIPPING: frozenset(
        {
            "what is your shipping policy",
            "whats your shipping policy",
            "how does shipping work",
            "when do you ship",
            "how fast do you ship",
        }
    ),
    AnswerCategory.PAYMENT: frozenset(
        {
            "what is your payment policy",
            "whats your payment policy",
            "how does payment work",
            "when is payment captured",
        }
    ),
    AnswerCategory.RETURNS: frozenset(
        {
            "what is your return policy",
            "whats your return policy",
            "what is your returns policy",
            "can i return this",
            "are returns allowed",
        }
    ),
}


class ReplyEffectBroker:
    """Recompute support and freshness; never trust model authorization labels."""

    def __init__(self, database: MarketplaceDatabase, catalog: SellerCatalog) -> None:
        self.database = database
        self.catalog = catalog
        self.retriever = EvidenceRetriever(database, catalog)

    def evaluate(
        self,
        agent_result: AgentRunResult,
        routing: RoutingDecision,
        snapshot: EvidenceSnapshot,
    ) -> BrokerDecision:
        if agent_result.status is not RunStatus.SUCCEEDED:
            reason = (
                agent_result.failure.code.value
                if agent_result.failure is not None
                else "agent_failure"
            )
            return self._needs_seller(reason)
        try:
            intent = decode_livesell_intent(agent_result)
        except LivesellIntentError:
            return self._needs_seller("malformed_intent")

        return self.evaluate_intent(intent, routing, snapshot)

    def evaluate_template(
        self,
        selection: TemplateSelectionIntent,
        rendered: Optional[RenderedTemplateReply],
        routing: RoutingDecision,
        snapshot: EvidenceSnapshot,
    ) -> BrokerDecision:
        """Evaluate a locally rendered template or a closed safe terminal."""

        if selection.template_id is ReplyTemplateId.NO_RESPONSE:
            return BrokerDecision(
                outcome=BrokerOutcome.NO_RESPONSE,
                reason_code=selection.reason_code.value,
            )
        if selection.template_id is ReplyTemplateId.NEEDS_SELLER:
            return BrokerDecision(
                outcome=BrokerOutcome.NEEDS_SELLER,
                reason_code=selection.reason_code.value,
            )
        if rendered is None:
            return self._needs_seller("template_render_failed")
        decision = self.evaluate_intent(
            rendered.intent,
            routing,
            snapshot,
            template_id=rendered.template_id,
        )
        return decision.model_copy(
            update={
                "template_id": rendered.template_id,
                "template_version": rendered.template_version,
            }
        )

    def evaluate_intent(
        self,
        intent: RequestReplySendIntent | AbstainIntent,
        routing: RoutingDecision,
        snapshot: EvidenceSnapshot,
        *,
        template_id: Optional[ReplyTemplateId] = None,
    ) -> BrokerDecision:
        """Evaluate prevalidated intent data without requiring a synthetic agent result."""

        if isinstance(intent, AbstainIntent):
            outcome = (
                BrokerOutcome.NO_RESPONSE
                if intent.reason_code in _NO_RESPONSE_ABSTENTIONS
                else BrokerOutcome.NEEDS_SELLER
            )
            return BrokerDecision(
                outcome=outcome,
                reason_code=intent.reason_code.value,
            )

        if routing.route is ReplyRoute.ADVERSARIAL:
            return self._needs_seller("prompt_injection")
        if not self._trusted_scope_matches(routing, snapshot):
            return self._needs_seller("scope_or_binding_mismatch")

        freshness = self.retriever.revalidate(snapshot)
        if freshness.status is RetrievalStatus.FAILED:
            return self._needs_seller("stale_evidence")

        evidence_by_id = {record.evidence_id: record for record in snapshot.records}
        referenced_ids = tuple(
            dict.fromkeys(
                evidence_id
                for claim in intent.claims
                for evidence_id in claim.evidence_ids
            )
        )
        if any(evidence_id not in evidence_by_id for evidence_id in referenced_ids):
            return self._needs_seller("fabricated_evidence")

        seller = self.catalog.seller(snapshot.seller_id)
        reply_lower = intent.reply_text.casefold()
        if len(intent.reply_text) > seller.tone.max_reply_chars or any(
            phrase.casefold() in reply_lower for phrase in seller.tone.prohibited_phrases
        ):
            return self._needs_seller("tone_guardrail")

        referenced_records: list[EvidenceRecord] = []
        for claim in intent.claims:
            claim_records = [evidence_by_id[evidence_id] for evidence_id in claim.evidence_ids]
            if not self._claim_supported(claim.reply_span, claim_records):
                return self._needs_seller("unsupported_claim")
            referenced_records.extend(claim_records)

        if not self._all_reply_text_is_claimed(intent, template_id=template_id):
            return self._needs_seller("unsupported_reply_text")

        category = self._recompute_category(referenced_records)
        if category is AnswerCategory.OTHER:
            return self._needs_seller("unsupported_claim_category")
        r3 = self._r3_decision(
            routing,
            snapshot,
            category,
            referenced_records,
            seller.tone.voice,
            seller.tone.max_reply_chars,
            seller.tone.prohibited_phrases,
        )
        if r3 is not None:
            return r3
        return BrokerDecision(
            outcome=BrokerOutcome.REVIEW,
            reason_code="supported_for_review",
            reply_text=intent.reply_text,
            evidence_ids=referenced_ids,
            validated_category=category,
        )

    def _r3_decision(
        self,
        routing: RoutingDecision,
        snapshot: EvidenceSnapshot,
        category: AnswerCategory,
        records: Sequence[EvidenceRecord],
        voice: str,
        max_reply_chars: int,
        prohibited_phrases: Sequence[str],
    ) -> Optional[BrokerDecision]:
        with self.database.read() as connection:
            capability = connection.execute(
                """SELECT enabled, version FROM copilot_r3_capabilities
                   WHERE seller_id = ? AND show_id = ?""",
                (snapshot.seller_id, snapshot.show_id),
            ).fetchone()
        if capability is None or not bool(capability["enabled"]):
            return None
        factual = tuple(
            {
                record.evidence_id: record
                for record in records
                if record.fact_type in _FACT_CATEGORY
            }.values()
        )
        if len(factual) != 1:
            return None
        record = factual[0]
        if not _r3_question_matches(routing.normalized_text, category, record):
            return None
        rendered = _render_r3_reply(category, record, voice)
        if rendered is None or len(rendered) > max_reply_chars:
            return None
        if any(phrase.casefold() in rendered.casefold() for phrase in prohibited_phrases):
            return None
        authorization = R3Authorization(
            capability_version=int(capability["version"]),
            seller_id=snapshot.seller_id,
            show_id=snapshot.show_id,
            listing_id=snapshot.listing_id,
            sku=routing.bound_listing.sku,
            epoch_id=snapshot.epoch_id,
            answer_category=category,
            fact=R3ValidatedFact(
                evidence_id=record.evidence_id,
                fact_type=record.fact_type,
                value=record.value,
                source_ref=record.source_ref,
                source_version=record.source_version,
            ),
        )
        return BrokerDecision(
            outcome=BrokerOutcome.AUTO_SEND,
            reason_code="r3_authorized",
            reply_text=rendered,
            evidence_ids=(record.evidence_id,),
            validated_category=category,
            r3_authorization=authorization,
        )

    def _trusted_scope_matches(
        self,
        routing: RoutingDecision,
        snapshot: EvidenceSnapshot,
    ) -> bool:
        bound = routing.bound_listing
        if bound is None:
            return False
        if bound.listing_id != snapshot.listing_id or bound.epoch_id != snapshot.epoch_id:
            return False
        if any(
            record.seller_id != snapshot.seller_id
            or record.listing_id != snapshot.listing_id
            for record in snapshot.records
        ):
            return False
        with self.database.read() as connection:
            row = connection.execute(
                """SELECT s.seller_id FROM shows s
                   JOIN listings l ON l.seller_id = s.seller_id
                   WHERE s.show_id = ? AND s.seller_id = ? AND l.listing_id = ?""",
                (snapshot.show_id, snapshot.seller_id, snapshot.listing_id),
            ).fetchone()
        return row is not None

    @staticmethod
    def _claim_supported(span: str, records: Sequence[EvidenceRecord]) -> bool:
        factual = [record for record in records if record.fact_type in _FACT_CATEGORY]
        if not factual:
            return False
        return any(_record_supports_span(span, record) for record in factual)

    @staticmethod
    def _all_reply_text_is_claimed(
        intent: RequestReplySendIntent,
        *,
        template_id: Optional[ReplyTemplateId] = None,
    ) -> bool:
        remaining = intent.reply_text
        for claim in intent.claims:
            remaining = remaining.replace(claim.reply_span, "", 1)
        normalized = re.sub(r"[\W_]+", " ", remaining, flags=re.UNICODE).strip().casefold()
        allowed_static_text = {"", "yes", "no", "currently", "right now"}
        template_static_text = {
            ReplyTemplateId.CURRENT_PRICE: "current price",
            ReplyTemplateId.EXACT_VARIANT_AVAILABILITY: "availability",
            ReplyTemplateId.SHIPPING_POLICY: "shipping",
            ReplyTemplateId.PAYMENT_POLICY: "payment",
            ReplyTemplateId.RETURNS_POLICY: "returns",
            ReplyTemplateId.AVAILABILITY_SUMMARY: "available variants",
            ReplyTemplateId.RELEASE_DATE: "release date",
            ReplyTemplateId.MSRP: "msrp",
            ReplyTemplateId.MATERIALS: "materials",
            ReplyTemplateId.SIZING_GUIDANCE: "sizing",
            ReplyTemplateId.AUTHENTICITY: "authenticity",
            ReplyTemplateId.CONDITION: "condition",
        }.get(template_id)
        if template_static_text is not None:
            allowed_static_text.add(template_static_text)
        return normalized in allowed_static_text

    @staticmethod
    def _recompute_category(records: Iterable[EvidenceRecord]) -> AnswerCategory:
        categories = {
            _FACT_CATEGORY[record.fact_type]
            for record in records
            if record.fact_type in _FACT_CATEGORY
        }
        if len(categories) == 1:
            return next(iter(categories))
        if categories and categories <= {AnswerCategory.PRODUCT_RESEARCH}:
            return AnswerCategory.PRODUCT_RESEARCH
        return AnswerCategory.OTHER

    @staticmethod
    def _needs_seller(reason_code: str) -> BrokerDecision:
        return BrokerDecision(
            outcome=BrokerOutcome.NEEDS_SELLER,
            reason_code=reason_code,
        )


def _record_supports_span(span: str, record: EvidenceRecord) -> bool:
    if record.fact_type is FactType.CURRENT_PRICE:
        return _price_supported(span, record.value)
    if record.fact_type is FactType.VARIANT_AVAILABILITY:
        label, _, quantity_text = record.value.partition(":")
        quantity_match = re.search(r"\d+", quantity_text)
        quantity = quantity_match.group(0) if quantity_match else None
        normalized_span = span.casefold()
        label_tokens = [token for token in re.findall(r"[a-z0-9.]+", label.casefold()) if token]
        meaningful_label = label_tokens[-1:] if label_tokens else []
        label_supported = all(token in normalized_span for token in meaningful_label)
        availability_supported = (
            (quantity is not None and quantity in normalized_span)
            or "available" in normalized_span
            or (quantity == "0" and "sold out" in normalized_span)
        )
        return label_supported and availability_supported
    value_tokens = set(re.findall(r"[a-z0-9]+", record.value.casefold()))
    span_tokens = set(re.findall(r"[a-z0-9]+", span.casefold()))
    if not span_tokens:
        return False
    overlap = len(value_tokens & span_tokens)
    return overlap >= min(3, len(span_tokens)) and overlap / len(span_tokens) >= 0.6


def _price_supported(span: str, value: str) -> bool:
    try:
        evidence_number = Decimal(re.search(r"\d+(?:\.\d+)?", value).group(0))
    except (AttributeError, InvalidOperation):
        return False
    for raw_number in re.findall(r"\d+(?:\.\d+)?", span):
        try:
            if Decimal(raw_number) == evidence_number:
                return True
        except InvalidOperation:
            continue
    return False


def _r3_question_matches(
    normalized_text: str,
    category: AnswerCategory,
    record: EvidenceRecord,
) -> bool:
    normalized = " ".join(normalized_text.casefold().split())
    if category is AnswerCategory.PRICE:
        if any(term in normalized for term in ("offer", "discount", "markdown", "cheaper")):
            return False
        return any(term in normalized for term in ("how much", "price", "cost"))
    if category is AnswerCategory.AVAILABILITY:
        label = record.value.partition(":")[0].casefold()
        label_tokens = re.findall(r"[a-z0-9]+", label)
        return all(token in normalized for token in label_tokens) and any(
            term in normalized
            for term in ("available", "have", "in stock", "left", "sold out")
        )
    allowed = _R3_POLICY_QUESTIONS.get(category)
    return allowed is not None and normalized in allowed


def _render_r3_reply(
    category: AnswerCategory,
    record: EvidenceRecord,
    voice: str,
) -> Optional[str]:
    if category is AnswerCategory.PRICE:
        match = re.search(r"(\d+)(?:\.(\d{2}))?", record.value)
        if match is None:
            return None
        cents = match.group(2) or "00"
        amount = f"${match.group(1)}" if cents == "00" else f"${match.group(1)}.{cents}"
        return {
            "energetic_concise": f"It's {amount} right now.",
            "precise_reserved": f"The current price is {amount}.",
            "fast_direct": f"Current price: {amount}.",
        }.get(voice)
    if category is AnswerCategory.AVAILABILITY:
        label, separator, quantity_text = record.value.partition(":")
        quantity = re.search(r"\d+", quantity_text)
        if not separator or quantity is None:
            return None
        count = int(quantity.group(0))
        if count == 0:
            return f"{label} is sold out."
        return {
            "energetic_concise": f"Yes — {label} is available ({count} left).",
            "precise_reserved": f"{label} is available; {count} remain.",
            "fast_direct": f"{label}: {count} available.",
        }.get(voice)
    if category in {
        AnswerCategory.SHIPPING,
        AnswerCategory.PAYMENT,
        AnswerCategory.RETURNS,
    }:
        return record.value
    return None


class ReplyPersistenceError(RuntimeError):
    """The local reply/receipt/state transaction could not commit."""


class SellerReplyDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    action: Literal["accept", "reply", "dismiss"]
    reply_text: Optional[
        Annotated[str, StringConstraints(strict=True, min_length=1, max_length=500)]
    ] = None

    @model_validator(mode="after")
    def text_matches_action(self) -> "SellerReplyDecisionRequest":
        if self.action == "reply" and self.reply_text is None:
            raise ValueError("reply action requires exact seller text")
        if self.action != "reply" and self.reply_text is not None:
            raise ValueError("only reply action accepts seller text")
        return self


class R2ResultHandler:
    """Persist safe review/needs-seller results and publish their SSE records."""

    def __init__(
        self,
        database: MarketplaceDatabase,
        catalog: SellerCatalog,
        stream_store: StreamEventStore,
        hub: SseHub,
        *,
        wall_clock: Callable[[], datetime],
        id_factory: Callable[[], str] = lambda: f"sug_{uuid4().hex}",
        reply_id_factory: Callable[[str], str] = lambda prefix: f"{prefix}_{uuid4().hex}",
        before_auto_send: Optional[Callable[[], None]] = None,
        before_receipt_insert: Optional[Callable[[], None]] = None,
    ) -> None:
        self.database = database
        self.catalog = catalog
        self.stream_store = stream_store
        self.hub = hub
        self.wall_clock = wall_clock
        self.id_factory = id_factory
        self.reply_id_factory = reply_id_factory
        self.before_auto_send = before_auto_send
        self.before_receipt_insert = before_receipt_insert

    async def handle(self, event, routing, snapshot, decision: BrokerDecision) -> dict:
        if decision.outcome is BrokerOutcome.AUTO_SEND:
            return await self._handle_auto_send(event, routing, snapshot, decision)
        changed_at = _utc_text(self.wall_clock())
        with self.database.transaction() as connection:
            if decision.outcome is BrokerOutcome.REVIEW:
                connection.execute(
                    """INSERT OR REPLACE INTO copilot_suggestions(
                           suggestion_id, question_id, seller_id, show_id, listing_id,
                           epoch_id, snapshot_id, reply_text, answer_category,
                           evidence_ids_json, evidence_snapshot_json, created_at
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        self.id_factory(),
                        routing.question_id,
                        event.seller_id,
                        event.show_id,
                        snapshot.listing_id,
                        snapshot.epoch_id,
                        snapshot.snapshot_id,
                        decision.reply_text,
                        decision.validated_category.value,
                        json.dumps(decision.evidence_ids, separators=(",", ":")),
                        json.dumps(
                            snapshot.model_dump(mode="json"),
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        changed_at,
                    ),
                )
                _advance_question(
                    connection,
                    routing.question_id,
                    target="awaiting_review",
                    reason_code=decision.reason_code,
                    changed_at=changed_at,
                )
                state = "awaiting_review"
            elif decision.outcome is BrokerOutcome.NEEDS_SELLER:
                _advance_question(
                    connection,
                    routing.question_id,
                    target="needs_seller",
                    reason_code=decision.reason_code,
                    changed_at=changed_at,
                )
                state = "needs_seller"
            else:
                _advance_question(
                    connection,
                    routing.question_id,
                    target="unanswered",
                    reason_code=decision.reason_code,
                    changed_at=changed_at,
                )
                state = "unanswered"
            payload = {
                "question_id": routing.question_id,
                "state": state,
                "reason_code": decision.reason_code,
            }
            self.stream_store.append(
                seller_id=event.seller_id,
                show_id=event.show_id,
                event_type="copilot.question.changed",
                payload=payload,
                connection=connection,
                created_at=changed_at,
            )
        await self.hub.notify(event.show_id)
        return payload

    async def _handle_auto_send(
        self,
        event,
        routing,
        snapshot: EvidenceSnapshot,
        decision: BrokerDecision,
    ) -> dict:
        authorization = decision.r3_authorization
        if authorization is None:
            raise ValueError("R3 auto-send requires authorization")
        if self.before_auto_send is not None:
            self.before_auto_send()
        changed_at = _utc_text(self.wall_clock())
        with self.database.transaction() as connection:
            question = connection.execute(
                """SELECT * FROM copilot_questions
                   WHERE question_id = ? AND seller_id = ? AND show_id = ?""",
                (routing.question_id, event.seller_id, event.show_id),
            ).fetchone()
            if question is None:
                raise KeyError("R3 question is outside the trusted scope")
            canonical_question_id = question["canonical_question_id"] or routing.question_id
            existing = connection.execute(
                """SELECT reply_id FROM copilot_outbound_replies
                   WHERE canonical_question_id = ?""",
                (canonical_question_id,),
            ).fetchone()
            if existing is not None:
                return {
                    "question_id": routing.question_id,
                    "state": question["state"],
                    "reason_code": "canonical_reply_already_exists",
                    "reply_id": existing["reply_id"],
                    "idempotent_replay": True,
                }

            final_reason, validated_versions = self._validate_r3_final(
                connection,
                event,
                authorization,
            )
            if final_reason is not None:
                if final_reason == "previous_listing":
                    target = "needs_seller"
                else:
                    target = "awaiting_review"
                    connection.execute(
                        """INSERT INTO copilot_suggestions(
                               suggestion_id, question_id, seller_id, show_id, listing_id,
                               epoch_id, snapshot_id, reply_text, answer_category,
                               evidence_ids_json, evidence_snapshot_json, created_at
                           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                           ON CONFLICT(question_id) DO UPDATE SET
                               snapshot_id = excluded.snapshot_id,
                               reply_text = excluded.reply_text,
                               answer_category = excluded.answer_category,
                               evidence_ids_json = excluded.evidence_ids_json,
                               evidence_snapshot_json = excluded.evidence_snapshot_json,
                               created_at = excluded.created_at""",
                        (
                            self.id_factory(),
                            routing.question_id,
                            event.seller_id,
                            event.show_id,
                            snapshot.listing_id,
                            snapshot.epoch_id,
                            snapshot.snapshot_id,
                            decision.reply_text,
                            decision.validated_category.value,
                            json.dumps(decision.evidence_ids, separators=(",", ":")),
                            json.dumps(
                                snapshot.model_dump(mode="json"),
                                sort_keys=True,
                                separators=(",", ":"),
                            ),
                            changed_at,
                        ),
                    )
                _advance_question(
                    connection,
                    routing.question_id,
                    target=target,
                    reason_code=final_reason,
                    changed_at=changed_at,
                )
                payload = {
                    "question_id": routing.question_id,
                    "state": target,
                    "reason_code": final_reason,
                }
                self.stream_store.append(
                    seller_id=event.seller_id,
                    show_id=event.show_id,
                    event_type="copilot.question.changed",
                    payload=payload,
                    connection=connection,
                    created_at=changed_at,
                )
            else:
                reply_id = self.reply_id_factory("rpl")
                receipt_id = self.reply_id_factory("rrc")
                connection.execute(
                    """INSERT INTO copilot_outbound_replies(
                           reply_id, question_id, canonical_question_id, seller_id,
                           show_id, actor_id, actor_type, mode, reply_text, created_at
                       ) VALUES (?, ?, ?, ?, ?, 'sidestage_r3', 'automation', 'r3', ?, ?)""",
                    (
                        reply_id,
                        routing.question_id,
                        canonical_question_id,
                        event.seller_id,
                        event.show_id,
                        decision.reply_text,
                        changed_at,
                    ),
                )
                if self.before_receipt_insert is not None:
                    self.before_receipt_insert()
                connection.execute(
                    """INSERT INTO copilot_reply_receipts(
                           receipt_id, reply_id, question_id, canonical_question_id,
                           seller_id, show_id, actor_id, mode, reply_text,
                           evidence_ids_json, broker_outcome, guardrail_verdict,
                           authorization_version, validated_versions_json,
                           warnings_json, created_at
                       ) VALUES (?, ?, ?, ?, ?, ?, 'sidestage_r3', 'r3', ?, ?,
                                 'auto_send', 'r3_final_revalidated', ?, ?, '[]', ?)""",
                    (
                        receipt_id,
                        reply_id,
                        routing.question_id,
                        canonical_question_id,
                        event.seller_id,
                        event.show_id,
                        decision.reply_text,
                        json.dumps(decision.evidence_ids, separators=(",", ":")),
                        authorization.capability_version,
                        json.dumps(validated_versions, sort_keys=True, separators=(",", ":")),
                        changed_at,
                    ),
                )
                _advance_question(
                    connection,
                    routing.question_id,
                    target="auto_answered",
                    reason_code="r3_sent",
                    changed_at=changed_at,
                )
                self.stream_store.append(
                    seller_id=event.seller_id,
                    show_id=event.show_id,
                    event_type="chat.reply",
                    payload={
                        "reply_id": reply_id,
                        "question_id": routing.question_id,
                        "reply_text": decision.reply_text,
                    },
                    connection=connection,
                    created_at=changed_at,
                )
                payload = {
                    "question_id": routing.question_id,
                    "state": "auto_answered",
                    "reason_code": "r3_sent",
                    "reply_id": reply_id,
                    "receipt_id": receipt_id,
                }
                self.stream_store.append(
                    seller_id=event.seller_id,
                    show_id=event.show_id,
                    event_type="copilot.question.changed",
                    payload=payload,
                    connection=connection,
                    created_at=changed_at,
                )
        await self.hub.notify(event.show_id)
        return payload

    def _validate_r3_final(self, connection, event, authorization):
        if (
            authorization.seller_id != event.seller_id
            or authorization.show_id != event.show_id
        ):
            return "scope_or_binding_mismatch", {}
        epoch = connection.execute(
            """SELECT epoch_id, listing_id FROM listing_epochs
               WHERE seller_id = ? AND show_id = ? AND end_seq IS NULL""",
            (event.seller_id, event.show_id),
        ).fetchone()
        if (
            epoch is None
            or epoch["epoch_id"] != authorization.epoch_id
            or epoch["listing_id"] != authorization.listing_id
        ):
            return "previous_listing", {}
        capability = connection.execute(
            """SELECT enabled, version FROM copilot_r3_capabilities
               WHERE seller_id = ? AND show_id = ?""",
            (event.seller_id, event.show_id),
        ).fetchone()
        if (
            capability is None
            or not bool(capability["enabled"])
            or int(capability["version"]) != authorization.capability_version
        ):
            return "r3_authorization_changed", {}
        product = next(
            (
                item
                for item in self.catalog.seller(event.seller_id).products
                if item.listing.listing_id == authorization.listing_id
            ),
            None,
        )
        if product is None or product.sku != authorization.sku:
            return "scope_or_binding_mismatch", {}
        fact = authorization.fact
        validated_versions = {
            "r3_capability": authorization.capability_version,
            "epoch_id": authorization.epoch_id,
            "listing_id": authorization.listing_id,
            "fact_type": fact.fact_type.value,
            "fact_source_version": fact.source_version,
        }
        if fact.fact_type is FactType.CURRENT_PRICE:
            listing = connection.execute(
                """SELECT price_cents, version FROM listings
                   WHERE seller_id = ? AND listing_id = ?""",
                (event.seller_id, authorization.listing_id),
            ).fetchone()
            expected_value = (
                None
                if listing is None
                else f"USD {int(listing['price_cents']) / 100:.2f}"
            )
            if (
                listing is None
                or int(listing["version"]) != fact.source_version
                or expected_value != fact.value
            ):
                return "r3_fact_version_changed", {}
            validated_versions["listing_version"] = int(listing["version"])
        elif fact.fact_type is FactType.VARIANT_AVAILABILITY:
            variant_id = fact.source_ref.rsplit("/", 1)[-1]
            variant = connection.execute(
                """SELECT available_quantity, version FROM inventory
                   WHERE seller_id = ? AND listing_id = ? AND variant_id = ?""",
                (event.seller_id, authorization.listing_id, variant_id),
            ).fetchone()
            fixture_variant = next(
                (item for item in product.variants if item.variant_id == variant_id),
                None,
            )
            expected_value = (
                None
                if variant is None or fixture_variant is None
                else f"{fixture_variant.label}: {int(variant['available_quantity'])} available"
            )
            if (
                variant is None
                or int(variant["version"]) != fact.source_version
                or expected_value != fact.value
            ):
                return "r3_fact_version_changed", {}
            validated_versions["variant_id"] = variant_id
            validated_versions["inventory_version"] = int(variant["version"])
        else:
            policy = connection.execute(
                """SELECT value, source_version FROM copilot_evidence_records
                   WHERE evidence_id = ? AND seller_id = ? AND listing_id = ?
                     AND fact_type = ?""",
                (
                    fact.evidence_id,
                    event.seller_id,
                    authorization.listing_id,
                    fact.fact_type.value,
                ),
            ).fetchone()
            if (
                policy is None
                or int(policy["source_version"]) != fact.source_version
                or policy["value"] != fact.value
            ):
                return "r3_fact_version_changed", {}
            validated_versions["policy_version"] = int(policy["source_version"])
        return None, validated_versions

    async def handle_failure(self, event, routing, reason_code: str) -> dict:
        return await self._handle_without_draft(
            event,
            routing,
            state="needs_seller",
            reason_code=reason_code,
        )

    async def handle_no_response(self, event, routing, reason_code: str) -> dict:
        return await self._handle_without_draft(
            event,
            routing,
            state="unanswered",
            reason_code=reason_code,
        )

    async def _handle_without_draft(
        self,
        event,
        routing,
        *,
        state: Literal["needs_seller", "unanswered"],
        reason_code: str,
    ) -> dict:
        changed_at = _utc_text(self.wall_clock())
        with self.database.transaction() as connection:
            _advance_question(
                connection,
                routing.question_id,
                target=state,
                reason_code=reason_code,
                changed_at=changed_at,
            )
            payload = {
                "question_id": routing.question_id,
                "state": state,
                "reason_code": reason_code,
            }
            self.stream_store.append(
                seller_id=event.seller_id,
                show_id=event.show_id,
                event_type="copilot.question.changed",
                payload=payload,
                connection=connection,
                created_at=changed_at,
            )
        await self.hub.notify(event.show_id)
        return payload


class SellerReplyService:
    """Authenticated R2 decision boundary with one local atomic reply transaction."""

    def __init__(
        self,
        database: MarketplaceDatabase,
        catalog: SellerCatalog,
        stream_store: StreamEventStore,
        hub: SseHub,
        *,
        wall_clock: Callable[[], datetime],
        before_receipt_insert: Optional[Callable[[], None]] = None,
        id_factory: Callable[[str], str] = lambda prefix: f"{prefix}_{uuid4().hex}",
    ) -> None:
        self.database = database
        self.catalog = catalog
        self.stream_store = stream_store
        self.hub = hub
        self.wall_clock = wall_clock
        self.before_receipt_insert = before_receipt_insert
        self.id_factory = id_factory
        self.retriever = EvidenceRetriever(database, catalog)

    async def decide(
        self,
        authority: SellerAuthority,
        question_id: str,
        request: SellerReplyDecisionRequest,
        *,
        idempotency_key: str,
    ) -> dict:
        fingerprint = sha256(
            json.dumps(
                request.model_dump(mode="json"),
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        changed_at = _utc_text(self.wall_clock())
        try:
            with self.database.transaction() as connection:
                replay = connection.execute(
                    """SELECT request_fingerprint, receipt_id
                       FROM copilot_reply_idempotency
                       WHERE seller_id = ? AND show_id = ? AND idempotency_key = ?""",
                    (authority.seller_id, authority.show_id, idempotency_key),
                ).fetchone()
                if replay is not None:
                    if replay["request_fingerprint"] != fingerprint:
                        raise ValueError("idempotency key was reused with another decision")
                    result = self._sent_result(
                        connection,
                        replay["receipt_id"],
                        idempotent_replay=True,
                    )
                    result["notify"] = False
                    return result

                question = connection.execute(
                    """SELECT * FROM copilot_questions
                       WHERE question_id = ? AND seller_id = ? AND show_id = ?""",
                    (question_id, authority.seller_id, authority.show_id),
                ).fetchone()
                if question is None:
                    raise KeyError("question is not in the authenticated seller scope")

                if request.action == "dismiss":
                    _advance_question(
                        connection,
                        question_id,
                        target="unanswered",
                        reason_code="seller_dismissed",
                        changed_at=changed_at,
                    )
                    self.stream_store.append(
                        seller_id=authority.seller_id,
                        show_id=authority.show_id,
                        event_type="copilot.question.changed",
                        payload={"question_id": question_id, "state": "unanswered"},
                        connection=connection,
                        created_at=changed_at,
                    )
                    result = {
                        "status": "dismissed",
                        "question_id": question_id,
                        "idempotent_replay": False,
                        "notify": True,
                    }
                else:
                    suggestion = connection.execute(
                        "SELECT * FROM copilot_suggestions WHERE question_id = ?",
                        (question_id,),
                    ).fetchone()
                    if request.action == "accept":
                        if suggestion is None:
                            raise ValueError("question has no AI suggestion to accept")
                        snapshot = EvidenceSnapshot.model_validate_json(
                            suggestion["evidence_snapshot_json"]
                        )
                        if self.retriever.revalidate(snapshot).status is RetrievalStatus.FAILED:
                            return {
                                "status": "stale",
                                "question_id": question_id,
                                "reason_code": "stale_evidence",
                                "idempotent_replay": False,
                                "notify": False,
                            }
                        reply_text = suggestion["reply_text"]
                        evidence_ids = tuple(json.loads(suggestion["evidence_ids_json"]))
                        warnings: tuple[str, ...] = ()
                        guardrail_verdict = "supported_revalidated"
                    else:
                        reply_text = request.reply_text
                        evidence_ids = ()
                        warnings = self._seller_warnings(connection, authority, reply_text)
                        guardrail_verdict = "seller_override_warning_only"

                    canonical_question_id = question["canonical_question_id"] or question_id
                    existing = connection.execute(
                        """SELECT r.receipt_id FROM copilot_outbound_replies o
                           JOIN copilot_reply_receipts r ON r.reply_id = o.reply_id
                           WHERE o.canonical_question_id = ?""",
                        (canonical_question_id,),
                    ).fetchone()
                    if existing is not None:
                        result = self._sent_result(
                            connection,
                            existing["receipt_id"],
                            idempotent_replay=True,
                        )
                        result["notify"] = False
                        return result

                    reply_id = self.id_factory("rpl")
                    receipt_id = self.id_factory("rrc")
                    connection.execute(
                        """INSERT INTO copilot_outbound_replies(
                               reply_id, question_id, canonical_question_id, seller_id,
                               show_id, actor_id, actor_type, mode, reply_text, created_at
                           ) VALUES (?, ?, ?, ?, ?, ?, 'seller', 'r2', ?, ?)""",
                        (
                            reply_id,
                            question_id,
                            canonical_question_id,
                            authority.seller_id,
                            authority.show_id,
                            authority.actor_id,
                            reply_text,
                            changed_at,
                        ),
                    )
                    if self.before_receipt_insert is not None:
                        self.before_receipt_insert()
                    connection.execute(
                        """INSERT INTO copilot_reply_receipts(
                               receipt_id, reply_id, question_id, canonical_question_id,
                               seller_id, show_id, actor_id, mode, reply_text,
                               evidence_ids_json, broker_outcome, guardrail_verdict,
                               warnings_json, created_at
                           ) VALUES (?, ?, ?, ?, ?, ?, ?, 'r2', ?, ?, 'review', ?, ?, ?)""",
                        (
                            receipt_id,
                            reply_id,
                            question_id,
                            canonical_question_id,
                            authority.seller_id,
                            authority.show_id,
                            authority.actor_id,
                            reply_text,
                            json.dumps(evidence_ids, separators=(",", ":")),
                            guardrail_verdict,
                            json.dumps(warnings, separators=(",", ":")),
                            changed_at,
                        ),
                    )
                    _advance_question(
                        connection,
                        question_id,
                        target="answered_by_seller",
                        reason_code="seller_replied",
                        changed_at=changed_at,
                    )
                    connection.execute(
                        """INSERT INTO copilot_reply_idempotency(
                               seller_id, show_id, idempotency_key,
                               request_fingerprint, receipt_id
                           ) VALUES (?, ?, ?, ?, ?)""",
                        (
                            authority.seller_id,
                            authority.show_id,
                            idempotency_key,
                            fingerprint,
                            receipt_id,
                        ),
                    )
                    self.stream_store.append(
                        seller_id=authority.seller_id,
                        show_id=authority.show_id,
                        event_type="chat.reply",
                        payload={
                            "reply_id": reply_id,
                            "question_id": question_id,
                            "reply_text": reply_text,
                        },
                        connection=connection,
                        created_at=changed_at,
                    )
                    self.stream_store.append(
                        seller_id=authority.seller_id,
                        show_id=authority.show_id,
                        event_type="copilot.question.changed",
                        payload={
                            "question_id": question_id,
                            "state": "answered_by_seller",
                        },
                        connection=connection,
                        created_at=changed_at,
                    )
                    result = self._sent_result(
                        connection,
                        receipt_id,
                        idempotent_replay=False,
                    )
                    result["notify"] = True
        except (KeyError, ValueError):
            raise
        except Exception as error:
            raise ReplyPersistenceError("reply transaction failed") from error

        notify = result.pop("notify", False)
        if notify:
            await self.hub.notify(authority.show_id)
        return result

    def _seller_warnings(
        self,
        connection: sqlite3.Connection,
        authority: SellerAuthority,
        reply_text: str,
    ) -> tuple[str, ...]:
        warnings: list[str] = []
        seller = self.catalog.seller(authority.seller_id)
        if any(phrase.casefold() in reply_text.casefold() for phrase in seller.tone.prohibited_phrases):
            warnings.append("tone_conflict")
        show = connection.execute(
            "SELECT active_listing_id FROM shows WHERE show_id = ? AND seller_id = ?",
            (authority.show_id, authority.seller_id),
        ).fetchone()
        if show is not None and show["active_listing_id"] is not None:
            listing = connection.execute(
                "SELECT price_cents FROM listings WHERE listing_id = ? AND seller_id = ?",
                (show["active_listing_id"], authority.seller_id),
            ).fetchone()
            prices = [Decimal(value) for value in re.findall(r"\$(\d+(?:\.\d+)?)", reply_text)]
            if listing is not None and any(
                price != Decimal(int(listing["price_cents"])) / 100 for price in prices
            ):
                warnings.append("price_conflict")
        return tuple(warnings)

    @staticmethod
    def _sent_result(
        connection: sqlite3.Connection,
        receipt_id: str,
        *,
        idempotent_replay: bool,
    ) -> dict:
        row = connection.execute(
            """SELECT r.*, o.actor_type FROM copilot_reply_receipts r
               JOIN copilot_outbound_replies o ON o.reply_id = r.reply_id
               WHERE r.receipt_id = ?""",
            (receipt_id,),
        ).fetchone()
        reply = {
            "reply_id": row["reply_id"],
            "question_id": row["question_id"],
            "canonical_question_id": row["canonical_question_id"],
            "seller_id": row["seller_id"],
            "show_id": row["show_id"],
            "actor_id": row["actor_id"],
            "actor_type": row["actor_type"],
            "mode": row["mode"],
            "reply_text": row["reply_text"],
            "created_at": row["created_at"],
        }
        receipt = {
            "receipt_id": row["receipt_id"],
            "reply_id": row["reply_id"],
            "question_id": row["question_id"],
            "canonical_question_id": row["canonical_question_id"],
            "seller_id": row["seller_id"],
            "show_id": row["show_id"],
            "actor_id": row["actor_id"],
            "mode": row["mode"],
            "reply_text": row["reply_text"],
            "evidence_ids": json.loads(row["evidence_ids_json"]),
            "broker_outcome": row["broker_outcome"],
            "guardrail_verdict": row["guardrail_verdict"],
            "created_at": row["created_at"],
        }
        return {
            "status": "sent",
            "reply": reply,
            "receipt": receipt,
            "warnings": json.loads(row["warnings_json"]),
            "idempotent_replay": idempotent_replay,
        }


def copilot_projection(
    database: MarketplaceDatabase,
    *,
    seller_id: str,
    show_id: str,
) -> dict:
    with database.read() as connection:
        question_rows = connection.execute(
            """SELECT q.*, c.customer_display_name,
                      s.reply_text AS suggestion_text,
                      s.answer_category AS suggestion_category,
                      s.evidence_ids_json AS suggestion_evidence_ids,
                      s.snapshot_id AS suggestion_snapshot_id
               FROM copilot_questions q
               JOIN chat_events c ON c.event_id = q.event_id
               LEFT JOIN copilot_suggestions s ON s.question_id = q.question_id
               WHERE q.seller_id = ? AND q.show_id = ? AND q.route != 'noise'
               ORDER BY q.question_number""",
            (seller_id, show_id),
        ).fetchall()
        outbound = connection.execute(
            """SELECT * FROM copilot_outbound_replies
               WHERE seller_id = ? AND show_id = ? ORDER BY reply_number""",
            (seller_id, show_id),
        ).fetchall()
        receipts = connection.execute(
            """SELECT * FROM copilot_reply_receipts
               WHERE seller_id = ? AND show_id = ? ORDER BY receipt_number""",
            (seller_id, show_id),
        ).fetchall()
        active_epoch = connection.execute(
            """SELECT epoch_id FROM listing_epochs
               WHERE seller_id = ? AND show_id = ? AND end_seq IS NULL""",
            (seller_id, show_id),
        ).fetchone()
        active_epoch_id = active_epoch["epoch_id"] if active_epoch is not None else None
        capability_row = connection.execute(
            """SELECT * FROM copilot_r3_capabilities
               WHERE seller_id = ? AND show_id = ?""",
            (seller_id, show_id),
        ).fetchone()
    questions = []
    for row in question_rows:
        suggestion = None
        if row["suggestion_text"] is not None:
            suggestion = {
                "reply_text": row["suggestion_text"],
                "answer_category": row["suggestion_category"],
                "evidence_ids": json.loads(row["suggestion_evidence_ids"]),
                "snapshot_id": row["suggestion_snapshot_id"],
            }
        questions.append(
            {
                "question_id": row["question_id"],
                "event_id": row["event_id"],
                "customer_display_name": row["customer_display_name"],
                "raw_text": row["raw_text"],
                "asked_at": row["asked_at"],
                "route": row["route"],
                "state": row["state"],
                "reason_code": row["reason_code"],
                "bound_listing_id": row["bound_listing_id"],
                "previous_sku": (
                    row["bound_sku"]
                    if row["bound_epoch_id"] is not None
                    and row["bound_epoch_id"] != active_epoch_id
                    else None
                ),
                "canonical_question_id": row["canonical_question_id"],
                "suggestion": suggestion,
            }
        )
    return {
        "copilot_questions": questions,
        "outbound_replies": [dict(row) for row in outbound],
        "reply_receipts": [
            {
                **dict(row),
                "evidence_ids": json.loads(row["evidence_ids_json"]),
                "validated_versions": json.loads(row["validated_versions_json"]),
                "warnings": json.loads(row["warnings_json"]),
            }
            for row in receipts
        ],
        "r3_capability": {
            "seller_id": capability_row["seller_id"],
            "show_id": capability_row["show_id"],
            "enabled": bool(capability_row["enabled"]),
            "version": int(capability_row["version"]),
            "updated_by": capability_row["updated_by"],
            "updated_at": capability_row["updated_at"],
        },
    }


def _advance_question(
    connection: sqlite3.Connection,
    question_id: str,
    *,
    target: str,
    reason_code: str,
    changed_at: str,
) -> None:
    row = connection.execute(
        "SELECT state, asked_at FROM copilot_questions WHERE question_id = ?",
        (question_id,),
    ).fetchone()
    if row is None:
        raise KeyError(question_id)
    current = row["state"]
    if current == target:
        return
    path: list[str]
    if current == "queued" and target in {"awaiting_review", "auto_answered"}:
        path = ["ai_working", "awaiting_review"]
        if target == "auto_answered":
            path[-1] = "auto_answered"
    else:
        path = [target]
    for next_state in path:
        connection.execute(
            """INSERT INTO copilot_question_transitions(
                   question_id, from_state, to_state, asked_at,
                   state_changed_at, reason_code
               ) VALUES (?, ?, ?, ?, ?, ?)""",
            (question_id, current, next_state, row["asked_at"], changed_at, reason_code),
        )
        current = next_state
    connection.execute(
        """UPDATE copilot_questions
           SET state = ?, reason_code = ?, state_changed_at = ?
           WHERE question_id = ?""",
        (target, reason_code, changed_at, question_id),
    )


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("wall clock must return an aware datetime")
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )
