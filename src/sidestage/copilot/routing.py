"""Deterministic normalization, deduplication, and ask-time listing routing."""

from __future__ import annotations

import re
import sqlite3
import unicodedata
from typing import Callable, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from sidestage.copilot.contracts import BoundListing
from sidestage.domain.replies import (
    BindingBasis,
    BindingStatus,
    QuestionState,
    ReplyRoute,
)
from sidestage.copilot.contracts import AnalysisIntent
from sidestage.fixtures.loader import SellerCatalog
from sidestage.storage.database import MarketplaceDatabase
from sidestage.streaming.ingest import AcceptedChatEvent

# TODO: this can be expanded from an external "db of noises". Def need optimization.
_DETERMINISTIC_NOISE_PHRASES = frozenset(
    {
        "hello",
        "hi",
        "hey",
        "yo",
        "thanks",
        "thank you",
        "good morning",
        "good evening",
        "lets gooo",
        "clean pair",
        "that colorway is nice",
        "big w",
    }
)
_ADVERSARIAL_MARKERS = (
    "ignore previous instructions",
    "ignore all instructions",
    "system prompt",
    "developer message",
    "send without approval",
)


class RoutingDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    question_id: str
    event_id: str
    route: ReplyRoute
    state: Optional[QuestionState]
    reason_code: str
    normalized_text: str
    canonical_key: str
    canonical_question_id: Optional[str]
    bound_listing: Optional[BoundListing]
    should_process: bool
    event_replay: bool = False


