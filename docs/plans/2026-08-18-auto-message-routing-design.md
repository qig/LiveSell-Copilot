# Auto-message and Routing Corrections Design

**Status:** Accepted and implemented in the dirty worktree on 2026-08-18. Focused and full regression commands pass, but the result is not commit-bound `Verified` evidence.

## Product behavior

The seller workspace exposes two reply modes in plain language:

- **Auto-message:** the default. Every reply that passes the existing deterministic broker checks is sent automatically. A question that lacks evidence, is ambiguous, is stale, or otherwise needs judgment remains in Manual review.
- **Manual review:** every safe candidate is held for seller review. Questions that need judgment remain visibly marked as needing seller input.

The UI does not expose the internal `R2` or `R3` names. Internal capability fields and API paths may retain `r3` for backward compatibility.

## Exact variant absence

Variant interpretation remains application-owned. Python parses buyer wording and trusted catalog labels into `size_system`, `audience`, and decimal `size` attributes.

When a buyer asks for one exact typed size and the complete bound-listing catalog has no matching variant, Python produces one trusted negative availability fact such as `US M 6.5: 0 available`. No model chooses a variant ID, and no complete inventory array is added to model input. Missing system or audience may be inferred only when all trusted candidates agree. Mixed candidates stay ambiguous, and an untyped number stays unsupported rather than being treated as a shoe size.

Both registered workflows consume the same deterministic fact. The final-send check repeats the catalog-scope and freshness validation before any automatic send.

## Auto-message authority

Auto-message is an execution mode, not an expanded source of authority. The existing broker still validates tenant, seller, show, listing epoch, evidence identity, freshness, claim support, tone, and canonical-question uniqueness. If those checks produce a safe reply with one authoritative factual basis, Auto-message may send it regardless of supported answer category. The model never receives send authority.

The final gateway revalidates the exact evidence type immediately before committing the reply and receipt. Any failed revalidation downgrades to review or seller input; it never sends optimistically.

## Previous-listing questions

A question bound to a no-longer-active listing is never silently retargeted. Python builds a deterministic notice from the trusted current listing, for example: `We’re showing Aero Dash right now—the item you asked about is no longer on stage.` It makes zero model calls and does not answer the old listing’s price, inventory, or policy question.

In Auto-message mode the notice is sent automatically. In Manual review mode it is presented as a reviewable suggestion. If the current listing cannot be established from trusted state, the question needs seller input.

## Duplicate boundary

Marketplace event-ID replay remains idempotent forever. Text-level duplicate grouping is limited to a five-second rolling window within the same seller, show, listing epoch, and canonical key. A matching question after that window becomes a new canonical question and may receive a new reply. The database lookup index is non-unique because canonical identity now includes time-window behavior enforced transactionally in Python.

## User-visible state

New shows and demo reset start in Auto-message mode. An explicit seller switch to Manual review is versioned and preserved until reset. The header, warning, notices, and controls use only `Auto-message` and `Manual review` wording.

## Safety invariants

- An exact absence is derived only from the immutable bound listing’s complete trusted catalog and inventory.
- An ambiguous, unsupported, missing, stale, or cross-scope fact never auto-sends.
- A previous-listing notice discloses the listing transition and never answers using the current item’s facts as though they belonged to the old item.
- Repeated event IDs never create a second question; repeated text outside five seconds may.
- Reply, receipt, and terminal question state remain one local atomic transaction.
