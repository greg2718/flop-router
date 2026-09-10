# TCLK linkage review — Decision B

2026-09-09. Contract/source-mapping review only; no runtime implementation.

**DECISION B: OFFER_ID_IS_NOT_AUTHORITATIVE.** A tclk/1 ACCEPT containing only
`offer_id` is not a valid authoritative acceptance of the named offer. The
producer correctly stopped on event 214. This does not endorse every part of its
current generic `ref or contract` traversal as a complete protocol implementation.

`TCLK_OFFER_ID_LINKAGE_BLOCKED = YES`

`SCOUT_PRODUCTION_SHAPED_LG2_PROJECTION_VALID = NO`

`ROUTER_PRODUCTION_SHAPED_HANDOFF_READY = NO`

## Evidence and scope

Read the [Scout dry-run report](../../flop_scout_v02/docs/router-projection-v2-lg2-production-dry-run.md),
[projection contract](SCOUT_ROUTER_SNAPSHOT_V2.md), Scout's source workflow review,
its `tclk_workflow`, cache parser/extraction and identity functions, and Router's
TCLK observation, settlement-evidence and closure paths/tests. No frozen warehouse,
production publication, live Scout/Router state or private originals were opened.

Scout's README identifies the official repository as `flop-labs/tclk`. Its
[wire schema](https://github.com/flop-labs/tclk/blob/main/schema/tclk1-frames.schema.json),
[SPEC §§2–4](https://github.com/flop-labs/tclk/blob/main/SPEC.md),
[reference frames](https://github.com/flop-labs/tclk/blob/main/src/frames.ts) and
[state machine](https://github.com/flop-labs/tclk/blob/main/src/machine.ts)
were reviewed on this date. These are repository documentation/code, not room
messages. Moving main-branch links are review evidence, not a frozen release pin;
a later implementation must pin the reviewed upstream version and golden vectors.
The required Technocore repository, llms.txt, auth.md and patterns.md were also
checked; transport authentication does not define application-level aliases.

The official schema requires ACCEPT's `ref` and `contract` and disallows extra
properties, including `offer_id`. `AcceptFrame`, `makeAccept`, `validateFrame` and
`requireKeys` agree. A well-formed ACCEPT has type/from/ref/statement/contract/nonce,
with paymentKey optional subject to lock-specific requirements. The builder sets
ref from the offer's id and computes contract separately. Neither missing required
fields nor an unknown field is repaired by successful transport verification.

## Identifier semantics

| Field/context | Meaning | Alias decision |
|---|---|---|
| OFFER `id` | Content-derived offer identity. | Root offer key. |
| ACCEPT `ref` | Exact OFFER id being accepted. | Offer reference in this frame class only. |
| ACCEPT `contract` | Derived identity binding the complete offer and acceptance core. | Distinct from offer id; both fields are required. |
| Post-accept `contract` | The negotiated agreement's identity. | Resolve through its validated acceptance, not by string equality with an offer key. |
| LOCK `ref` | Rail-specific escrow/payment/transaction reference. | Not an offer, workflow or prior-message identifier. |
| REVEAL/REFUND optional `ref` | Rail reference; when supplied it must match the lock reference. | Not ACCEPT.ref semantics. |
| RECEIPT optional `ref` | Optional receipt/rail context; never an alternative to required contract. | Do not traverse it as an offer key. |
| Signed frame `offer_id` | No field with this spelling is defined for tclk/1 ACCEPT. | Unsupported; no authoritative target. |
| Scout cache/export `offer_id` | Adapter column populated from frame `id`; also the source model's offer-root key label. | Normalized storage vocabulary, not a wire-field alias. |
| Router `TclkObservation.deal_id` | Display/evidence grouping fallback: contract_id, then offer_id, then location. | Not an authoritative workflow resolver or alias declaration. |

The identifier meanings above follow the official frame types; in particular,
`ref` changes meaning by frame class. Text equality across namespaces proves no
relationship. No reviewed field is a generic prior-message pointer.

## Message shapes and workflow effects

These are linkage summaries, not complete frame schemas. Every supported frame
also needs the required fields, structural validation and authenticated authorship.
Protocol state effects below describe observations only; Router executes none.

| Frame | Linkage fields | Target | Protocol effect / current projection restriction |
|---|---|---|---|
| OFFER | `id` | Its own validated offer identity | Proposed/open; no work success. |
| ACCEPT | `ref` AND `contract` | Offer plus derived agreement | Proposed → accepted after guards; never closed. |
| LOCK | `contract`, `ref` | Agreement and separate rail object | May enter locked; not a closure proof in current projection. |
| REVEAL / REFUND | `contract`, optional `ref` | Agreement and lock's rail reference | Terminal only under the protocol's full guards; current projection has no terminal-rail adapter. |
| CANCEL | `contract` | Agreement | Protocol permits cancellation before lock; current projection does not infer finite closure from this alone. |
| RECEIPT | `contract`, optional `rail`/`ref` | Already-terminal agreement | Acknowledgment, not a new transition or independent settlement verification. |
| HEARTBEAT | `contract` | Agreement | Liveness only; current Scout recognized-type list does not include it. Separate compatibility work. |
| RESULT | None defined in tclk/1 | External work protocol if explicitly linked | No TCLK RESULT transition. Do not import Kibble RESULT semantics. |
| EXPIRE | No wire frame | Local validated offer deadline | Existing projection permits expiry only without active or unresolved obligations. |
| SETTLEMENT / CONTRACT | No standalone frame types | Contract is an identifier; settlement is rail state | No fabricated frame or executable settlement path. |

The schema supplies the closed frame set. The reference `applyFrame` checks state,
ref/offer equality, different offer-maker/acceptor DIDs, pre-expiry time, derived
contract equality and statement/lock compatibility before entering accepted. It
rejects invalid/replayed transitions. None of those checks is replaced by a
successful lookup of a string named offer_id.

## Linkage, precedence and conflicts

No ACCEPT alias rule is added. Do not use `offer_id or ref or contract`, fill in
missing fields, normalize signed text, or compute a replacement acceptance on
behalf of its author. Valid normative linkage requires both exact ACCEPT.ref and
a correctly derived ACCEPT.contract, the unique authenticated offer, compatible
source provenance and the existing captured-domain restrictions.

| ACCEPT fields | Decision |
|---|---|
| offer_id only | Reject authoritative linkage; preserve unresolved evidence. |
| offer_id + ref, whether equal or different | Reject unknown wire field; missing contract independently rejects. Agreement does not legalize an extra key. |
| offer_id + contract | Reject unknown field and missing ref, even if a graph lookup reaches one offer. |
| offer_id + ref + contract | Reject extra field even when the other fields are otherwise valid. |
| ref + contract, correctly bound | Required pair, not redundant aliases; validate both and all remaining fields/guards. |
| ref points to one offer, contract derives from another | Reject true binding conflict. |
| ref and contract text happens to be identical | Equality is not evidence of validity; independently verify their different meanings and derivations. |
| Blank, wrong-type, malformed, absent or ambiguous required target | Reject; no fallback or first/majority winner. |

Duplicate target candidates must not be chosen by query order. Identical transport
replays may be recognized under the separately validated immutable identity rules;
competing source identities, content, issuer or lineage remain unresolved/conflicting.
Bounds must fail closed rather than dropping candidates.

## Workflow and interaction identities

Keep `sw1:` derived from the canonical `flop-scout-workflow-identity/v1` object:
protocol tclk/1, source namespace, verified root maker, root room/captured generation,
and key type offer_id whose value is the validated OFFER.id. That key label does
not authorize an ACCEPT.offer_id wire property. Reparse order, cache rowid, ACCEPT
arrival order, similar text and publication IDs cannot select or merge workflows.
Invalid ACCEPTs do not acquire authoritative workflow membership or state change.
A valid acceptance remains active/unresolved for current projection retention;
acceptance is not successful work or settlement.

An ACCEPT is a distinct source message from its OFFER. Existing `si1:` identities
hash relationship type and immutable, role-labelled source/target endpoint facts
(raw identity, room, captured generation, sequence, sender). No extra edge is
created merely because an ACCEPT has multiple linkage fields. A source-backed
interaction, if present and unambiguously resolved, keeps its distinct ID; this
review authorizes no new synthetic OFFER or ACCEPT interactions. There is no
requirement to invent an OFFER interaction when only the root message exists.

No changes to durable qualifications, current support, same-operator exclusions or
independent reputation are justified. Relationship/linkage evidence is not proof
of execution. Existing separately configured TCLK settlement observations remain
subject to their current evidence boundary; their normalized offer_id fields are
not proof of wire validity or authority to execute settlement.

## LG2 and generation boundaries

UNKNOWN_LEGACY remains UNKNOWN_LEGACY. Reported 0/1 is audit-only and cannot bridge
target domains, select a root, change an interaction ID or promote qualification.
An exact offer identifier does not relax source/generation checks. Current projection
mapping scopes to the source room and captured generation. Normative post-accept
traffic uses a derived deal room, so complete protocol support also needs a separately
reviewed cross-room provenance mapping; room generations are not globally comparable
numbers. Do not silently widen the current lookup or use LG2 reports as that mapping.

## Current runtime gaps and ownership

**Scout:** `tclk_parse_frame_text` recognizes the type, not the complete official
schema. `tclk_record_from_message` extracts id/contract/ref into cached fields.
`tclk_workflow` then takes id for offers, otherwise ref-or-contract, and walks a
bounded graph. This explains event 214 without proving an alias. A future correction
must distinguish full wire validity, authenticated-but-nonconforming audit data and
root/contract/rail namespaces. It must retain exact originals and classify receipts
separately. Do not add offer_id acceptance, discard affected raws, or emit partial
healthy output as a repair.

**Router:** this is not producer-only. `ClosureVerifier.__init__` independently
extracts ref-or-contract from raw projected text; `verify` uses those facts to rule
out active transitions before expiry. Canonical producer workflow state is private,
not a published workflow table that Router can simply trust. `TclkObservationAdapter`,
`tclk_frame_valid` and `settlement_level_for_tclk` consume normalized evidence and
are not complete normative frame/contract validators. Existing `scout_tclk_offer_record`
fixtures and the minimal deadline fixture test these interfaces, not the official
wire grammar. This review does not relabel their passing tests as conformance.

A pure in-memory probe reused `workflow_database` and `verify_closure` from
`test_projection_performance.py`, changing only an accept-shaped fixture's linkage
spelling. With ref, expiry rejected as CONTINUITY_UNVERIFIED_TERMINAL_TRANSITION;
with offer_id, expiry was allowed. These minimal fixtures are deliberately not full
valid tclk/1 messages. The result demonstrates an unrecognized-transition retention
gap, not validity of offer_id. A later conservative retention design must prevent
ignored nonconforming related evidence from proving absence of obligations, without
making it authoritative acceptance. The known invalid producer cut must not reach
Router in the meantime.

Future Router work must independently validate the agreed typed linkage/retention
rules, distinguish malformed retained evidence from valid transitions, preserve
unresolved obligations and add normative vectors alongside existing adapter tests.
It must not mint commitments, secrets, signatures or invoke rail operations.

## Versioning and reconciliation

No wire, classifier, selection, source-mapping or LG2 storage version changes in
this review: Decision B adds no accepted alias and does not silently change runtime
acceptance. Existing schema/encoding/policy values stay frozen. The documentation
clarifies an unsupported shape and records implementation limitations.

A new permissive legacy dialect or unresolved-audit representation would be a
separate contract decision with an exact version, manifest binding, migration and
replay tests before implementation. No new value is selected here because that
representation is not yet approved. Likewise, stricter mapping/closure behavior
must be coordinated and explicitly versioned where it changes retained membership
or accepted source classes, rather than hidden under today's classifier version.

Do not rewrite historical signed ACCEPT bodies into ref/contract form or fabricate
missing contract commitments. Reconciliation needs either a documented, versioned
historical dialect with original-emitter evidence and full binding vectors, or an
explicit contract for preserving nonconforming unresolved audit evidence without
claiming accepted state. A new conforming message cannot retroactively change what
an old signed message said. Missing target/proof remains missing until independently
supplied through authorized evidence channels. This review authorizes no outreach.

## Production prevalence and next dry run

Only the supplied Scout report was used for production statistics:

| Structural class | Distinct raws |
|---|---:|
| ACCEPT; offer_id string; no ref/contract; captured UNKNOWN_LEGACY; reported 1 | 2,373 |
| RECEIPT; no ref/contract; captured UNKNOWN_LEGACY; reported 0 | 49 |
| RECEIPT; no ref/contract; captured 0; reported NULL | 83 |
| Total | 2,505 |

These are structural matches among 342,582 scanned linked pairs, not 2,505 completed
admission failures. Only event 214 was reproduced as the stopping scalar failure.
The 132 receipts require separate reconciliation; adding an ACCEPT alias could
not fix them. No target uniqueness, derived-contract validity or complete-shape
counts were provided for this population.

Minimum follow-up from Scout's owner: aggregate complete frame validation outcomes
by type and captured domain; field-presence/type combinations for the receipts;
counts of missing/unique/conflicting offer roots, exact original-source bindings,
full ref/contract derivation checks where supplied, same/cross-room and captured-
generation matches, and emitter/schema version evidence where actually available.
No raw text, IDs, signatures or private keys are needed in that aggregate report.
Those counts diagnose reconciliation; they cannot by themselves establish an alias.

Do not rerun by adding a fallback or skipping event 214. First approve a versioned
reconciliation/retention design and independent producer/consumer fixtures. Then,
under separate authorization, repeat a complete producer cut with valid pins,
originals, dependencies and history. Only a valid immutable publication can be
handed to Router for the unchanged 30-second/512-MiB/4-GiB qualification.

## Planned tests — not implemented here

1. Authenticated ACCEPT with offer_id naming an existing offer: reject as unsupported.
2. Missing target for a normative ref: reject; preserve unresolved evidence.
3. Duplicate/competing target offers: no arbitrary winner.
4. Invalid signature or frame/transport sender mismatch: no authoritative transition.
5. offer_id + ref same value: reject extra key, no alias.
6. offer_id + ref conflicting values: reject, no precedence.
7. offer_id + contract apparently reaches same offer: reject; namespaces are distinct.
8. Cross-generation ref lookup: no bridge.
9. UNKNOWN_LEGACY plus reported 0/1: unchanged captured domain and IDs.
10. Valid normative ACCEPT with complete fields and recomputed contract: stable workflow ID.
11. Valid source-backed interaction: distinct stable si1; no duplicate from multiple fields.
12. Valid ACCEPT enters accepted/active, never finite closure; late or self-accept rejects.
13. ACCEPT linkage alone confers no capability qualification or successful work claim.
14. Same-operator relations retain independence exclusions.
15. Restart/reparse/replay preserves original bytes, IDs, history and failure outcomes.
16. Unsupported future mapping/dialect policy rejects; no silent cache reuse or migration.
17. Canonical ref plus wrong derived contract: reject despite valid signature.
18. Nonconforming offer_id transition cannot justify offer expiry by being ignored.
19. Contract and rail ref namespace collision: never traverse the rail reference as an offer.
20. Receipt without contract: unresolved/rejected; a receipt alone neither settles nor closes.
21. Unknown RESULT/EXPIRE/SETTLEMENT/CONTRACT frame types: no invented transition.
22. Full normative vectors plus original adapter fixtures remain distinctly labelled.

Implementation readiness: the proposed offer_id alias is **blocked**, not ready
for coding. Decision B resolves the identifier question; production handoff remains
blocked pending a separately reviewed reconciliation design. No runtime suite was
rerun for documentation changes. The in-memory retention probe and documentation
checks are the only new validation performed. STOP for coordinated review.