class NormalizedQuestion(BaseModel):
    """Durable output of stage 2 before deterministic route evaluation."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    question_id: str
    event_id: str
    event: AcceptedChatEvent
    normalized_text: str
    canonical_key: str
    canonical_scope: str
    canonical_question_id: Optional[str]
    bound_listing: Optional[BoundListing]
    preclassified_decision: Optional[RoutingDecision] = None


def canonicalize_question(raw_text: str) -> str:
    """Apply the approved v1 normalization without semantic paraphrasing."""

    characters = []
    for character in raw_text.casefold().strip():
        category = unicodedata.category(character)
        characters.append(" " if category.startswith(("P", "S")) else character)
    return " ".join("".join(characters).split())


def is_deterministic_noise(raw_text: str, normalized_text: Optional[str] = None) -> bool:
    if not any(character.isalnum() for character in raw_text):
        return True
    normalized = normalized_text if normalized_text is not None else canonicalize_question(raw_text)
    return normalized in _DETERMINISTIC_NOISE_PHRASES


def explicit_product_matches(seller, raw_text: str):
    """Match stable seller-owned product/listing names without fuzzy guessing."""

    normalized_text = canonicalize_question(raw_text)
    matches = []
    for product in seller.products:
        aliases = {
            canonicalize_question(product.sku),
            canonicalize_question(product.model_name),
            canonicalize_question(product.listing.title),
            canonicalize_question(f"{product.brand} {product.model_name}"),
            canonicalize_question(product.colorway),
        }
        if any(
            alias and re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", normalized_text)
            for alias in aliases
        ):
            matches.append(product)
    return tuple(matches)


class CopilotRouter:
    """Persist exactly one tenant/epoch-scoped routing decision per raw event."""

    def __init__(
        self,
        database: MarketplaceDatabase,
        catalog: SellerCatalog,
        *,
        id_factory: Callable[[], str] = lambda: f"qst_{uuid4().hex}",
    ) -> None:
        self.database = database
        self.catalog = catalog
        self.id_factory = id_factory

    def normalize_and_deduplicate(self, event: AcceptedChatEvent) -> NormalizedQuestion:
        normalized = canonicalize_question(event.raw_text)
        canonical_key = normalized
        with self.database.transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM copilot_questions WHERE event_id = ?",
                (event.event_id,),
            ).fetchone()
            if existing is not None:
                decision = (
                    None
                    if existing["route"] == "pending"
                    else self._decision_from_row(existing, event_replay=True)
                )
                return self._normalized_from_row(
                    existing,
                    event=event,
                    preclassified_decision=decision,
                )

            if is_deterministic_noise(event.raw_text, normalized):
                question_id = self.id_factory()
                self._insert_question_row(
                    connection,
                    question_id=question_id,
                    event=event,
                    route=ReplyRoute.NOISE.value,
                    state=None,
                    reason_code="deterministic_noise",
                    normalized_text=normalized,
                    canonical_key=canonical_key or "noise",
                    canonical_scope=f"noise:{event.event_id}",
                    canonical_question_id=None,
                    bound_listing=None,
                )
                decision = RoutingDecision(
                    question_id=question_id,
                    event_id=event.event_id,
                    route=ReplyRoute.NOISE,
                    state=None,
                    reason_code="deterministic_noise",
                    normalized_text=normalized,
                    canonical_key=canonical_key or "noise",
                    canonical_question_id=None,
                    bound_listing=None,
                    should_process=False,
                )
                return NormalizedQuestion(
                    question_id=question_id,
                    event_id=event.event_id,
                    event=event,
                    normalized_text=normalized,
                    canonical_key=canonical_key or "noise",
                    canonical_scope=f"noise:{event.event_id}",
                    canonical_question_id=None,
                    bound_listing=None,
                    preclassified_decision=decision,
                )

            bound_listing = self._resolve_binding(connection, event)
            canonical_scope = (
                bound_listing.epoch_id
                if bound_listing is not None
                else f"unbound:{event.event_id}"
            )
            canonical = connection.execute(
                """SELECT question_id FROM copilot_questions
                   WHERE seller_id = ? AND show_id = ? AND canonical_scope = ?
                     AND canonical_key = ? AND canonical_question_id IS NULL
                     AND route != 'noise'
                   ORDER BY question_number LIMIT 1""",
                (event.seller_id, event.show_id, canonical_scope, canonical_key),
            ).fetchone()
            if canonical is not None:
                question_id = self.id_factory()
                self._insert_question_row(
                    connection,
                    question_id=question_id,
                    event=event,
                    route=ReplyRoute.DUPLICATE.value,
                    state=QuestionState.GROUPED,
                    reason_code="normalization_equivalent_duplicate",
                    normalized_text=normalized,
                    canonical_key=canonical_key,
                    canonical_scope=canonical_scope,
                    canonical_question_id=canonical["question_id"],
                    bound_listing=bound_listing,
                )
                self._insert_transition(
                    connection,
                    question_id=question_id,
                    from_state=None,
                    to_state=QuestionState.GROUPED,
                    asked_at=event.accepted_at,
                    reason_code="normalization_equivalent_duplicate",
                )
                decision = RoutingDecision(
                    question_id=question_id,
                    event_id=event.event_id,
                    route=ReplyRoute.DUPLICATE,
                    state=QuestionState.GROUPED,
                    reason_code="normalization_equivalent_duplicate",
                    normalized_text=normalized,
                    canonical_key=canonical_key,
                    canonical_question_id=canonical["question_id"],
                    bound_listing=bound_listing,
                    should_process=False,
                )
                return NormalizedQuestion(
                    question_id=question_id,
                    event_id=event.event_id,
                    event=event,
                    normalized_text=normalized,
                    canonical_key=canonical_key,
                    canonical_scope=canonical_scope,
                    canonical_question_id=canonical["question_id"],
                    bound_listing=bound_listing,
                    preclassified_decision=decision,
                )

            question_id = self.id_factory()
            self._insert_question_row(
                connection,
                question_id=question_id,
                event=event,
                route="pending",
                state=None,
                reason_code="normalization_complete",
                normalized_text=normalized,
                canonical_key=canonical_key,
                canonical_scope=canonical_scope,
                canonical_question_id=None,
                bound_listing=bound_listing,
            )
            return NormalizedQuestion(
                question_id=question_id,
                event_id=event.event_id,
                event=event,
                normalized_text=normalized,
                canonical_key=canonical_key,
                canonical_scope=canonical_scope,
                canonical_question_id=None,
                bound_listing=bound_listing,
            )

    def route(self, value) -> RoutingDecision:
        normalized = (
            self.normalize_and_deduplicate(value)
            if isinstance(value, AcceptedChatEvent)
            else value
        )
        if not isinstance(normalized, NormalizedQuestion):
            raise TypeError("route requires AcceptedChatEvent or NormalizedQuestion")
        if normalized.preclassified_decision is not None:
            return normalized.preclassified_decision

        event = normalized.event
        bound_listing = normalized.bound_listing
        with self.database.transaction() as connection:
            if bound_listing is None or bound_listing.binding_status is BindingStatus.UNCERTAIN:
                return self._finalize_decision(
                    connection,
                    normalized=normalized,
                    route=ReplyRoute.AMBIGUOUS_OR_UNSUPPORTED,
                    state=QuestionState.NEEDS_SELLER,
                    reason_code="uncertain_listing_binding",
                    should_process=False,
                )

            active_epoch = connection.execute(
                """SELECT epoch_id FROM listing_epochs
                   WHERE seller_id = ? AND show_id = ? AND end_seq IS NULL""",
                (event.seller_id, event.show_id),
            ).fetchone()
            if active_epoch is None or active_epoch["epoch_id"] != bound_listing.epoch_id:
                return self._finalize_decision(
                    connection,
                    normalized=normalized,
                    route=ReplyRoute.ELIGIBLE,
                    state=QuestionState.NEEDS_SELLER,
                    reason_code="previous_listing",
                    should_process=False,
                )

            route = (
                ReplyRoute.ADVERSARIAL
                if any(marker in event.raw_text.casefold() for marker in _ADVERSARIAL_MARKERS)
                else ReplyRoute.ELIGIBLE
            )
            return self._finalize_decision(
                connection,
                normalized=normalized,
                route=route,
                state=QuestionState.QUEUED,
                reason_code="eligible_candidate" if route is ReplyRoute.ELIGIBLE else "adversarial_candidate",
                should_process=True,
            )

    def refine_route_after_analysis(
        self,
        event: AcceptedChatEvent,
        question_id: str,
        intent: AnalysisIntent,
    ) -> ReplyRoute:
        """Persist the actual route when bounded analysis resolves a harder non-answer."""

        route = {
            AnalysisIntent.AMBIGUOUS: ReplyRoute.AMBIGUOUS_OR_UNSUPPORTED,
            AnalysisIntent.UNSUPPORTED: ReplyRoute.AMBIGUOUS_OR_UNSUPPORTED,
            AnalysisIntent.ADVERSARIAL: ReplyRoute.ADVERSARIAL,
            AnalysisIntent.NO_RESPONSE_NEEDED: ReplyRoute.NOISE,
        }.get(intent, ReplyRoute.ELIGIBLE)
        with self.database.transaction() as connection:
            row = connection.execute(
                """SELECT seller_id, show_id FROM copilot_questions
                   WHERE question_id = ?""",
                (question_id,),
            ).fetchone()
            if (
                row is None
                or row["seller_id"] != event.seller_id
                or row["show_id"] != event.show_id
            ):
                raise KeyError("analysis route refinement is outside the trusted scope")
            connection.execute(
                "UPDATE copilot_questions SET route = ? WHERE question_id = ?",
                (route.value, question_id),
            )
        return route

    def _resolve_binding(
        self,
        connection: sqlite3.Connection,
        event: AcceptedChatEvent,
    ) -> Optional[BoundListing]:
        seller = self.catalog.seller(event.seller_id)
        explicit_products = explicit_product_matches(seller, event.raw_text)
        if len(explicit_products) > 1:
            return None
        if len(explicit_products) == 1:
            product = explicit_products[0]
            epoch = connection.execute(
                """SELECT epoch_id FROM listing_epochs
                   WHERE seller_id = ? AND show_id = ? AND listing_id = ?
                   ORDER BY epoch_number DESC LIMIT 1""",
                (event.seller_id, event.show_id, product.listing.listing_id),
            ).fetchone()
            if epoch is None:
                return None
            return BoundListing(
                listing_id=product.listing.listing_id,
                sku=product.sku,
                epoch_id=epoch["epoch_id"],
                binding_basis=BindingBasis.EXPLICIT,
                binding_status=BindingStatus.CERTAIN,
            )

        if event.source_epoch_id is None or event.source_listing_id is None:
            return None
        product = next(
            (
                candidate
                for candidate in seller.products
                if candidate.listing.listing_id == event.source_listing_id
            ),
            None,
        )
        if product is None:
            return None
        epoch = connection.execute(
            """SELECT epoch_id FROM listing_epochs
               WHERE epoch_id = ? AND seller_id = ? AND show_id = ? AND listing_id = ?""",
            (
                event.source_epoch_id,
                event.seller_id,
                event.show_id,
                event.source_listing_id,
            ),
        ).fetchone()
        if epoch is None:
            return None
        return BoundListing(
            listing_id=product.listing.listing_id,
            sku=product.sku,
            epoch_id=event.source_epoch_id,
            binding_basis=BindingBasis.SOURCE_EPOCH,
            binding_status=BindingStatus.CERTAIN,
        )


    @staticmethod
    def _insert_question_row(
        connection: sqlite3.Connection,
        *,
        question_id: str,
        event: AcceptedChatEvent,
        route: str,
        state: Optional[QuestionState],
        reason_code: str,
        normalized_text: str,
        canonical_key: str,
        canonical_scope: str,
        canonical_question_id: Optional[str],
        bound_listing: Optional[BoundListing],
    ) -> None:
        connection.execute(
            """INSERT INTO copilot_questions(
                   question_id, event_id, seller_id, show_id, raw_text,
                   normalized_text, canonical_key, canonical_scope,
                   canonical_question_id, route, state, reason_code,
                   bound_epoch_id, bound_listing_id, bound_sku,
                   binding_basis, binding_status, workflow_id, model_profile_id,
                   requested_model_id, model_config_ref, model_provider,
                   selection_version, selection_selected_at,
                   asked_at, state_changed_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                question_id,
                event.event_id,
                event.seller_id,
                event.show_id,
                event.raw_text,
                normalized_text,
                canonical_key,
                canonical_scope,
                canonical_question_id,
                route,
                state.value if state is not None else None,
                reason_code,
                bound_listing.epoch_id if bound_listing else None,
                bound_listing.listing_id if bound_listing else None,
                bound_listing.sku if bound_listing else None,
                bound_listing.binding_basis.value if bound_listing else None,
                bound_listing.binding_status.value if bound_listing else None,
                event.workflow_id,
                event.model_profile_id,
                event.requested_model_id,
                event.model_config_ref,
                event.model_provider,
                event.selection_version,
                event.selection_selected_at,
                event.accepted_at,
                event.accepted_at,
            ),
        )

    def record_runtime_execution(
        self,
        question_id: str,
        *,
        sample_phase: str,
        resolved_model_id: Optional[str] = None,
        resolved_provider: Optional[str] = None,
    ) -> None:
        """Attach model-backed execution identity without changing question state."""

        with self.database.transaction() as connection:
            cursor = connection.execute(
                """UPDATE copilot_questions
                   SET sample_phase = ?,
                       resolved_model_id = COALESCE(?, resolved_model_id),
                       resolved_provider = COALESCE(?, resolved_provider)
                   WHERE question_id = ?""",
                (sample_phase, resolved_model_id, resolved_provider, question_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(question_id)

    def _finalize_decision(
        self,
        connection: sqlite3.Connection,
        *,
        normalized: NormalizedQuestion,
        route: ReplyRoute,
        state: QuestionState,
        reason_code: str,
        should_process: bool,
    ) -> RoutingDecision:
        connection.execute(
            """UPDATE copilot_questions
               SET route = ?, state = ?, reason_code = ?, state_changed_at = ?
               WHERE question_id = ? AND route = 'pending'""",
            (
                route.value,
                state.value,
                reason_code,
                normalized.event.accepted_at,
                normalized.question_id,
            ),
        )
        self._insert_transition(
            connection,
            question_id=normalized.question_id,
            from_state=None,
            to_state=QuestionState.QUEUED,
            asked_at=normalized.event.accepted_at,
            reason_code="accepted",
        )
        if state is not QuestionState.QUEUED:
            self._insert_transition(
                connection,
                question_id=normalized.question_id,
                from_state=QuestionState.QUEUED,
                to_state=state,
                asked_at=normalized.event.accepted_at,
                reason_code=reason_code,
            )
        return RoutingDecision(
            question_id=normalized.question_id,
            event_id=normalized.event_id,
            route=route,
            state=state,
            reason_code=reason_code,
            normalized_text=normalized.normalized_text,
            canonical_key=normalized.canonical_key,
            canonical_question_id=normalized.canonical_question_id,
            bound_listing=normalized.bound_listing,
            should_process=should_process,
        )

    @staticmethod
    def _insert_transition(
        connection: sqlite3.Connection,
        *,
        question_id: str,
        from_state: Optional[QuestionState],
        to_state: QuestionState,
        asked_at: str,
        reason_code: str,
    ) -> None:
        connection.execute(
            """INSERT INTO copilot_question_transitions(
                   question_id, from_state, to_state, asked_at,
                   state_changed_at, reason_code
               ) VALUES (?, ?, ?, ?, ?, ?)""",
            (
                question_id,
                from_state.value if from_state is not None else None,
                to_state.value,
                asked_at,
                asked_at,
                reason_code,
            ),
        )

    @staticmethod
    def _decision_from_row(row: sqlite3.Row, *, event_replay: bool) -> RoutingDecision:
        bound_listing = None
        if row["bound_listing_id"] is not None:
            bound_listing = BoundListing(
                listing_id=row["bound_listing_id"],
                sku=row["bound_sku"],
                epoch_id=row["bound_epoch_id"],
                binding_basis=BindingBasis(row["binding_basis"]),
                binding_status=BindingStatus(row["binding_status"]),
            )
        state = QuestionState(row["state"]) if row["state"] is not None else None
        route = ReplyRoute(row["route"])
        return RoutingDecision(
            question_id=row["question_id"],
            event_id=row["event_id"],
            route=route,
            state=state,
            reason_code=row["reason_code"],
            normalized_text=row["normalized_text"],
            canonical_key=row["canonical_key"],
            canonical_question_id=row["canonical_question_id"],
            bound_listing=bound_listing,
            should_process=state is QuestionState.QUEUED
            and route in {ReplyRoute.ELIGIBLE, ReplyRoute.ADVERSARIAL},
            event_replay=event_replay,
        )

    @classmethod
    def _normalized_from_row(
        cls,
        row: sqlite3.Row,
        *,
        event: AcceptedChatEvent,
        preclassified_decision: Optional[RoutingDecision],
    ) -> NormalizedQuestion:
        return NormalizedQuestion(
            question_id=row["question_id"],
            event_id=row["event_id"],
            event=event,
            normalized_text=row["normalized_text"],
            canonical_key=row["canonical_key"],
            canonical_scope=row["canonical_scope"],
            canonical_question_id=row["canonical_question_id"],
            bound_listing=cls._bound_listing_from_row(row),
            preclassified_decision=preclassified_decision,
        )

    @staticmethod
    def _bound_listing_from_row(row: sqlite3.Row) -> Optional[BoundListing]:
        if row["bound_listing_id"] is None:
            return None
        return BoundListing(
            listing_id=row["bound_listing_id"],
            sku=row["bound_sku"],
            epoch_id=row["bound_epoch_id"],
            binding_basis=BindingBasis(row["binding_basis"]),
            binding_status=BindingStatus(row["binding_status"]),
        )
