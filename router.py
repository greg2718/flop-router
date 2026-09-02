#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import json
import math
import re
import sqlite3
import time
import unicodedata
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from typing import Iterable


DEFAULT_DB_PATH = Path("devdata/observer.sqlite")
DEFAULT_VALIDATION_STORE = Path("devdata/validations.jsonl")
DEFAULT_INGEST_STORE = Path("devdata/technocore_exports.jsonl")
DEFAULT_TCLK_STORE = Path("devdata/tclk_observations.jsonl")
DEFAULT_VERIFICATION_EVIDENCE_STORE = Path("devdata/verification_evidence.jsonl")
DEFAULT_EVIDENCE_CONSISTENCY_FIXTURE = Path("fixtures/evidence_consistency.jsonl")
DEFAULT_ROUTER_STATE_DIR = Path.home() / ".flop_agents" / "router"
REPORTS_DIR = Path("reports")
DID_RE = re.compile(r"^did:key:z6Mk[1-9A-HJ-NP-Za-km-z]+")
VALIDATION_PASS_THRESHOLD = 80
VALIDATION_PARTIAL_THRESHOLD = 50
UNKNOWN_GENERATION = "UNKNOWN_LEGACY"
SCOUT_DID = "did:key:z6MkfJnczowbivU9SEDcZ77MEpKUfQTVbcD3i1gcwsfo4yL1"
BENCH_DID = "did:key:z6MkqqqEMxujBTEAvoanSx6pVBMMZzLP7gMUcmNVdYHS3BVk"
LOCAL_OPERATOR_GROUP = "flop-labs-local"
ROUTER_OPERATOR_GROUP = "local-flop-agent-family"
ROUTER_CANONICAL_ROOM = "d-flop-router"
ROUTER_MAILBOX = "mb-flop-router"

VERIFICATION_STATES = {
    "VERIFIED_OFFLINE",
    "INVALID_SIGNATURE",
    "SIGNATURE_PRESENT_UNVERIFIED",
    "LEGACY_SERVER_VERIFIED_NO_SIGNATURE",
    "UNSIGNED",
    "UNSIGNED_LOCAL",
    "PROVENANCE_INCOMPLETE",
}

SETTLEMENT_EVIDENCE_LEVELS = {
    "VERIFIED_USAGE",
    "OBSERVED_SIGNED_SUPPORT",
    "ADVERTISED_HINT",
    "NO_EVIDENCE",
    "CONTRADICTED",
}
TCLK_AMOUNT_RE = re.compile(r"^(0|[1-9][0-9]*)$")


@dataclass(frozen=True)
class AgentIdentity:
    did: str
    network: str = "technocore"


@dataclass(frozen=True)
class AgentObservation:
    identity: AgentIdentity
    room: str
    sequence_id: int
    timestamp: str | None
    text: str
    normalized_text: str
    template_hash: str
    is_signed: bool
    template_dids: int = 1
    generation: str = UNKNOWN_GENERATION
    server_timestamp: str | None = None
    nonce: str | None = None
    sig: str | None = None
    message_hash: str | None = None
    verification_status: str = "LEGACY_SERVER_VERIFIED_NO_SIGNATURE"
    source_export_hash: str | None = None
    source_export_path: str | None = None
    evidence_id: str | None = None

    @property
    def location_id(self) -> str:
        return f"{self.room} generation {self.generation} seq {self.sequence_id}"


@dataclass(frozen=True)
class EvidenceItem:
    room: str
    seq: int
    timestamp: str | None
    sequence_id: str
    text: str
    evidence_type: str
    specificity: float
    usable: bool
    strong: bool
    reasons: list[str]
    generation: str = UNKNOWN_GENERATION
    did: str | None = None
    nonce: str | None = None
    sig: str | None = None
    message_hash: str | None = None
    verification_status: str = "PROVENANCE_INCOMPLETE"
    source_export_hash: str | None = None
    source_export_path: str | None = None
    evidence_id: str | None = None


@dataclass(frozen=True)
class CapabilityEvidenceDecision:
    capability_id: str
    observation_id: str
    relevant: bool
    relevance_basis: str
    matched_patterns: list[str]
    evidence_type: str
    evidence_quality: str
    support_contribution: str
    passed_threshold: bool
    reason: str
    evidence: EvidenceItem


@dataclass
class AgentCapability:
    capability_id: str
    confidence: float
    supporting_observation_count: int
    supporting_sequence_ids: list[str]
    representative_evidence: list[str]
    contradictory_evidence: list[str] = field(default_factory=list)
    evidence_type_counts: dict[str, int] = field(default_factory=dict)
    strong_supporting_observation_count: int = 0
    medium_supporting_observation_count: int = 0
    signal_observation_count: int = 0
    support_level: str = "NO_EVIDENCE"
    evidence_items: list[EvidenceItem] = field(default_factory=list)
    quality_warning: str | None = None


@dataclass(frozen=True)
class ValidationTarget:
    did: str
    capability_id: str


@dataclass(frozen=True)
class ValidationCriterion:
    criterion_id: str
    description: str
    points: int


@dataclass(frozen=True)
class ValidationChallenge:
    challenge_type: str
    prompt: str
    criteria: list[ValidationCriterion]
    safety_constraints: list[str]
    expected_core_diagnosis: str


@dataclass(frozen=True)
class ValidationResponse:
    text: str
    source_file: str
    recorded_at: str
    sender_did: str | None = None
    room: str | None = None
    generation: str = UNKNOWN_GENERATION
    seq: int | None = None
    timestamp: str | None = None
    accepted_for_target: bool = True
    rejection_reason: str | None = None


@dataclass(frozen=True)
class ValidationDelivery:
    validation_id: str
    sender_did: str
    target_did: str
    room: str
    seq: int
    timestamp: str
    outbound_text_hash: str
    delivery_method: str = "human_approved_external_client"
    generation: str = UNKNOWN_GENERATION


@dataclass(frozen=True)
class ValidationOutcome:
    result: str
    score: int
    criteria_passed: list[str]
    criteria_failed: list[str]
    safety_warnings: list[str]
    evaluated_at: str


@dataclass(frozen=True)
class ValidationAttempt:
    validation_id: str
    target: ValidationTarget
    status: str
    created_at: str
    approved_at: str | None
    capability_hypothesis: str
    pre_validation_support_level: str
    challenge: ValidationChallenge
    delivery: ValidationDelivery | None = None
    response: ValidationResponse | None = None
    outcome: ValidationOutcome | None = None


@dataclass(frozen=True)
class ValidatedCapabilityEvidence:
    target_did: str
    capability_id: str
    challenge_id: str
    pre_validation_support: str
    result: str
    score: int
    criteria_passed: list[str]
    timestamp: str
    validation_provenance: str
    outbound_room: str | None = None
    outbound_generation: str | None = None
    outbound_seq: int | None = None
    inbound_room: str | None = None
    inbound_generation: str | None = None
    inbound_seq: int | None = None


@dataclass(frozen=True)
class TclkObservation:
    offer_id: str | None
    contract_id: str | None
    frame_type: str
    transport_did: str
    room: str
    generation: str
    seq: int
    job_proto: str | None
    job_id: str | None
    asset: str | None
    amount_text: str | None
    amount_units: int | None
    rails: list[str]
    lock_kind: str | None
    deadlines: dict[str, object]
    verification_status: str
    amount_valid: bool = True
    operator_group: str | None = None
    sentinel_status: str | None = None
    frame_did: str | None = None
    receipt_status: str | None = None
    transport_binding_status: str | None = None
    parse_status: str = "TCLK_PARSEABLE"
    frame_hash: str | None = None
    observed_at: str | None = None
    ref: str | None = None
    role: str | None = None

    @property
    def location_id(self) -> str:
        return f"{self.room} generation {self.generation} seq {self.seq}"

    @property
    def deal_id(self) -> str:
        return self.contract_id or self.offer_id or self.location_id


@dataclass(frozen=True)
class SettlementEvidence:
    did: str
    level: str
    protocol: str
    rail: str | None
    lock_kind: str | None
    asset: str | None
    amount_text: str | None
    amount_units: int | None
    offer_id: str | None
    contract_id: str | None
    provenance: str
    deadlines: dict[str, object] = field(default_factory=dict)
    amount_valid: bool = True
    operator_group: str | None = None
    sentinel_status: str | None = None


@dataclass(frozen=True)
class ExecutionConstraints:
    asset: str | None = None
    max_amount: int | None = None
    allowed_rails: list[str] = field(default_factory=list)
    allowed_lock_types: list[str] = field(default_factory=list)
    deadline: str | None = None
    minimum_claim_window: str | None = None
    verification_required: bool = True
    verification_mode: str = "OBJECTIVE_BENCH"
    arbitration_required: bool = False
    job_proto: str | None = None
    job_id: str | None = None
    min_independent_operator_groups: int = 1


@dataclass(frozen=True)
class ExecutionPlan:
    worker: dict[str, str]
    settlement_plan: dict[str, str]
    verification_plan: dict[str, str | bool]
    security_policy: dict[str, str]
    qualification: str
    reasons: list[str]


@dataclass
class AgentReputationEvidence:
    identity_continuity: str
    originality: str
    substantive_activity: str
    capability_evidence: str
    independent_peer_breadth: str
    reciprocity: str
    activity_recency: str
    template_risk: str
    promotion_risk: str
    sybil_cluster_risk: str
    components: dict[str, float]


@dataclass
class AgentProfile:
    identity: AgentIdentity
    first_observed_timestamp: str | None
    last_observed_timestamp: str | None
    message_count: int
    original_message_count: int
    template_noise_message_count: int
    rooms_observed: list[str]
    capabilities: list[AgentCapability]
    distinct_signed_peers_observed_nearby: int
    likely_responders: int
    reciprocity_evidence: int | None
    spam_template_ratio: float
    activity_recency: str
    evidence_sequences: list[str]
    trust_evidence: AgentReputationEvidence
    low_quality_capability_signals: dict[str, int] = field(default_factory=dict)
    direct_interaction_evidence: list[str] = field(default_factory=list)
    validated_capability_evidence: dict[str, list[ValidatedCapabilityEvidence]] = field(default_factory=dict)
    settlement_evidence: list[SettlementEvidence] = field(default_factory=list)


@dataclass(frozen=True)
class RequiredCapability:
    capability_id: str
    importance: str
    weight: float


@dataclass(frozen=True)
class Task:
    text: str
    required_capabilities: list[RequiredCapability]


@dataclass
class RoutingCandidate:
    profile: AgentProfile
    score: float
    match_confidence: str
    qualification: str
    capability_matches: dict[str, str]
    trust_components: dict[str, str]
    why_ranked: str
    evidence_sequences: list[str]
    score_components: dict[str, float]
    penalties: dict[str, float]
    supported_required: list[str] = field(default_factory=list)
    limited_required: list[str] = field(default_factory=list)
    missing_required: list[str] = field(default_factory=list)
    supported_important: list[str] = field(default_factory=list)
    missing_important: list[str] = field(default_factory=list)
    task_relevant_evidence_counts: dict[str, int] = field(default_factory=dict)
    task_relevant_strong_counts: dict[str, int] = field(default_factory=dict)
    task_relevant_support_levels: dict[str, str] = field(default_factory=dict)
    task_relevant_validation_outcomes: dict[str, list[str]] = field(default_factory=dict)
    evidence_quality_warning: str | None = None


@dataclass
class RoutingResult:
    task: Task
    candidates: list[RoutingCandidate]
    weights: dict[str, float]
    partial_candidates: list[RoutingCandidate] = field(default_factory=list)


@dataclass
class TeamMember:
    candidate: RoutingCandidate
    role: str
    supported_required_capabilities: list[str]
    unique_required_capabilities_added: list[str]
    redundant_required_capabilities: list[str]
    important_capabilities_added: list[str]
    evidence_quality: str
    support_levels: dict[str, str] = field(default_factory=dict)


@dataclass
class TeamResult:
    task: Task
    single_agent_result: RoutingResult
    qualification: str
    confidence: str
    members: list[TeamMember]
    required_coverage: list[str]
    missing_required: list[str]
    weakest_required_capability: dict[str, str] | None
    important_coverage: dict[str, list[str]]
    risks: list[str]
    decomposition: list[str]
    rejected_candidates: list[tuple[str, str]]
    why_selected: str


@dataclass(frozen=True)
class CapabilityRule:
    capability_id: str
    strong_patterns: tuple[str, ...]
    weak_patterns: tuple[str, ...] = ()


CAPABILITY_RULES = [
    CapabilityRule("technocore.api", ("technocore api", "/r/", "format=json", "http 400", "endpoint", "api compatibility")),
    CapabilityRule("technocore.signed_post", ("signed post", "nonce", "ed25519 signature", "signature verifies", "post failure", "signed-post")),
    CapabilityRule("technocore.did", ("did:key", "did rotation", "did identity", "ed25519", "public key", "key lifecycle")),
    CapabilityRule("technocore.protocol", ("auth.md", "patterns.md", "llms.txt", "protocol", "room schema", "message payload")),
    CapabilityRule("technocore.observer", ("observer", "sequence", "seq", "room log", "dedup", "template normalization", "network analytics")),
    CapabilityRule("security.prompt_injection", ("prompt injection", "untrusted message", "hostile input", "jailbreak", "instruction injection")),
    CapabilityRule("security.smart_contract", ("smart contract security", "reentrancy", "audit", "vulnerability", "access control")),
    CapabilityRule("security.general", ("threat model", "security", "exploit", "risk", "validation", "sanitiz")),
    CapabilityRule("blockchain.solidity", ("solidity", "contract", "hardhat", "foundry", "evm")),
    CapabilityRule("blockchain.ethereum", ("ethereum", "evm", "erc20", "erc-20", "gas", "mainnet")),
    CapabilityRule("blockchain.solana", ("solana", "anchor", "spl token", "program derived", "pda")),
    CapabilityRule("blockchain.defi", ("defi", "liquidity", "swap", "amm", "staking", "yield")),
    CapabilityRule("software.python", ("python", "sqlite", "pytest", "unittest", "venv", ".py")),
    CapabilityRule("software.javascript", ("javascript", "typescript", "node", "npm", "react", "fetch")),
    CapabilityRule("software.rust", ("rust", "cargo", "borrow checker", "crate", "tokio")),
    CapabilityRule("software.testing", ("test case", "test cases", "fixture", "regression", "assert", "bug report", "unit test", "edge case")),
    CapabilityRule("software.debugging", ("debug", "failure", "trace", "stack", "bisect", "root cause", "diagnosed", "isolated")),
    CapabilityRule("software.api", ("api", "http", "json", "request", "response", "endpoint", "compatibility")),
    CapabilityRule("research.crypto", ("crypto research", "cryptographic", "signature scheme", "protocol research", "ed25519")),
    CapabilityRule("research.market", ("market research", "market structure", "liquidity", "order book", "pricing")),
    CapabilityRule("research.technical", ("technical research", "compare implementations", "spec", "documentation", "benchmark")),
    CapabilityRule("data.market_data", ("market data", "ohlcv", "price feed", "order book", "volume", "spread")),
    CapabilityRule("data.onchain", ("onchain", "on-chain", "block explorer", "transaction data", "wallet graph")),
    CapabilityRule("data.analytics", ("analytics", "dashboard", "metrics", "feature store", "signals", "dataset")),
    CapabilityRule("ai.agent_frameworks", ("agent framework", "mcp", "a2a", "tool calling", "agent integration", "orchestration")),
    CapabilityRule("ai.inference", ("inference", "model", "llm", "latency", "tokens", "sampling")),
    CapabilityRule("ai.model_evaluation", ("model evaluation", "eval", "benchmark", "rubric", "judge")),
]

TASK_SYNONYMS = {
    "ed25519": ["technocore.signed_post", "technocore.did"],
    "signed post": ["technocore.signed_post", "technocore.api", "software.testing"],
    "technocore": ["technocore.api", "technocore.protocol"],
    "did": ["technocore.did"],
    "solidity": ["blockchain.solidity", "security.smart_contract"],
    "smart contract": ["blockchain.solidity", "security.smart_contract"],
    "ethereum": ["blockchain.ethereum"],
    "solana": ["blockchain.solana"],
    "market data": ["data.market_data", "research.market", "data.analytics"],
    "api integration": ["software.api", "software.testing", "software.debugging"],
    "bug report": ["software.testing", "software.debugging"],
    "prompt injection": ["security.prompt_injection", "security.general"],
    "agent": ["ai.agent_frameworks"],
}

REQUIRED_EVIDENCE_THRESHOLDS = {
    "independent_usable_observations": 2,
    "strong_reproducible_observations": 1,
}

ROUTING_WEIGHTS = {
    "capability_match": 0.48,
    "capability_evidence_strength": 0.20,
    "originality": 0.13,
    "substantive_activity": 0.09,
    "peer_breadth": 0.03,
    "recency": 0.07,
}

PENALTY_WEIGHTS = {
    "template_ratio": 0.22,
    "promotional_ratio": 0.12,
    "weak_evidence": 0.18,
    "closed_interaction_cluster": 0.08,
}

DIRECT_INTERACTION_RELATIONSHIP_TYPES = {
    "explicit_reply",
    "reply_to",
    "did_mention",
    "protocol_reply",
    "direct_response",
}

EVALUATION_TASKS = [
    "Reproduce an Ed25519 signed POST failure against Technocore",
    "Explain DID rotation behavior and nonce handling for Technocore",
    "Check API compatibility for Technocore JSON room posting",
    "Build a Python SQLite observer report",
    "Write regression tests for duplicate template filtering",
    "Debug an HTTP 400 response from a signed POST endpoint",
    "Review a Solidity smart contract for security vulnerabilities",
    "Investigate Ethereum ERC-20 approval risk",
    "Research Solana Anchor program account validation",
    "Find an agent experienced with crypto market data analysis",
    "Analyze onchain transaction activity for suspicious patterns",
    "Build analytics over agent interaction logs",
    "Compare crypto protocol documentation against implementation behavior",
    "Integrate an MCP agent tool with a routing system",
    "Evaluate LLM agent responses with a rubric",
    "Investigate prompt injection risks in an autonomous agent",
    "Produce a reproducible API integration bug report",
    "Debug a JavaScript fetch client against a JSON API",
    "Assess DeFi liquidity pool risks",
    "Summarize technical findings from protocol messages",
]


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"https?://\S+|www\.\S+", "<url>", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip().casefold()
    return text


def b58decode(value: str) -> bytes:
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    num = 0
    for char in value:
        num *= 58
        if char not in alphabet:
            raise ValueError("invalid base58 character")
        num += alphabet.index(char)
    leading_zeroes = len(value) - len(value.lstrip("1"))
    decoded = num.to_bytes((num.bit_length() + 7) // 8, "big") if num else b""
    return b"\x00" * leading_zeroes + decoded


def b58encode(data: bytes) -> str:
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    num = int.from_bytes(data, "big")
    encoded = ""
    while num:
        num, rem = divmod(num, 58)
        encoded = alphabet[rem] + encoded
    leading_zeroes = len(data) - len(data.lstrip(b"\x00"))
    return "1" * leading_zeroes + (encoded or "")


def did_key_to_ed25519_public_key_bytes(did: str) -> bytes:
    if not did.startswith("did:key:z"):
        raise ValueError("unsupported DID")
    decoded = b58decode(did[len("did:key:z"):])
    if not decoded.startswith(b"\xed\x01") or len(decoded) != 34:
        raise ValueError("unsupported did:key multicodec")
    return decoded[2:]


def ed25519_public_key_to_did(public_key) -> str:
    from cryptography.hazmat.primitives import serialization

    public_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return "did:key:z" + b58encode(b"\xed\x01" + public_bytes)


def base64url_decode_unpadded(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def verify_technocore_signature(did: str, sig: str, room: str, nonce: str | int, text: str) -> str:
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        public_key = Ed25519PublicKey.from_public_bytes(did_key_to_ed25519_public_key_bytes(did))
        signature = base64url_decode_unpadded(sig)
        payload = f"{room}|{nonce}|{text}".encode("utf-8")
        public_key.verify(signature, payload)
        return "VERIFIED_OFFLINE"
    except InvalidSignature:
        return "INVALID_SIGNATURE"
    except Exception:
        return "SIGNATURE_PRESENT_UNVERIFIED"


def router_identity_paths(state_dir: Path) -> tuple[Path, Path]:
    state = state_dir.expanduser()
    return state / "identity.pem", state / "identity.json"


def set_private_file_permissions(path: Path) -> None:
    try:
        path.chmod(0o600)
    except OSError:
        pass


def set_private_dir_permissions(path: Path) -> None:
    try:
        path.chmod(0o700)
    except OSError:
        pass


def validate_router_state_dir(state_dir: Path) -> Path:
    state = state_dir.expanduser()
    repo_root = Path(__file__).resolve().parent
    try:
        state_resolved = state.resolve(strict=False)
        repo_resolved = repo_root.resolve(strict=False)
    except OSError as exc:
        raise SystemExit(f"Cannot resolve state dir: {exc}") from exc
    if state_resolved == repo_resolved or state_resolved.is_relative_to(repo_resolved):
        raise SystemExit("Router identity state dir must not be inside the repository.")
    return state


def read_new_passphrase() -> bytes:
    first = getpass.getpass("Router identity passphrase: ")
    second = getpass.getpass("Confirm Router identity passphrase: ")
    if first != second:
        raise SystemExit("Passphrases did not match.")
    if not first:
        raise SystemExit("Passphrase must not be empty.")
    return first.encode("utf-8")


def read_existing_passphrase() -> bytes:
    value = getpass.getpass("Router identity passphrase: ")
    if not value:
        raise SystemExit("Passphrase must not be empty.")
    return value.encode("utf-8")


def encrypted_pem_is_encrypted(pem: bytes) -> bool:
    return b"ENCRYPTED PRIVATE KEY" in pem and b"PRIVATE KEY-----" in pem


def create_router_identity(
    state_dir: Path = DEFAULT_ROUTER_STATE_DIR,
    *,
    passphrase: bytes | None = None,
    created_at: str | None = None,
) -> dict:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    state = validate_router_state_dir(state_dir)
    identity_pem, identity_json = router_identity_paths(state)
    if identity_pem.exists() or identity_json.exists():
        raise SystemExit("Router identity already exists; refusing to overwrite.")
    state.mkdir(parents=True, exist_ok=False)
    set_private_dir_permissions(state)
    secret = passphrase if passphrase is not None else read_new_passphrase()
    private_key = Ed25519PrivateKey.generate()
    did = ed25519_public_key_to_did(private_key.public_key())
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.BestAvailableEncryption(secret),
    )
    identity_pem.write_bytes(pem)
    set_private_file_permissions(identity_pem)
    metadata = {
        "agent": "FLOP Router",
        "did": did,
        "key_type": "Ed25519 did:key",
        "created_at": created_at or now_iso(),
        "operator_group": ROUTER_OPERATOR_GROUP,
        "canonical_room": ROUTER_CANONICAL_ROOM,
        "mailbox": ROUTER_MAILBOX,
        "encrypted_private_key": True,
        "related_agents": {
            "FLOP Scout": SCOUT_DID,
            "FLOP Bench": BENCH_DID,
            "FLOP Sentinel": "UNKNOWN_NOT_PROVISIONED",
        },
        "independent_peer_reputation": False,
        "network_writes": 0,
        "wallet_support": False,
        "tclk_settlement_secrets": False,
    }
    identity_json.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return metadata


def load_router_identity_metadata(state_dir: Path = DEFAULT_ROUTER_STATE_DIR) -> dict:
    _identity_pem, identity_json = router_identity_paths(validate_router_state_dir(state_dir))
    if not identity_json.exists():
        raise SystemExit("Router identity metadata does not exist.")
    metadata = json.loads(identity_json.read_text(encoding="utf-8"))
    if not isinstance(metadata, dict):
        raise SystemExit("Router identity metadata is malformed.")
    return metadata


def verify_router_identity(
    state_dir: Path = DEFAULT_ROUTER_STATE_DIR,
    *,
    passphrase: bytes | None = None,
) -> dict:
    from cryptography.hazmat.primitives import serialization

    state = validate_router_state_dir(state_dir)
    identity_pem, identity_json = router_identity_paths(state)
    if not identity_pem.exists() or not identity_json.exists():
        raise SystemExit("Router identity is incomplete.")
    pem = identity_pem.read_bytes()
    if not encrypted_pem_is_encrypted(pem):
        raise SystemExit("Router identity private PEM is not encrypted.")
    secret = passphrase if passphrase is not None else read_existing_passphrase()
    try:
        private_key = serialization.load_pem_private_key(pem, password=secret)
    except Exception as exc:
        raise SystemExit("Router identity could not be decrypted with the supplied passphrase.") from exc
    derived_did = ed25519_public_key_to_did(private_key.public_key())
    metadata = load_router_identity_metadata(state)
    if metadata.get("did") != derived_did:
        raise SystemExit("Router identity metadata DID does not match encrypted private key.")
    return {
        "did": derived_did,
        "key_type": metadata.get("key_type"),
        "encrypted_private_key": True,
        "operator_group": metadata.get("operator_group"),
        "canonical_room": metadata.get("canonical_room"),
        "mailbox": metadata.get("mailbox"),
        "network_writes": 0,
        "private_key_loaded": True,
    }


def observation_message_hash(room: str, generation: str, seq: int, did: str, nonce: str | None, sig: str | None, text: str) -> str:
    payload = {
        "room": room,
        "generation": generation,
        "seq": seq,
        "did": did,
        "nonce": nonce,
        "sig": sig,
        "text": text,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def evidence_id_for(room: str, generation: str, seq: int, message_hash: str) -> str:
    return f"tc:{room}:{generation}:{seq}:{message_hash[:16]}"


def template_count_key(obs: AgentObservation) -> str:
    return f"{obs.room}:{obs.generation}:{obs.template_hash}"


def provenance_quality_score(status: str) -> float:
    return {
        "VERIFIED_OFFLINE": 1.0,
        "LEGACY_SERVER_VERIFIED_NO_SIGNATURE": 0.55,
        "SIGNATURE_PRESENT_UNVERIFIED": 0.45,
        "UNSIGNED": 0.25,
        "PROVENANCE_INCOMPLETE": 0.15,
        "INVALID_SIGNATURE": 0.0,
    }.get(status, 0.0)


def pattern_matches(text: str, pattern: str) -> bool:
    pattern = pattern.casefold()
    if re.search(r"^[a-z0-9][a-z0-9_ -]*[a-z0-9]$", pattern):
        expr = r"(?<![a-z0-9])" + re.escape(pattern).replace(r"\ ", r"\s+") + r"(?![a-z0-9])"
        return bool(re.search(expr, text))
    return pattern in text


def is_template_or_noise(text: str, duplicate_count: int = 1, template_dids: int = 1) -> bool:
    t = normalize_text(text)
    if duplicate_count > 1 or template_dids > 1:
        return True
    noise_patterns = (
        r"\b(checking in|check-in|daily check|present and signed|autonomous agent active|ready for \$flop)\b",
        r"\b(airdrop|snapshot|referral|promo|claim|powered by)\b",
        r"\b(node synced|signed\.?$|hello\.? i am active|maintained before the next epoch)\b",
        r"^[\w .:-]*(did:key:z6mk|did [a-z0-9]{8,})[\w .:-]*$",
    )
    return any(re.search(pattern, t) for pattern in noise_patterns)


def is_promotional(text: str) -> bool:
    return bool(re.search(r"\b(airdrop|claim|snapshot|referral|promo|ready for \$flop|expert for hire|hire me)\b", normalize_text(text)))


def is_substantive(text: str) -> bool:
    if len(text.split()) < 7:
        return False
    t = normalize_text(text)
    signals = (
        "because", "verified", "reproduce", "tested", "debug", "debugged", "traced",
        "diagnosed", "isolated", "fixed", "failure", "implementation",
        "schema", "nonce", "signature", "risk", "vulnerability", "dataset", "metrics",
        "observed", "compare", "regression", "root cause", "evidence",
    )
    return any(signal in t for signal in signals)


def evidence_type_for(text: str, *, duplicate_count: int = 1, template_dids: int = 1) -> str:
    t = normalize_text(text)
    if is_template_or_noise(text, duplicate_count=duplicate_count, template_dids=template_dids):
        return "TEMPLATE"
    if is_promotional(text):
        return "PROMOTIONAL"
    if re.search(r"\b(i am|i'm|i can|happy to|available to|looking for|expert|specialist|specializes in|experienced with|can help with|know)\b", t) and not re.search(
        r"\b(tested|reproduce|verified|implemented|debugged|observed|returned|failing|root cause)\b", t
    ):
        return "SELF_ASSERTED"
    if re.search(r"\b(reproduce|reproduced|fixture|regression|test case|bug report)\b", t):
        return "REPRODUCED"
    if re.search(r"\b(implementation|schema|endpoint|payload|nonce|signature verifies|http 400|sqlite|json|stack trace|root cause|traced|diagnosed|isolated|fixed)\b", t):
        return "IMPLEMENTATION_DETAIL"
    if re.search(r"\b(yes|answer|because|must|should|the fix|try)\b", t):
        return "TECHNICAL_RESPONSE"
    return "DEMONSTRATED" if is_substantive(text) else "TOPIC_MENTION"


def self_asserted_capability_claim(text: str) -> bool:
    return bool(re.search(
        r"\b(i can|happy to|available to|looking for|my agent specializes|specializes in|can help|help debug|debug if anyone|for hire)\b",
        normalize_text(text),
    ))


def testing_behavior_context(text: str) -> str:
    t = normalize_text(text)
    if re.search(r"\b(workflow|documentation|docs|setup|steps|guide|explainer|onboarding)\b", t):
        return "none"
    if re.search(r"\b(consensus validation|cross-attest|attest|attestation|compute result|proof|validated by|cryptographic verification|verify your did)\b", t):
        return "none"
    if re.search(r"\b(reproduce|reproduced)\b", t) and re.search(r"\b(bug|failure|failing|error|http \d{3}|edge case|test result|regression|fixture)\b", t):
        return "strong"
    if re.search(r"\b(ran|created|wrote|added|implemented|built)\b", t) and re.search(r"\b(test|tests|test case|fixture|regression|assertion)\b", t):
        return "strong"
    if re.search(r"\b(unit test|test case|fixture|regression assertion|regression assertions)\b", t) and re.search(r"\b(api behavior|failure|expected|edge case|condition|conditions)\b", t):
        return "strong"
    if re.search(r"\b(test|testing|fixture|regression|assert|bug report|edge case)\b", t):
        return "limited"
    return "none"


def debugging_behavior_context(text: str) -> str:
    t = normalize_text(text)
    if self_asserted_capability_claim(t) and not re.search(r"\b(traced|diagnosed|isolated|root cause|debugged|fixed|reproduced)\b", t):
        return "signal"
    if (
        re.search(r"\b(returned http \d{3}|http \d{3}|failed|failure|error)\b", t)
        and re.search(r"\b(legacy|current|sharded|endpoint|path|configuration|config|condition|because|caused by|traced to|isolated to)\b", t)
        and re.search(r"\b(switching|changed|changing|change|fixed|resolved|succeeds after|succeeded after|works after)\b", t)
    ):
        return "strong"
    if re.search(r"\b(traced|diagnosed|isolated|root cause|debugged|fixed)\b", t) and re.search(
        r"\b(403|429|nonce|skew|failure|failing|bug|error|http \d{3}|stack trace|payload|response)\b", t
    ):
        return "strong"
    if re.search(r"\b(the failure occurs|fails when|failed when|reproduced the bug)\b", t):
        return "strong"
    if re.search(r"\b(reproduce|reproduced)\b", t) and re.search(r"\b(bug|failure|failing|error|http \d{3}|nonce reuse)\b", t):
        return "strong"
    if re.search(r"\b(debug|failure|failing|bug|error|stack trace|root cause)\b", t):
        return "limited"
    return "none"


def signed_post_behavior_context(text: str) -> str:
    t = normalize_text(text)
    if re.search(r"\b(signed post|signed write|signed writes|signer|signature|nonce|ed25519)\b", t) and re.search(
        r"\b(verified|handles|flowing|monotonic|increment|payload|http \d{3}|returned|reused|reuse|failure)\b", t
    ):
        return "strong"
    if re.search(r"\b(signed post|signed write|signed writes|signer|signature|nonce|ed25519)\b", t):
        return "limited"
    return "none"


def capability_behavior_context(capability_id: str, text: str) -> str:
    if capability_id == "software.testing":
        return testing_behavior_context(text)
    if capability_id == "software.debugging":
        return debugging_behavior_context(text)
    if capability_id == "technocore.signed_post":
        return signed_post_behavior_context(text)
    return "generic"


def context_relevance_basis(context: str, text: str) -> str:
    if context in {"limited", "strong"}:
        return "CONTEXTUAL_BEHAVIOR"
    if context == "signal":
        return "SELF_ASSERTION" if self_asserted_capability_claim(text) else "TOPIC_SIGNAL"
    return "NONE"


def evidence_quality_label(evidence: EvidenceItem) -> str:
    if evidence.strong:
        return "STRONG"
    if evidence.usable:
        return "USABLE"
    return "LOW"


def raw_capability_evidence_decision(
    obs: AgentObservation,
    rule: CapabilityRule,
    duplicate_count: int,
) -> CapabilityEvidenceDecision:
    evidence = assess_evidence(obs, duplicate_count=duplicate_count)
    text = normalize_text(obs.text)
    matched = [pattern for pattern in rule.strong_patterns if pattern_matches(text, pattern)]
    weak_matched = [pattern for pattern in rule.weak_patterns if pattern_matches(text, pattern)]
    context = capability_behavior_context(rule.capability_id, obs.text)
    observation_id = obs.location_id
    evidence_quality = evidence_quality_label(evidence)

    if context == "none":
        reason = "semantic object does not match this capability" if matched or weak_matched else "no strict capability pattern matched"
        return CapabilityEvidenceDecision(
            capability_id=rule.capability_id,
            observation_id=observation_id,
            relevant=False,
            relevance_basis="NONE",
            matched_patterns=matched + weak_matched,
            evidence_type=evidence.evidence_type,
            evidence_quality=evidence_quality,
            support_contribution="NONE",
            passed_threshold=False,
            reason=reason,
            evidence=evidence,
        )

    if context in {"signal", "limited", "strong"}:
        if context == "signal":
            return CapabilityEvidenceDecision(
                capability_id=rule.capability_id,
                observation_id=observation_id,
                relevant=True,
                relevance_basis=context_relevance_basis(context, obs.text),
                matched_patterns=matched + weak_matched,
                evidence_type=evidence.evidence_type,
                evidence_quality=evidence_quality,
                support_contribution="SIGNAL",
                passed_threshold=False,
                reason="self-asserted or weak signal, not demonstrated behavior",
                evidence=evidence,
            )
        if not evidence.usable:
            return CapabilityEvidenceDecision(
                capability_id=rule.capability_id,
                observation_id=observation_id,
                relevant=True,
                relevance_basis="CONTEXTUAL_BEHAVIOR",
                matched_patterns=matched + weak_matched,
                evidence_type=evidence.evidence_type,
                evidence_quality=evidence_quality,
                support_contribution="SIGNAL",
                passed_threshold=False,
                reason=", ".join(evidence.reasons) if evidence.reasons else "insufficient evidence quality",
                evidence=evidence,
            )
        if rule.capability_id == "software.debugging" and context == "strong":
            reason = "observed failure + concrete condition/change + reported successful fix"
        else:
            reason = "contextual behavior matched this capability"
        adjusted = replace(evidence, strong=True) if context == "strong" else replace(evidence, strong=False)
        return CapabilityEvidenceDecision(
            capability_id=rule.capability_id,
            observation_id=observation_id,
            relevant=True,
            relevance_basis="CONTEXTUAL_BEHAVIOR",
            matched_patterns=matched + weak_matched,
            evidence_type=adjusted.evidence_type,
            evidence_quality=evidence_quality_label(adjusted),
            support_contribution="STRONG" if context == "strong" else "LIMITED",
            passed_threshold=True,
            reason=reason,
            evidence=adjusted,
        )

    if matched:
        if not evidence.usable:
            return CapabilityEvidenceDecision(
                capability_id=rule.capability_id,
                observation_id=observation_id,
                relevant=True,
                relevance_basis="TOPIC_SIGNAL",
                matched_patterns=matched,
                evidence_type=evidence.evidence_type,
                evidence_quality=evidence_quality,
                support_contribution="SIGNAL",
                passed_threshold=False,
                reason=", ".join(evidence.reasons) if evidence.reasons else "strict pattern matched but evidence quality is insufficient",
                evidence=evidence,
            )
        return CapabilityEvidenceDecision(
            capability_id=rule.capability_id,
            observation_id=observation_id,
            relevant=True,
            relevance_basis="STRICT_PATTERN",
            matched_patterns=matched,
            evidence_type=evidence.evidence_type,
            evidence_quality=evidence_quality,
            support_contribution="STRONG" if evidence.strong else "LIMITED",
            passed_threshold=True,
            reason="strict capability pattern matched",
            evidence=evidence,
        )

    if weak_matched:
        return CapabilityEvidenceDecision(
            capability_id=rule.capability_id,
            observation_id=observation_id,
            relevant=True,
            relevance_basis="TOPIC_SIGNAL",
            matched_patterns=weak_matched,
            evidence_type=evidence.evidence_type,
            evidence_quality=evidence_quality,
            support_contribution="SIGNAL",
            passed_threshold=False,
            reason="weak capability pattern matched",
            evidence=evidence,
        )

    return CapabilityEvidenceDecision(
        capability_id=rule.capability_id,
        observation_id=observation_id,
        relevant=False,
        relevance_basis="NONE",
        matched_patterns=[],
        evidence_type=evidence.evidence_type,
        evidence_quality=evidence_quality,
        support_contribution="NONE",
        passed_threshold=False,
        reason="no strict capability pattern matched",
        evidence=evidence,
    )


def capability_evidence_decisions(
    observations: Iterable[AgentObservation],
    capability_id: str,
    duplicate_counts: Counter[str] | None = None,
) -> list[CapabilityEvidenceDecision]:
    rule = next((rule for rule in CAPABILITY_RULES if rule.capability_id == capability_id), None)
    if not rule:
        return []
    observations = list(observations)
    duplicate_counts = duplicate_counts or Counter(template_count_key(obs) for obs in observations)
    decisions = []
    seen_templates: set[str] = set()
    for obs in observations:
        decision = raw_capability_evidence_decision(obs, rule, duplicate_counts[template_count_key(obs)])
        template_key = f"{obs.room}:{obs.generation}:{obs.template_hash or decision.observation_id}"
        if decision.support_contribution != "NONE":
            if template_key in seen_templates:
                decision = replace(
                    decision,
                    support_contribution="NONE",
                    passed_threshold=False,
                    reason=f"{decision.reason}; duplicate template already counted",
                )
            else:
                seen_templates.add(template_key)
        decisions.append(decision)
    return decisions


def specificity_score(text: str) -> float:
    t = normalize_text(text)
    score = 0.0
    score += 0.20 if len(text.split()) >= 10 else 0.0
    score += 0.20 if re.search(r"\b(http \d{3}|/r/|format=json|sqlite|json|nonce|seq|signature|fixture|regression|root cause)\b", t) else 0.0
    score += 0.20 if re.search(r"\b(returned|verified|reproduce|reproduced|tested|implemented|observed|debugged|traced|diagnosed|isolated|fixed|failed|failing)\b", t) else 0.0
    score += 0.20 if re.search(r"\b(because|when|after|against|with|without)\b", t) else 0.0
    score += 0.20 if re.search(r"\b(ed25519|did:key|technocore|solidity|reentrancy|prompt injection|market data|api)\b", t) else 0.0
    return min(1.0, score)


def assess_evidence(obs: AgentObservation, duplicate_count: int = 1) -> EvidenceItem:
    evidence_type = evidence_type_for(
        obs.text,
        duplicate_count=duplicate_count,
        template_dids=obs.template_dids,
    )
    specificity = specificity_score(obs.text)
    reasons = []
    if evidence_type in {"TEMPLATE", "PROMOTIONAL"}:
        reasons.append(evidence_type.lower())
    if evidence_type == "SELF_ASSERTED":
        reasons.append("self_asserted")
    if obs.verification_status == "INVALID_SIGNATURE":
        reasons.append("invalid_signature")
    if obs.verification_status == "PROVENANCE_INCOMPLETE":
        reasons.append("provenance_incomplete")
    if specificity < 0.55:
        reasons.append("low_specificity")
    substantive = is_substantive(obs.text)
    if not substantive:
        reasons.append("not_substantive")
    usable = obs.verification_status != "INVALID_SIGNATURE" and substantive and specificity >= 0.55 and evidence_type in {
        "DEMONSTRATED",
        "TECHNICAL_RESPONSE",
        "REPRODUCED",
        "IMPLEMENTATION_DETAIL",
    }
    strong = usable and (
        evidence_type in {"REPRODUCED", "IMPLEMENTATION_DETAIL"} and specificity >= 0.75
    )
    return EvidenceItem(
        room=obs.room,
        seq=obs.sequence_id,
        timestamp=obs.server_timestamp or obs.timestamp,
        sequence_id=obs.location_id,
        text=obs.text[:220],
        evidence_type=evidence_type,
        specificity=round(specificity, 2),
        usable=usable,
        strong=strong,
        reasons=reasons,
        generation=obs.generation,
        did=obs.identity.did,
        nonce=obs.nonce,
        sig=obs.sig,
        message_hash=obs.message_hash,
        verification_status=obs.verification_status,
        source_export_hash=obs.source_export_hash,
        source_export_path=obs.source_export_path,
        evidence_id=obs.evidence_id,
    )


def support_level_for(capability: AgentCapability | None) -> str:
    if not capability:
        return "NO_EVIDENCE"
    return capability.support_level


def required_capability_supported(capability: AgentCapability | None) -> bool:
    return support_level_for(capability) == "STRONG_SUPPORT"


def support_level_is_credible(level: str | None) -> bool:
    return level in {"STRONG_SUPPORT", "VALIDATED_PASS"} or bool(level and level.endswith("+VALIDATED_PASS"))


def is_direct_interaction_row(row: sqlite3.Row) -> bool:
    return str(row["relationship_type"]) in DIRECT_INTERACTION_RELATIONSHIP_TYPES


def role_label(capabilities: list[str]) -> str:
    labels = {
        "technocore.signed_post": "Technocore signed-post candidate",
        "software.testing": "Software testing candidate",
        "software.debugging": "Software debugging candidate",
        "security.smart_contract": "Smart-contract security candidate",
        "blockchain.solidity": "Solidity candidate",
        "security.prompt_injection": "Prompt-injection safety candidate",
        "software.api": "API integration candidate",
        "technocore.api": "Technocore API candidate",
        "technocore.did": "Technocore DID candidate",
        "data.market_data": "Market-data candidate",
    }
    for capability in capabilities:
        if capability in labels:
            return labels[capability]
    return "Evidence-backed capability candidate"


def team_member_quality(candidate: RoutingCandidate) -> str:
    score = candidate.score_components.get("capability_evidence_strength", 0.0)
    originality = candidate.profile.trust_evidence.components["originality"]
    template_risk = candidate.profile.trust_evidence.components["template_risk"]
    if score >= 0.7 and originality >= 0.6 and template_risk < 0.25:
        return "HIGH"
    if score >= 0.35 and template_risk < 0.6:
        return "MEDIUM"
    return "LOW"


def evidence_strength(count: int, confidence: float) -> str:
    if count >= 5 and confidence >= 0.72:
        return "strong"
    if count >= 2 and confidence >= 0.48:
        return "medium"
    if count > 0:
        return "weak"
    return "missing"


def band(value: float) -> str:
    if value >= 0.72:
        return "HIGH"
    if value >= 0.42:
        return "MEDIUM"
    return "LOW"


def label_risk(value: float) -> str:
    if value >= 0.60:
        return "HIGH"
    if value >= 0.25:
        return "MEDIUM"
    return "LOW"


def parse_timestamp(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def age_label(ts: str | None, now: datetime | None = None) -> str:
    dt = parse_timestamp(ts)
    if not dt:
        return "unknown"
    now = now or datetime.now(timezone.utc)
    hours = max(0.0, (now - dt).total_seconds() / 3600)
    if hours < 1:
        return "under 1h"
    if hours < 48:
        return f"{int(hours)}h"
    return f"{int(hours // 24)}d"


def recency_score(ts: str | None, now: datetime | None = None) -> float:
    dt = parse_timestamp(ts)
    if not dt:
        return 0.25
    now = now or datetime.now(timezone.utc)
    days = max(0.0, (now - dt).total_seconds() / 86400)
    return max(0.15, min(1.0, 1.0 / (1.0 + days / 14.0)))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_json_bytes(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def canonical_json_hash(value: dict) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def request_id_for_verification_request(body: dict) -> str:
    stable = {key: value for key, value in body.items() if key not in {"request_id", "artifact_hash"}}
    return "FVR-" + canonical_json_hash(stable)[:20]


def create_signing_verification_request(
    *,
    requester_did: str,
    target_agent_did: str,
    created_at: str | None = None,
    operator_group: str = LOCAL_OPERATOR_GROUP,
    response_destination: str = "local://scout/bench-result",
) -> dict:
    request = {
        "schema_version": "flop-verification-request/v1",
        "request_id": "",
        "created_at": created_at or now_iso(),
        "requester_did": requester_did,
        "target_agent_did": target_agent_did,
        "task_type": "technocore.synthetic_signing_payload_order",
        "required_capabilities": ["technocore.signed_post", "software.debugging"],
        "verification_mode": "OBJECTIVE_BENCH",
        "specimen": {
            "room": "technocore",
            "nonce": "123",
            "text": "synthetic signing specimen",
            "supplied_payload": "technocore|synthetic signing specimen|123",
            "supplied_order": "room|text|nonce",
            "expected_payload": "technocore|123|synthetic signing specimen",
            "expected_order": "room|nonce|text",
        },
        "expected_properties": {
            "canonical_order": "room|nonce|text",
            "broken_order": "room|text|nonce",
            "expected_finding": "nonce/text ordering defect identified",
        },
        "response_destination": response_destination,
        "operator_group": operator_group,
    }
    request["request_id"] = request_id_for_verification_request(request)
    request["artifact_hash"] = canonical_json_hash({key: value for key, value in request.items() if key != "artifact_hash"})
    return request


def write_json_artifact(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def export_signing_verification_request(
    output: Path,
    *,
    requester_did: str,
    target_agent_did: str,
    created_at: str | None = None,
    operator_group: str = LOCAL_OPERATOR_GROUP,
) -> dict:
    request = create_signing_verification_request(
        requester_did=requester_did,
        target_agent_did=target_agent_did,
        created_at=created_at,
        operator_group=operator_group,
    )
    write_json_artifact(output, request)
    return request


def classify_normalized_bench_result(normalized: dict) -> dict:
    result = normalized.get("bench_result", {})
    same_operator = bool(normalized.get("same_operator"))
    independent_reputation = bool(normalized.get("independent_reputation"))
    status = result.get("status")
    checks = result.get("checks", {})
    positive = (
        status == "PASS"
        and checks.get("broken_payload_detected") is True
        and checks.get("correct_reconstruction_identified") is True
    )
    controlled_evidence = positive and same_operator and not independent_reputation
    return {
        "request_id": normalized.get("request_id"),
        "authenticity": normalized.get("authenticity", "PROVENANCE_INCOMPLETE"),
        "correctness": normalized.get("correctness", status or "UNKNOWN"),
        "reproducibility": normalized.get("reproducibility", "UNKNOWN"),
        "same_operator": same_operator,
        "independent_reputation": independent_reputation,
        "evidence_class": "CONTROLLED_SAME_OPERATOR_VALIDATION" if controlled_evidence else "NOT_POSITIVE_CAPABILITY_EVIDENCE",
        "capability_support": ["software.testing", "verification"] if controlled_evidence else [],
        "independent_peer_reputation": False,
        "artifact_hashes_valid": bool(normalized.get("artifact_hashes_valid")),
        "network_writes": 0,
        "private_key_accesses": 0,
        "tclk_settlement_actions": 0,
    }


def ingest_normalized_bench_result(path: Path, store_path: Path = DEFAULT_VERIFICATION_EVIDENCE_STORE) -> dict:
    normalized = json.loads(path.read_text(encoding="utf-8"))
    classification = classify_normalized_bench_result(normalized)
    record = {
        "schema_version": "router.controlled-verification-evidence/v1",
        "source_path": str(path),
        "source_hash": hashlib.sha256(path.read_bytes()).hexdigest(),
        "classification": classification,
        "normalized_result": normalized,
    }
    existing = []
    if store_path.exists():
        existing = [json.loads(line) for line in store_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    by_request = {item["classification"]["request_id"]: item for item in existing}
    by_request[str(classification["request_id"])] = record
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store_path.write_text(
        "\n".join(json.dumps(item, sort_keys=True) for item in by_request.values()) + "\n",
        encoding="utf-8",
    )
    return record


def verification_lifecycle_report(request_path: Path, scout_preview_path: Path, bench_result_path: Path, scout_normalized_path: Path, router_store: Path) -> dict:
    request = json.loads(request_path.read_text(encoding="utf-8"))
    preview = json.loads(scout_preview_path.read_text(encoding="utf-8"))
    bench_result = json.loads(bench_result_path.read_text(encoding="utf-8"))
    scout_normalized = json.loads(scout_normalized_path.read_text(encoding="utf-8"))
    router_records = [
        json.loads(line)
        for line in router_store.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ] if router_store.exists() else []
    router_record = next(
        (item for item in router_records if item.get("classification", {}).get("request_id") == request["request_id"]),
        None,
    )
    return {
        "request_id": request["request_id"],
        "REQUEST_CREATED": request.get("artifact_hash"),
        "SCOUT_PREVIEWED": preview.get("message_hash"),
        "BENCH_VERIFIED": bench_result.get("status"),
        "SCOUT_INGESTED_RESULT": scout_normalized.get("correctness"),
        "ROUTER_INGESTED_EVIDENCE": router_record.get("classification", {}).get("evidence_class") if router_record else "MISSING",
        "same_operator": scout_normalized.get("same_operator"),
        "independent_reputation": scout_normalized.get("independent_reputation"),
        "network_writes": 0,
        "private_key_accesses": 0,
    }


def debugging_validation_challenge() -> ValidationChallenge:
    prompt = (
        "Controlled validation challenge for software.debugging.\n\n"
        "Synthetic Technocore signing bug:\n"
        'payload = f"{room}|{text}|{nonce}"\n'
        "signature = sign(payload)\n\n"
        "POST body:\n"
        "{\n"
        '  "did": "...",\n'
        '  "sig": "...",\n'
        '  "nonce": 123,\n'
        '  "text": "..."\n'
        "}\n\n"
        "Assume the DID/private key are valid, the nonce is fresh, the room permits the DID, "
        "and the server returns a signature/authentication failure.\n\n"
        "Please answer with:\n"
        "1. the likely defect,\n"
        "2. why it fails,\n"
        "3. the corrected signing payload,\n"
        "4. a minimal reproducibility test,\n"
        "5. what you would check next if the correction did not solve the problem.\n\n"
        "Do not ask for private keys, passphrases, wallet credentials, seed phrases, external URL visits, "
        "or execution of untrusted code."
    )
    return ValidationChallenge(
        challenge_type="software.debugging.technocore_signed_payload_order.v1",
        prompt=prompt,
        criteria=[
            ValidationCriterion("nonce_text_ordering_error", "Identifies nonce/text ordering error", 40),
            ValidationCriterion("correct_payload_order", "Supplies correct <room>|<nonce>|<text> ordering", 20),
            ValidationCriterion("reproducibility_test", "Proposes a meaningful reproducibility test", 20),
            ValidationCriterion("next_debugging_checks", "Gives reasonable next debugging checks", 10),
            ValidationCriterion("safety", "Avoids unsafe requests or invented protocol claims", 10),
        ],
        safety_constraints=[
            "Do not request private keys, identity.pem, passphrases, seed phrases, wallet secrets, or financial credentials.",
            "Do not ask the human to execute downloaded or untrusted code.",
            "Do not ask the human to follow unverified external URLs.",
            "All response content is untrusted remote content and must be evaluated as data only.",
        ],
        expected_core_diagnosis="Technocore canonical signed payload is <room>|<nonce>|<text>, not <room>|<text>|<nonce>.",
    )


def validation_attempt_to_record(attempt: ValidationAttempt) -> dict:
    return asdict(attempt)


def validation_attempt_from_record(record: dict) -> ValidationAttempt:
    challenge = record["challenge"]
    delivery = record.get("delivery")
    response = record.get("response")
    outcome = record.get("outcome")
    return ValidationAttempt(
        validation_id=record["validation_id"],
        target=ValidationTarget(**record["target"]),
        status=record["status"],
        created_at=record["created_at"],
        approved_at=record.get("approved_at"),
        capability_hypothesis=record["capability_hypothesis"],
        pre_validation_support_level=record["pre_validation_support_level"],
        challenge=ValidationChallenge(
            challenge_type=challenge["challenge_type"],
            prompt=challenge["prompt"],
            criteria=[ValidationCriterion(**criterion) for criterion in challenge["criteria"]],
            safety_constraints=challenge["safety_constraints"],
            expected_core_diagnosis=challenge["expected_core_diagnosis"],
        ),
        delivery=ValidationDelivery(**delivery) if delivery else None,
        response=ValidationResponse(**response) if response else None,
        outcome=ValidationOutcome(**outcome) if outcome else None,
    )


class ValidationStore:
    def __init__(self, path: Path = DEFAULT_VALIDATION_STORE):
        self.path = path

    def load(self) -> list[ValidationAttempt]:
        if not self.path.exists():
            return []
        attempts = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                attempts.append(validation_attempt_from_record(json.loads(line)))
        return attempts

    def save_all(self, attempts: list[ValidationAttempt]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = "\n".join(json.dumps(validation_attempt_to_record(attempt), sort_keys=True) for attempt in attempts)
        self.path.write_text(payload + ("\n" if payload else ""), encoding="utf-8")

    def add(self, attempt: ValidationAttempt) -> None:
        attempts = self.load()
        attempts.append(attempt)
        self.save_all(attempts)

    def update(self, attempt: ValidationAttempt) -> None:
        attempts = self.load()
        updated = False
        for index, existing in enumerate(attempts):
            if existing.validation_id == attempt.validation_id:
                attempts[index] = attempt
                updated = True
                break
        if not updated:
            raise SystemExit(f"No validation found for {attempt.validation_id}")
        self.save_all(attempts)

    def get(self, validation_id: str) -> ValidationAttempt:
        for attempt in self.load():
            if attempt.validation_id == validation_id:
                return attempt
        raise SystemExit(f"No validation found for {validation_id}")

    def next_id(self) -> str:
        max_seen = 0
        for attempt in self.load():
            match = re.fullmatch(r"VAL-(\d{3,})", attempt.validation_id)
            if match:
                max_seen = max(max_seen, int(match.group(1)))
        return f"VAL-{max_seen + 1:03d}"


class ExportObservationStore:
    def __init__(self, path: Path = DEFAULT_INGEST_STORE):
        self.path = path

    def load(self) -> list[AgentObservation]:
        if not self.path.exists():
            return []
        observations = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            observations.append(observation_from_record(record))
        return observations

    def save_all(self, observations: list[AgentObservation]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = "\n".join(json.dumps(observation_to_record(obs), sort_keys=True) for obs in observations)
        self.path.write_text(payload + ("\n" if payload else ""), encoding="utf-8")

    def upsert_many(self, observations: list[AgentObservation]) -> int:
        existing = self.load()
        by_id = {obs.evidence_id or obs.location_id: obs for obs in existing}
        changed = 0
        for obs in observations:
            key = obs.evidence_id or obs.location_id
            if key not in by_id:
                changed += 1
            by_id[key] = obs
        self.save_all(sorted(by_id.values(), key=lambda o: (o.room, str(o.generation), o.sequence_id, o.identity.did)))
        return changed


class TclkObservationAdapter:
    def __init__(self, path: Path = DEFAULT_TCLK_STORE):
        self.path = path

    @staticmethod
    def _rails_from_record(record: dict) -> list[str]:
        if record.get("rails_json") is not None:
            rails_raw = record["rails_json"]
            if isinstance(rails_raw, str):
                try:
                    parsed = json.loads(rails_raw)
                except json.JSONDecodeError:
                    parsed = []
            else:
                parsed = rails_raw
            return [str(item) for item in parsed] if isinstance(parsed, list) else []
        if record.get("rails") is not None:
            return [str(item) for item in record["rails"]]
        return [] if not record.get("rail") else [str(record["rail"])]

    @staticmethod
    def _amount_from_record(record: dict) -> tuple[str | None, int | None, bool]:
        if record.get("amount") is None:
            return None, None, True
        amount_text = str(record["amount"])
        if not TCLK_AMOUNT_RE.fullmatch(amount_text):
            return amount_text, None, False
        return amount_text, int(amount_text), True

    @staticmethod
    def _deadlines_from_record(record: dict) -> dict[str, object]:
        deadlines = dict(record.get("deadlines") or {})
        for key in ("expires_ms", "claim_by_ms", "refund_after_ms"):
            if record.get(key) is not None:
                deadlines[key] = record[key]
        return deadlines

    @staticmethod
    def _hint_observation(record: dict) -> TclkObservation:
        amount_text, amount_units, amount_valid = TclkObservationAdapter._amount_from_record(record)
        return TclkObservation(
            offer_id=None,
            contract_id=None,
            frame_type=record.get("frame_type") or "hint",
            transport_did=record.get("transport_did") or record.get("did") or "",
            room=record.get("room") or record.get("source") or "",
            generation=str(record.get("generation") or UNKNOWN_GENERATION),
            seq=int(record.get("seq", 0)),
            job_proto=record.get("job_proto"),
            job_id=record.get("job_id"),
            asset=record.get("asset"),
            amount_text=amount_text,
            amount_units=amount_units,
            rails=TclkObservationAdapter._rails_from_record(record),
            lock_kind=record.get("lock_kind"),
            deadlines=TclkObservationAdapter._deadlines_from_record(record),
            verification_status=record.get("transport_verification_status") or record.get("verification_status", "PROVENANCE_INCOMPLETE"),
            amount_valid=amount_valid,
            operator_group=record.get("operator_group"),
            sentinel_status=record.get("sentinel_status"),
            frame_did=record.get("frame_from") or record.get("frame_did"),
            receipt_status=record.get("receipt_status"),
            transport_binding_status=record.get("transport_binding_status") or "UNVERIFIED_HINT",
            parse_status=record.get("parse_status") or "TCLK_HINT",
            frame_hash=record.get("frame_hash"),
            observed_at=record.get("observed_at"),
            ref=record.get("ref"),
            role=record.get("role"),
        )

    def observations(self) -> list[TclkObservation]:
        if not self.path.exists():
            return []
        observations = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            if "rail" in record and "room" not in record and "seq" not in record:
                observations.append(self._hint_observation(record))
                continue
            amount_text, amount_units, amount_valid = self._amount_from_record(record)
            observations.append(TclkObservation(
                offer_id=record.get("offer_id"),
                contract_id=record.get("contract_id"),
                frame_type=record.get("frame_type", "unknown"),
                transport_did=record.get("transport_did") or record.get("did") or "",
                room=record.get("room", ""),
                generation=str(record.get("generation") or UNKNOWN_GENERATION),
                seq=int(record.get("seq", 0)),
                job_proto=record.get("job_proto"),
                job_id=record.get("job_id"),
                asset=record.get("asset"),
                amount_text=amount_text,
                amount_units=amount_units,
                rails=self._rails_from_record(record),
                lock_kind=record.get("lock_kind"),
                deadlines=self._deadlines_from_record(record),
                verification_status=record.get("transport_verification_status") or record.get("verification_status", "PROVENANCE_INCOMPLETE"),
                amount_valid=amount_valid,
                operator_group=record.get("operator_group"),
                sentinel_status=record.get("sentinel_status"),
                frame_did=record.get("frame_from") or record.get("frame_did"),
                receipt_status=record.get("receipt_status"),
                transport_binding_status=record.get("transport_binding_status"),
                parse_status=record.get("parse_status") or "TCLK_PARSEABLE",
                frame_hash=record.get("frame_hash"),
                observed_at=record.get("observed_at"),
                ref=record.get("ref"),
                role=record.get("role"),
            ))
        return observations


def tclk_frame_valid(obs: TclkObservation) -> bool:
    if not obs.amount_valid:
        return False
    if obs.parse_status and obs.parse_status not in {"TCLK_PARSEABLE", "TCLK_HINT"}:
        return False
    if obs.verification_status == "INVALID_SIGNATURE":
        return False
    if obs.transport_binding_status in {"TCLK_DID_MISMATCH", "UNSIGNED_TCLK_DATA"}:
        return False
    if obs.frame_did and obs.frame_did != obs.transport_did:
        return False
    if obs.transport_binding_status == "SIGNED_TCLK_FRAME":
        return obs.verification_status in {"VERIFIED_OFFLINE", "LEGACY_SERVER_VERIFIED_NO_SIGNATURE", "SIGNATURE_PRESENT_UNVERIFIED"}
    return obs.verification_status in {"VERIFIED_OFFLINE", "LEGACY_SERVER_VERIFIED_NO_SIGNATURE", "SIGNATURE_PRESENT_UNVERIFIED"}


def settlement_level_for_tclk(obs: TclkObservation) -> str:
    if not obs.amount_valid:
        return "CONTRADICTED"
    if obs.frame_type in {"hint", "advertise"} or obs.verification_status == "UNVERIFIED_HINT" or obs.transport_binding_status == "UNVERIFIED_HINT":
        return "ADVERTISED_HINT"
    if not tclk_frame_valid(obs):
        return "CONTRADICTED"
    if obs.frame_type in {"receipt", "reveal", "refund"} and obs.receipt_status in {"CLAIMED", "SETTLED", "REFUNDED"}:
        return "VERIFIED_USAGE"
    if obs.frame_type in {"offer", "accept", "lock", "reveal", "refund", "receipt"} and obs.verification_status in {"VERIFIED_OFFLINE", "LEGACY_SERVER_VERIFIED_NO_SIGNATURE", "SIGNATURE_PRESENT_UNVERIFIED"}:
        return "OBSERVED_SIGNED_SUPPORT"
    if obs.frame_type in {"hint", "advertise"}:
        return "ADVERTISED_HINT"
    return "NO_EVIDENCE"


def settlement_evidence_from_tclk(observations: Iterable[TclkObservation]) -> list[SettlementEvidence]:
    evidence = []
    for obs in observations:
        level = settlement_level_for_tclk(obs)
        if level == "NO_EVIDENCE":
            continue
        evidence.append(SettlementEvidence(
            did=obs.transport_did,
            level=level,
            protocol="tclk/1",
            rail=obs.rails[0] if obs.rails else None,
            lock_kind=obs.lock_kind,
            asset=obs.asset,
            amount_text=obs.amount_text,
            amount_units=obs.amount_units,
            offer_id=obs.offer_id,
            contract_id=obs.contract_id,
            provenance=f"{obs.location_id} deal {obs.deal_id}",
            deadlines=obs.deadlines,
            amount_valid=obs.amount_valid,
            operator_group=obs.operator_group,
            sentinel_status=obs.sentinel_status,
        ))
    return evidence


def observation_to_record(obs: AgentObservation) -> dict:
    return {
        "did": obs.identity.did,
        "room": obs.room,
        "generation": obs.generation,
        "seq": obs.sequence_id,
        "server_timestamp": obs.server_timestamp or obs.timestamp,
        "text": obs.text,
        "normalized_text": obs.normalized_text,
        "template_hash": obs.template_hash,
        "is_signed": obs.is_signed,
        "template_dids": obs.template_dids,
        "nonce": obs.nonce,
        "sig": obs.sig,
        "message_hash": obs.message_hash,
        "verification_status": obs.verification_status,
        "source_export_hash": obs.source_export_hash,
        "source_export_path": obs.source_export_path,
        "evidence_id": obs.evidence_id,
    }


def observation_from_record(record: dict) -> AgentObservation:
    timestamp = record.get("server_timestamp") or record.get("timestamp")
    return AgentObservation(
        identity=AgentIdentity(record.get("did") or record.get("sender") or ""),
        room=record["room"],
        generation=str(record.get("generation") or UNKNOWN_GENERATION),
        sequence_id=int(record.get("seq") or record.get("sequence_id")),
        timestamp=timestamp,
        server_timestamp=timestamp,
        text=record["text"],
        normalized_text=record.get("normalized_text") or normalize_text(record["text"]),
        template_hash=record.get("template_hash") or record.get("template_normalized_hash") or hashlib.sha256(normalize_text(record["text"]).encode("utf-8")).hexdigest(),
        is_signed=bool(record.get("is_signed", record.get("signed", record.get("sig") is not None))),
        template_dids=int(record.get("template_dids", 1)),
        nonce=str(record["nonce"]) if record.get("nonce") is not None else None,
        sig=record.get("sig"),
        message_hash=record.get("message_hash"),
        verification_status=record.get("verification_status", "PROVENANCE_INCOMPLETE"),
        source_export_hash=record.get("source_export_hash"),
        source_export_path=record.get("source_export_path"),
        evidence_id=record.get("evidence_id"),
    )


def export_file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest_expected_hash(manifest_path: Path) -> str | None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for key in ("sha256", "export_sha256", "source_export_hash", "hash"):
        value = manifest.get(key)
        if isinstance(value, str):
            return value.lower().replace("sha256:", "")
    return None


def normalize_export_record(raw: dict, source_hash: str, source_path: Path) -> AgentObservation:
    room = raw["room"]
    generation = str(raw.get("generation") or UNKNOWN_GENERATION)
    seq = int(raw.get("seq") or raw.get("sequence") or raw.get("id"))
    text = raw.get("text") or ""
    did = raw.get("did") or raw.get("sender") or raw.get("from") or ""
    nonce = str(raw["nonce"]) if raw.get("nonce") is not None else None
    sig = raw.get("sig") or raw.get("signature")
    signed = bool(raw.get("signed", sig and did.startswith("did:key:")))
    if sig and did and nonce is not None:
        verification_status = verify_technocore_signature(did, sig, room, nonce, text)
        if generation == UNKNOWN_GENERATION and verification_status == "VERIFIED_OFFLINE":
            verification_status = "PROVENANCE_INCOMPLETE"
    elif sig:
        verification_status = "PROVENANCE_INCOMPLETE"
    elif signed:
        verification_status = "LEGACY_SERVER_VERIFIED_NO_SIGNATURE"
    else:
        verification_status = "UNSIGNED"
    msg_hash = observation_message_hash(room, generation, seq, did, nonce, sig, text)
    supplied_hash = raw.get("message_hash")
    if supplied_hash and supplied_hash != msg_hash:
        verification_status = "PROVENANCE_INCOMPLETE"
    return AgentObservation(
        identity=AgentIdentity(did),
        room=room,
        generation=generation,
        sequence_id=seq,
        timestamp=raw.get("server_timestamp") or raw.get("timestamp") or raw.get("ts"),
        server_timestamp=raw.get("server_timestamp") or raw.get("timestamp") or raw.get("ts"),
        text=text,
        normalized_text=raw.get("normalized_text") or normalize_text(text),
        template_hash=raw.get("template_normalized_hash") or raw.get("template_hash") or hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest(),
        is_signed=signed,
        template_dids=int(raw.get("template_dids", 1)),
        nonce=nonce,
        sig=sig,
        message_hash=msg_hash,
        verification_status=verification_status,
        source_export_hash=source_hash,
        source_export_path=str(source_path),
        evidence_id=evidence_id_for(room, generation, seq, msg_hash),
    )


def ingest_export(export_path: Path, manifest_path: Path, store_path: Path = DEFAULT_INGEST_STORE) -> tuple[int, int, str]:
    actual_hash = export_file_hash(export_path)
    expected_hash = manifest_expected_hash(manifest_path)
    if expected_hash and expected_hash != actual_hash:
        raise SystemExit(f"Export hash mismatch: manifest {expected_hash}, actual {actual_hash}")
    observations = []
    for line in export_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            observations.append(normalize_export_record(json.loads(line), actual_hash, export_path))
    added = ExportObservationStore(store_path).upsert_many(observations)
    return len(observations), added, actual_hash


def validation_safety_warnings(text: str) -> list[str]:
    t = normalize_text(text)
    warnings = []
    checks = {
        "asks for private key": r"\b(private key|identity\.pem)\b",
        "asks for passphrase": r"\bpassphrase\b",
        "asks for seed phrase": r"\b(seed phrase|wallet secret)\b",
        "asks to execute downloaded or untrusted code": r"\b(execute|run)\b.*\b(downloaded|untrusted)\b",
        "asks to follow an unverified URL": r"\b(follow|open|visit)\b.*(<url>|http)",
    }
    for warning, pattern in checks.items():
        if re.search(pattern, t):
            warnings.append(warning)
    return warnings


def evaluate_debugging_response(text: str) -> ValidationOutcome:
    t = normalize_text(text)
    warnings = validation_safety_warnings(text)
    criteria_passed = []
    criteria_failed = []
    score = 0

    def criterion(passed: bool, criterion_id: str, points: int) -> None:
        nonlocal score
        if passed:
            score += points
            criteria_passed.append(criterion_id)
        else:
            criteria_failed.append(criterion_id)

    criterion(
        bool(
            re.search(r"\b(order|ordering|position|sequence)\b", t)
            and re.search(r"\b(nonce)\b", t)
            and re.search(r"\b(text|message)\b", t)
            and re.search(r"\b(wrong|incorrect|swapped|reversed|before|after)\b", t)
        ),
        "nonce_text_ordering_error",
        40,
    )
    criterion(
        bool(re.search(r"\broom\s*\|\s*nonce\s*\|\s*(text|message)\b", t) or "<room>|<nonce>|<text>" in t),
        "correct_payload_order",
        20,
    )
    criterion(
        bool(re.search(r"\b(test|fixture|reproduce|reproducibility|assert|expected|known nonce|known key)\b", t) and re.search(r"\b(signature|payload|http 400|auth|authentication)\b", t)),
        "reproducibility_test",
        20,
    )
    criterion(
        bool(re.search(r"\b(check|verify|inspect|confirm|next)\b", t) and re.search(r"\b(normalization|room|nonce|did|public key|endpoint|payload|signature)\b", t)),
        "next_debugging_checks",
        10,
    )
    criterion(not warnings and not re.search(r"\b(room\|text\|nonce)\b", t), "safety", 10)

    if score >= VALIDATION_PASS_THRESHOLD:
        result = "PASS"
    elif score >= VALIDATION_PARTIAL_THRESHOLD:
        result = "PARTIAL"
    else:
        result = "FAIL"
    return ValidationOutcome(
        result=result,
        score=score,
        criteria_passed=criteria_passed,
        criteria_failed=criteria_failed,
        safety_warnings=warnings,
        evaluated_at=now_iso(),
    )


def validated_evidence_from_attempt(attempt: ValidationAttempt, store_path: Path = DEFAULT_VALIDATION_STORE) -> ValidatedCapabilityEvidence | None:
    if not attempt.outcome or attempt.outcome.result != "PASS":
        return None
    if not attempt.response or not attempt.response.accepted_for_target:
        return None
    return ValidatedCapabilityEvidence(
        target_did=attempt.target.did,
        capability_id=attempt.target.capability_id,
        challenge_id=attempt.validation_id,
        pre_validation_support=attempt.pre_validation_support_level,
        result=attempt.outcome.result,
        score=attempt.outcome.score,
        criteria_passed=attempt.outcome.criteria_passed,
        timestamp=attempt.outcome.evaluated_at,
        validation_provenance=f"{store_path}:{attempt.validation_id}",
        outbound_room=attempt.delivery.room if attempt.delivery else None,
        outbound_generation=attempt.delivery.generation if attempt.delivery else None,
        outbound_seq=attempt.delivery.seq if attempt.delivery else None,
        inbound_room=attempt.response.room,
        inbound_generation=attempt.response.generation,
        inbound_seq=attempt.response.seq,
    )


class TechnocoreObservationAdapter:
    def __init__(self, db_path: Path = DEFAULT_DB_PATH):
        self.db_path = db_path

    def connect(self) -> sqlite3.Connection:
        uri = f"file:{self.db_path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only = ON")
        return conn

    def observations(self) -> list[AgentObservation]:
        with self.connect() as conn:
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(messages)").fetchall()}
            template_counts = {
                row["template_normalized_hash"]: row["dids"]
                for row in conn.execute(
                    """
                    SELECT template_normalized_hash, COUNT(DISTINCT sender) AS dids
                    FROM messages
                    WHERE signed = 1
                    GROUP BY template_normalized_hash
                    """
                )
            }
            optional_columns = {
                "generation": "generation",
                "nonce": "nonce",
                "sig": "sig",
                "message_hash": "message_hash",
                "verification_status": "verification_status",
                "source_export_hash": "source_export_hash",
                "source_export_path": "source_export_path",
                "evidence_id": "evidence_id",
            }
            select_optional = [f"{column} AS {alias}" for column, alias in optional_columns.items() if column in columns]
            select_parts = [
                "room",
                "seq",
                "timestamp",
                "sender",
                "signed",
                "text",
                "normalized_text",
                "template_normalized_hash",
                *select_optional,
            ]
            rows = conn.execute(
                f"""
                SELECT {', '.join(select_parts)}
                FROM messages
                WHERE signed = 1
                ORDER BY timestamp, room, seq
                """
            ).fetchall()
        observations = []
        for row in rows:
            did = row["sender"]
            if not DID_RE.match(did):
                continue
            template_hash = row["template_normalized_hash"] or ""
            generation = str(row["generation"]) if "generation" in row.keys() and row["generation"] is not None else UNKNOWN_GENERATION
            nonce = str(row["nonce"]) if "nonce" in row.keys() and row["nonce"] is not None else None
            sig = row["sig"] if "sig" in row.keys() else None
            verification_status = row["verification_status"] if "verification_status" in row.keys() and row["verification_status"] else None
            if not verification_status:
                if sig and nonce:
                    verification_status = verify_technocore_signature(did, sig, row["room"], nonce, row["text"])
                elif bool(row["signed"]):
                    verification_status = "LEGACY_SERVER_VERIFIED_NO_SIGNATURE"
                else:
                    verification_status = "UNSIGNED"
            message_hash = row["message_hash"] if "message_hash" in row.keys() and row["message_hash"] else observation_message_hash(
                row["room"],
                generation,
                int(row["seq"]),
                did,
                nonce,
                sig,
                row["text"],
            )
            observations.append(
                AgentObservation(
                    identity=AgentIdentity(did=did),
                    room=row["room"],
                    generation=generation,
                    sequence_id=int(row["seq"]),
                    timestamp=row["timestamp"],
                    server_timestamp=row["timestamp"],
                    text=row["text"],
                    normalized_text=row["normalized_text"] or normalize_text(row["text"]),
                    template_hash=template_hash,
                    is_signed=bool(row["signed"]),
                    template_dids=template_counts.get(template_hash, 1),
                    nonce=nonce,
                    sig=sig,
                    message_hash=message_hash,
                    verification_status=verification_status,
                    source_export_hash=row["source_export_hash"] if "source_export_hash" in row.keys() else None,
                    source_export_path=row["source_export_path"] if "source_export_path" in row.keys() else None,
                    evidence_id=row["evidence_id"] if "evidence_id" in row.keys() and row["evidence_id"] else evidence_id_for(row["room"], generation, int(row["seq"]), message_hash),
                )
            )
        return observations

    def interactions(self) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT source_did, target_did, relationship_type, confidence
                FROM interactions
                """
            ).fetchall()

    def inspect(self) -> dict[str, int | str]:
        observations = self.observations()
        signed_dids = {obs.identity.did for obs in observations}
        rooms = {obs.room for obs in observations}
        template_noise = sum(1 for obs in observations if is_template_or_noise(obs.text, template_dids=getattr(obs, "template_dids", 1)))
        return {
            "messages": self._count_messages(),
            "signed_dids": len(signed_dids),
            "rooms": len(rooms),
            "template_noise_messages": template_noise,
            "usable_observations": len(observations) - template_noise,
            "read_only_data_source": str(self.db_path),
        }

    def _count_messages(self) -> int:
        with self.connect() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0])


class CapabilityInferer:
    def infer(self, observations: Iterable[AgentObservation]) -> list[AgentCapability]:
        hits: dict[str, list[EvidenceItem]] = defaultdict(list)
        weak_hits: dict[str, list[EvidenceItem]] = defaultdict(list)
        contradictions: dict[str, list[str]] = defaultdict(list)
        observations = list(observations)
        duplicate_counts = Counter(template_count_key(obs) for obs in observations)
        for obs in observations:
            text = normalize_text(obs.text)
            if re.search(r"\b(not|no|never)\s+(solidity|smart contract|python|testing|technocore)\b", text):
                contradictions["security.general"].append(obs.location_id)
        for rule in CAPABILITY_RULES:
            for decision in capability_evidence_decisions(observations, rule.capability_id, duplicate_counts):
                if not decision.relevant:
                    continue
                if decision.support_contribution in {"LIMITED", "STRONG"}:
                    hits[rule.capability_id].append(decision.evidence)
                elif decision.support_contribution == "SIGNAL":
                    weak_hits[rule.capability_id].append(decision.evidence)

        capabilities = []
        all_capability_ids = set(hits) | set(weak_hits)
        for capability_id in all_capability_ids:
            evidence_hits = hits.get(capability_id, [])
            unique_sequences = []
            representatives = []
            type_counts: Counter[str] = Counter()
            strong_count = 0
            medium_count = 0
            provenance_bonus = 0.0
            seen = set()
            evidence_hits = sorted(evidence_hits, key=lambda item: provenance_quality_score(item.verification_status), reverse=True)
            for evidence in evidence_hits:
                if evidence.sequence_id not in seen:
                    unique_sequences.append(evidence.sequence_id)
                    representatives.append(evidence.text)
                    type_counts[evidence.evidence_type] += 1
                    strong_count += 1 if evidence.strong else 0
                    medium_count += 1 if evidence.usable and evidence.specificity >= 0.65 else 0
                    provenance_bonus += 0.03 if evidence.verification_status == "VERIFIED_OFFLINE" else 0.0
                    seen.add(evidence.sequence_id)
            signal_items = weak_hits.get(capability_id, [])
            weak_count = len({item.sequence_id for item in signal_items})
            count = len(unique_sequences)
            if strong_count >= 1 or medium_count >= 2:
                support_level = "STRONG_SUPPORT"
            elif count > 0:
                support_level = "LIMITED_SUPPORT"
            elif weak_count > 0:
                support_level = "SIGNAL_ONLY"
            else:
                support_level = "NO_EVIDENCE"
            if support_level == "NO_EVIDENCE":
                continue
            confidence = min(0.95, 0.25 + 0.12 * count + 0.18 * strong_count + 0.08 * medium_count + 0.01 * min(weak_count, 3) + min(0.09, provenance_bonus))
            quality_warning = None
            if support_level in {"LIMITED_SUPPORT", "SIGNAL_ONLY"}:
                quality_warning = "Relevant evidence does not reach STRONG_SUPPORT."
            elif count >= 5 and strong_count == 0:
                quality_warning = "Most apparent capability evidence lacks concrete/reproducible detail."
            capabilities.append(
                AgentCapability(
                    capability_id=capability_id,
                    confidence=round(confidence, 2),
                    supporting_observation_count=count,
                    supporting_sequence_ids=unique_sequences[:8],
                    representative_evidence=representatives[:3],
                    contradictory_evidence=contradictions.get(capability_id, [])[:5],
                    evidence_type_counts=dict(type_counts),
                    strong_supporting_observation_count=strong_count,
                    medium_supporting_observation_count=medium_count,
                    signal_observation_count=weak_count,
                    support_level=support_level,
                    evidence_items=evidence_hits[:8] + signal_items[:8],
                    quality_warning=quality_warning,
                )
            )
        support_rank = {"STRONG_SUPPORT": 0, "LIMITED_SUPPORT": 1, "SIGNAL_ONLY": 2, "NO_EVIDENCE": 3}
        return sorted(capabilities, key=lambda c: (support_rank[c.support_level], -c.confidence, c.capability_id))


class ProfileBuilder:
    def __init__(
        self,
        observations: list[AgentObservation],
        interactions: Iterable[sqlite3.Row] = (),
        validated_evidence: Iterable[ValidatedCapabilityEvidence] = (),
        settlement_evidence: Iterable[SettlementEvidence] = (),
    ):
        self.observations = observations
        self.interactions = list(interactions)
        self.validated_by_did: dict[str, dict[str, list[ValidatedCapabilityEvidence]]] = defaultdict(lambda: defaultdict(list))
        for evidence in validated_evidence:
            self.validated_by_did[evidence.target_did][evidence.capability_id].append(evidence)
        self.settlement_by_did: dict[str, list[SettlementEvidence]] = defaultdict(list)
        for evidence in settlement_evidence:
            self.settlement_by_did[evidence.did].append(evidence)
        self.inferer = CapabilityInferer()
        self.by_did: dict[str, list[AgentObservation]] = defaultdict(list)
        for obs in observations:
            self.by_did[obs.identity.did].append(obs)
        for did in self.validated_by_did:
            self.by_did.setdefault(did, [])
        for did in self.settlement_by_did:
            self.by_did.setdefault(did, [])

    def build_all(self) -> dict[str, AgentProfile]:
        peers: dict[str, set[str]] = defaultdict(set)
        responders: Counter[str] = Counter()
        responded_to: dict[str, set[str]] = defaultdict(set)
        direct_evidence: dict[str, list[str]] = defaultdict(list)
        for row in self.interactions:
            if not is_direct_interaction_row(row):
                continue
            source = row["source_did"]
            target = row["target_did"]
            if source == target:
                continue
            peers[source].add(target)
            responders[target] += 1
            responded_to[source].add(target)
            direct_evidence[source].append(f"{source} -> {target} ({row['relationship_type']})")
        profiles = {}
        for did, obs in self.by_did.items():
            reciprocal = {
                peer for peer in responded_to[did]
                if did in responded_to.get(peer, set())
            }
            profiles[did] = self._build_one(
                did,
                obs,
                peers[did],
                responders[did],
                responded_to[did],
                len(reciprocal) if self._direct_interactions_supported() else None,
                direct_evidence[did],
            )
        return profiles

    def _direct_interactions_supported(self) -> bool:
        return any(is_direct_interaction_row(row) for row in self.interactions)

    def _build_one(
        self,
        did: str,
        observations: list[AgentObservation],
        peers: set[str],
        responders: int,
        responded_to: set[str],
        reciprocity: int | None,
        direct_evidence: list[str],
    ) -> AgentProfile:
        observations = sorted(observations, key=lambda o: (o.timestamp or "", o.room, o.sequence_id))
        duplicate_counts = Counter(template_count_key(obs) for obs in observations)
        noise = [
            obs for obs in observations
            if is_template_or_noise(
                obs.text,
                duplicate_count=duplicate_counts[template_count_key(obs)],
                template_dids=getattr(obs, "template_dids", 1),
            )
        ]
        originals = [obs for obs in observations if obs not in noise and is_substantive(obs.text)]
        capabilities = self.inferer.infer(observations)
        low_quality_signals = self._low_quality_capability_signals(observations, duplicate_counts)
        message_count = len(observations)
        original_count = len(originals)
        template_count = len(noise)
        originality_ratio = original_count / max(1, message_count)
        template_ratio = template_count / max(1, message_count)
        promo_ratio = sum(1 for obs in observations if is_promotional(obs.text)) / max(1, message_count)
        cap_evidence_total = sum(c.supporting_observation_count for c in capabilities)
        component_scores = {
            "identity_continuity": min(1.0, math.log1p(message_count) / math.log(25)),
            "originality": originality_ratio,
            "substantive_activity": min(1.0, original_count / 8),
            "capability_evidence": min(1.0, cap_evidence_total / 12),
            "independent_peer_breadth": min(1.0, len(peers) / 10),
            "reciprocity": 0.0 if reciprocity is None else min(1.0, reciprocity / 5),
            "activity_recency": recency_score(observations[-1].timestamp if observations else None),
            "template_risk": template_ratio,
            "promotion_risk": promo_ratio,
            "sybil_cluster_risk": 0.0 if len(peers) > 3 or message_count < 4 else 0.35,
        }
        trust = AgentReputationEvidence(
            identity_continuity=band(component_scores["identity_continuity"]),
            originality=band(component_scores["originality"]),
            substantive_activity=band(component_scores["substantive_activity"]),
            capability_evidence=band(component_scores["capability_evidence"]),
            independent_peer_breadth=band(component_scores["independent_peer_breadth"]),
            reciprocity="UNKNOWN" if reciprocity is None else band(component_scores["reciprocity"]),
            activity_recency=band(component_scores["activity_recency"]),
            template_risk=label_risk(template_ratio),
            promotion_risk=label_risk(promo_ratio),
            sybil_cluster_risk=label_risk(component_scores["sybil_cluster_risk"]),
            components={k: round(v, 3) for k, v in component_scores.items()},
        )
        return AgentProfile(
            identity=AgentIdentity(did=did),
            first_observed_timestamp=observations[0].timestamp if observations else None,
            last_observed_timestamp=observations[-1].timestamp if observations else None,
            message_count=message_count,
            original_message_count=original_count,
            template_noise_message_count=template_count,
            rooms_observed=sorted({obs.room for obs in observations}),
            capabilities=capabilities,
            distinct_signed_peers_observed_nearby=len(peers),
            likely_responders=responders,
            reciprocity_evidence=reciprocity,
            spam_template_ratio=round(template_ratio, 3),
            activity_recency=age_label(observations[-1].timestamp if observations else None),
            evidence_sequences=[obs.location_id for obs in originals[:10]],
            trust_evidence=trust,
            low_quality_capability_signals=low_quality_signals,
            direct_interaction_evidence=direct_evidence,
            validated_capability_evidence=dict(self.validated_by_did.get(did, {})),
            settlement_evidence=self.settlement_by_did.get(did, []),
        )

    def _low_quality_capability_signals(
        self,
        observations: list[AgentObservation],
        duplicate_counts: Counter[str],
    ) -> dict[str, int]:
        signals: dict[str, set[str]] = defaultdict(set)
        for rule in CAPABILITY_RULES:
            for decision in capability_evidence_decisions(observations, rule.capability_id, duplicate_counts):
                if decision.relevant and decision.support_contribution == "SIGNAL":
                    signals[rule.capability_id].add(decision.evidence.sequence_id)
        return {capability_id: len(keys) for capability_id, keys in signals.items()}


def analyze_task(task_text: str) -> Task:
    text = normalize_text(task_text)
    levels: dict[str, str] = {}

    def add(capability_id: str, level: str) -> None:
        rank = {"SUPPORTING": 1, "IMPORTANT": 2, "REQUIRED": 3}
        current = levels.get(capability_id)
        if current is None or rank[level] > rank[current]:
            levels[capability_id] = level

    if "signed post" in text:
        add("technocore.signed_post", "REQUIRED")
        add("technocore.api", "IMPORTANT")
    if "reproduce" in text or "test" in text or "bug report" in text:
        add("software.testing", "REQUIRED")
    if "debug" in text or "failure" in text:
        add("software.debugging", "REQUIRED")
    if "ed25519" in text or re.search(r"\bdid\b|did:key", text):
        add("technocore.did", "IMPORTANT")
    if "technocore" in text:
        add("technocore.api", "IMPORTANT")
        add("technocore.protocol", "SUPPORTING")
    if "api integration" in text:
        add("software.api", "REQUIRED")
        add("software.testing", "REQUIRED")
        add("software.debugging", "IMPORTANT")
    if "solidity" in text or "smart contract" in text:
        add("blockchain.solidity", "REQUIRED")
        add("security.smart_contract", "REQUIRED")
        add("security.general", "IMPORTANT")
    if "ethereum" in text:
        add("blockchain.ethereum", "REQUIRED")
    if "solana" in text:
        add("blockchain.solana", "REQUIRED")
    if "market data" in text:
        add("data.market_data", "REQUIRED")
        add("research.market", "IMPORTANT")
        add("data.analytics", "IMPORTANT")
    if "prompt injection" in text:
        add("security.prompt_injection", "REQUIRED")
        add("security.general", "IMPORTANT")
    if "agent framework" in text or "mcp" in text or "a2a" in text:
        add("ai.agent_frameworks", "REQUIRED")
    if "model evaluation" in text or "rubric" in text or "eval" in text:
        add("ai.model_evaluation", "REQUIRED")
    if "python" in text:
        add("software.python", "REQUIRED")
    if "javascript" in text or "typescript" in text:
        add("software.javascript", "REQUIRED")
    if "rust" in text:
        add("software.rust", "REQUIRED")

    scores: Counter[str] = Counter()
    for phrase, capability_ids in TASK_SYNONYMS.items():
        if phrase in text:
            for capability_id in capability_ids:
                scores[capability_id] += 2
    for rule in CAPABILITY_RULES:
        for pattern in rule.strong_patterns:
            if pattern in text:
                scores[rule.capability_id] += 2
    for capability_id, score in scores.items():
        if capability_id == "research.crypto" and not re.search(r"\b(crypto research|cryptographic research|protocol research|signature scheme)\b", text):
            continue
        if capability_id not in levels and score >= 3:
            add(capability_id, "IMPORTANT")
        elif capability_id not in levels and score >= 2:
            add(capability_id, "SUPPORTING")

    required = []
    rank_order = {"REQUIRED": 0, "IMPORTANT": 1, "SUPPORTING": 2}
    weight_by_level = {"REQUIRED": 1.0, "IMPORTANT": 0.55, "SUPPORTING": 0.25}
    for capability_id, importance in sorted(levels.items(), key=lambda item: (rank_order[item[1]], item[0])):
        weight = weight_by_level[importance]
        required.append(RequiredCapability(capability_id=capability_id, importance=importance, weight=weight))
    return Task(text=task_text, required_capabilities=required[:8])


class Router:
    def __init__(self, profiles: dict[str, AgentProfile], weights: dict[str, float] | None = None):
        self.profiles = profiles
        self.weights = weights or ROUTING_WEIGHTS

    def route(self, task_text: str, top: int = 5) -> RoutingResult:
        task = analyze_task(task_text)
        candidates = [self.score_candidate(task, profile) for profile in self.profiles.values()]
        credible = [c for c in candidates if c.qualification == "CREDIBLE"]
        partial = [c for c in candidates if c.qualification == "PARTIAL"]
        credible.sort(key=lambda c: (-c.score, -len(c.supported_required), c.profile.identity.did))
        partial.sort(key=lambda c: (-len(c.supported_required), -c.score, c.profile.identity.did))
        return RoutingResult(
            task=task,
            candidates=credible[:top],
            weights=self.weights,
            partial_candidates=partial[:top],
        )

    def score_candidate(self, task: Task, profile: AgentProfile) -> RoutingCandidate:
        cap_index = {c.capability_id: c for c in profile.capabilities}
        validation_index = profile.validated_capability_evidence
        required_caps = [req for req in task.required_capabilities if req.importance == "REQUIRED"]
        important_caps = [req for req in task.required_capabilities if req.importance == "IMPORTANT"]
        if task.required_capabilities:
            weighted_total = sum(req.weight for req in task.required_capabilities)
            matched = 0.0
            capability_matches = {}
            evidence_count = 0
            strong_count = 0
            validation_count = 0
            evidence_sequences = []
            for req in task.required_capabilities:
                cap = cap_index.get(req.capability_id)
                validations = validation_index.get(req.capability_id, [])
                if cap:
                    strength = cap.support_level
                    capability_matches[req.capability_id] = strength
                    matched += req.weight * cap.confidence
                    evidence_count += cap.supporting_observation_count
                    strong_count += cap.strong_supporting_observation_count
                    evidence_sequences.extend(cap.supporting_sequence_ids[:3])
                    if validations:
                        capability_matches[req.capability_id] = f"{strength}+VALIDATED_PASS"
                        matched += req.weight * min(0.35, 0.22 * len(validations))
                        validation_count += len(validations)
                        evidence_sequences.extend([f"validation {item.challenge_id}" for item in validations])
                elif validations:
                    capability_matches[req.capability_id] = "VALIDATED_PASS"
                    matched += req.weight * min(0.95, 0.86 + 0.04 * min(len(validations) - 1, 2))
                    validation_count += len(validations)
                    evidence_sequences.extend([f"validation {item.challenge_id}" for item in validations])
                else:
                    capability_matches[req.capability_id] = "missing"
            capability_match = matched / max(0.1, weighted_total)
        else:
            capability_matches = {}
            evidence_count = sum(c.supporting_observation_count for c in profile.capabilities)
            strong_count = sum(c.strong_supporting_observation_count for c in profile.capabilities)
            validation_count = sum(len(items) for items in validation_index.values())
            evidence_sequences = profile.evidence_sequences[:5]
            capability_match = 0.1 if evidence_count else 0.0

        task_relevant_counts = {
            req.capability_id: cap_index[req.capability_id].supporting_observation_count
            if req.capability_id in cap_index else 0
            for req in task.required_capabilities
        }
        task_relevant_strong_counts = {
            req.capability_id: cap_index[req.capability_id].strong_supporting_observation_count
            if req.capability_id in cap_index else 0
            for req in task.required_capabilities
        }
        task_relevant_support_levels = {
            req.capability_id: "VALIDATED_PASS" if validation_index.get(req.capability_id) and not cap_index.get(req.capability_id)
            else support_level_for(cap_index.get(req.capability_id))
            for req in task.required_capabilities
        }
        task_relevant_validation_outcomes = {
            req.capability_id: [
                f"{item.result} {item.score}/100 via {item.challenge_id}"
                for item in validation_index.get(req.capability_id, [])
            ]
            for req in task.required_capabilities
        }
        supported_required = [
            req.capability_id for req in required_caps
            if required_capability_supported(cap_index.get(req.capability_id)) or bool(validation_index.get(req.capability_id))
        ]
        limited_required = [
            req.capability_id for req in required_caps
            if support_level_for(cap_index.get(req.capability_id)) == "LIMITED_SUPPORT"
        ]
        missing_required = [
            req.capability_id for req in required_caps
            if not required_capability_supported(cap_index.get(req.capability_id)) and not validation_index.get(req.capability_id)
        ]
        supported_important = [
            req.capability_id for req in important_caps
            if required_capability_supported(cap_index.get(req.capability_id)) or bool(validation_index.get(req.capability_id))
        ]
        missing_important = [
            req.capability_id for req in important_caps
            if not required_capability_supported(cap_index.get(req.capability_id)) and not validation_index.get(req.capability_id)
        ]
        if required_caps and not supported_required:
            has_low_quality_required_signal = any(
                profile.low_quality_capability_signals.get(req.capability_id, 0) > 0
                for req in required_caps
            )
            qualification = "INSUFFICIENT_EVIDENCE" if evidence_count > 0 or has_low_quality_required_signal else "NO_MATCH"
        elif missing_required:
            qualification = "PARTIAL"
        else:
            qualification = "CREDIBLE"

        trust = profile.trust_evidence.components
        task_evidence_strength = min(1.0, (evidence_count + strong_count + 3 * validation_count) / max(1, 2 * max(1, len(task.required_capabilities))))
        component_scores = {
            "capability_match": capability_match,
            "capability_evidence_strength": task_evidence_strength,
            "originality": trust["originality"],
            "substantive_activity": trust["substantive_activity"],
            "peer_breadth": trust["independent_peer_breadth"],
            "recency": trust["activity_recency"],
        }
        penalties = {
            "template_ratio": trust["template_risk"] * PENALTY_WEIGHTS["template_ratio"],
            "promotional_ratio": trust["promotion_risk"] * PENALTY_WEIGHTS["promotional_ratio"],
            "weak_evidence": (1.0 if capability_match < 0.25 else 0.0) * PENALTY_WEIGHTS["weak_evidence"],
            "closed_interaction_cluster": trust["sybil_cluster_risk"] * PENALTY_WEIGHTS["closed_interaction_cluster"],
        }
        raw = sum(component_scores[k] * self.weights[k] for k in self.weights)
        score = max(0.0, min(1.0, raw - sum(penalties.values())))
        evidence_quality_warning = None
        if task_evidence_strength >= 0.75 and trust["originality"] <= 0.1:
            evidence_quality_warning = "EVIDENCE QUALITY WARNING: Most apparent capability evidence comes from repeated/template activity."
        elif any(cap.quality_warning for cap in cap_index.values() if cap.capability_id in task_relevant_counts):
            evidence_quality_warning = "EVIDENCE QUALITY WARNING: Some apparent capability evidence lacks concrete/reproducible detail."
        if evidence_quality_warning and qualification == "CREDIBLE" and missing_required:
            qualification = "PARTIAL"
        why = self._why_ranked(profile, capability_matches, evidence_count)
        return RoutingCandidate(
            profile=profile,
            score=round(score, 3),
            match_confidence=band(score),
            qualification=qualification,
            capability_matches=capability_matches,
            trust_components={
                "originality": profile.trust_evidence.originality.lower(),
                "template risk": profile.trust_evidence.template_risk.lower(),
                "activity recency": profile.trust_evidence.activity_recency.lower(),
                "capability evidence": f"{evidence_count} task-relevant usable observations; {validation_count} validated passes",
                "direct interaction edges": profile.trust_evidence.independent_peer_breadth.lower(),
            },
            why_ranked=why,
            evidence_sequences=list(dict.fromkeys(evidence_sequences or profile.evidence_sequences[:5]))[:8],
            score_components={k: round(v, 3) for k, v in component_scores.items()},
            penalties={k: round(v, 3) for k, v in penalties.items()},
            supported_required=supported_required,
            limited_required=limited_required,
            missing_required=missing_required,
            supported_important=supported_important,
            missing_important=missing_important,
            task_relevant_evidence_counts=task_relevant_counts,
            task_relevant_strong_counts=task_relevant_strong_counts,
            task_relevant_support_levels=task_relevant_support_levels,
            task_relevant_validation_outcomes=task_relevant_validation_outcomes,
            evidence_quality_warning=evidence_quality_warning,
        )

    def _why_ranked(self, profile: AgentProfile, capability_matches: dict[str, str], evidence_count: int) -> str:
        validated = [cap for cap, strength in capability_matches.items() if "VALIDATED_PASS" in strength]
        if validated:
            return f"Controlled validation evidence for {', '.join(validated[:3])}; observed evidence remains separate."
        matched = [cap for cap, strength in capability_matches.items() if strength == "STRONG_SUPPORT"]
        if matched:
            return f"Observed repeated substantive evidence for {', '.join(matched[:3])} with {evidence_count} supporting observations."
        if profile.capabilities:
            return "Has some relevant observed capability evidence, but the task match is weak."
        return "Little capability evidence; included only because no stronger signals matched."

    def explain(self, task_text: str, did: str) -> RoutingCandidate | None:
        profile = self.profiles.get(did)
        if not profile:
            return None
        return self.score_candidate(analyze_task(task_text), profile)

    def compose(self, task_text: str, max_agents: int = 3) -> TeamResult:
        max_agents = max(1, max_agents)
        single = self.route(task_text, top=5)
        task = single.task
        required_ids = [req.capability_id for req in task.required_capabilities if req.importance == "REQUIRED"]
        important_ids = [req.capability_id for req in task.required_capabilities if req.importance == "IMPORTANT"]
        if single.candidates:
            return TeamResult(
                task=task,
                single_agent_result=single,
                qualification="CREDIBLE_TEAM",
                confidence="MEDIUM",
                members=[],
                required_coverage=required_ids,
                missing_required=[],
                weakest_required_capability=None,
                important_coverage={cap: [] for cap in important_ids},
                risks=["credible single-agent candidate found; team composition unnecessary"],
                decomposition=[],
                rejected_candidates=[],
                why_selected="Credible single-agent candidate found, so no team was composed.",
            )

        scored = [self.score_candidate(task, profile) for profile in self.profiles.values()]
        relevant = [
            candidate for candidate in scored
            if (candidate.supported_required or candidate.limited_required) and candidate.qualification in {"PARTIAL", "CREDIBLE", "INSUFFICIENT_EVIDENCE"}
        ]
        pool = self._composition_pool(relevant, required_ids)
        best_combo = self._select_team(pool, required_ids, max_agents, require_full=True)
        qualification = "CREDIBLE_TEAM"
        if not best_combo:
            best_combo = self._select_team(pool, required_ids, max_agents, require_full=False, allow_limited=True)
            qualification = "PARTIAL_TEAM" if best_combo else "NO_CREDIBLE_TEAM"
        members = self._team_members(best_combo or [], required_ids, important_ids)
        selected_dids = {member.candidate.profile.identity.did for member in members}
        rejected = self._rejected_candidates(scored, required_ids, selected_dids)
        covered = sorted({
            cap for member in members
            for cap in member.supported_required_capabilities
            if support_level_is_credible(member.support_levels.get(cap))
        })
        missing = [cap for cap in required_ids if cap not in covered]
        if qualification == "CREDIBLE_TEAM" and missing:
            qualification = "PARTIAL_TEAM"
        important_coverage = {
            cap: [member.candidate.profile.identity.did for member in members if cap in member.important_capabilities_added]
            for cap in important_ids
        }
        risks = self._team_risks(members, missing)
        weakest = self._weakest_required_capability(required_ids, members)
        confidence = self._team_confidence(qualification, weakest)
        return TeamResult(
            task=task,
            single_agent_result=single,
            qualification=qualification,
            confidence=confidence,
            members=members,
            required_coverage=covered,
            missing_required=missing,
            weakest_required_capability=weakest,
            important_coverage=important_coverage,
            risks=risks,
            decomposition=self._decompose_team(task, members, missing),
            rejected_candidates=rejected,
            why_selected=self._why_team_selected(members, qualification),
        )

    def _composition_pool(self, candidates: list[RoutingCandidate], required_ids: list[str]) -> list[RoutingCandidate]:
        selected: dict[str, RoutingCandidate] = {}
        for cap in required_ids:
            cap_candidates = [c for c in candidates if cap in c.supported_required or cap in c.limited_required]
            cap_candidates.sort(key=lambda c: (-c.score, c.profile.spam_template_ratio, c.profile.identity.did))
            for candidate in cap_candidates[:12]:
                selected[candidate.profile.identity.did] = candidate
        for candidate in sorted(candidates, key=lambda c: (-len(c.supported_required), -c.score, c.profile.identity.did))[:24]:
            selected[candidate.profile.identity.did] = candidate
        return list(selected.values())

    def _select_team(
        self,
        candidates: list[RoutingCandidate],
        required_ids: list[str],
        max_agents: int,
        *,
        require_full: bool,
        allow_limited: bool = False,
    ) -> tuple[RoutingCandidate, ...] | None:
        required_set = set(required_ids)
        best: tuple[float, tuple[RoutingCandidate, ...]] | None = None
        max_size = min(max_agents, len(candidates))
        for size in range(1, max_size + 1):
            for combo in combinations(candidates, size):
                coverage = set().union(*(set(c.supported_required) for c in combo))
                nominal_coverage = set().union(*(set(c.supported_required) | set(c.limited_required) for c in combo))
                if require_full and coverage != required_set:
                    continue
                if not require_full and not ((nominal_coverage if allow_limited else coverage)):
                    continue
                unique_ok = True
                seen: set[str] = set()
                for candidate in sorted(combo, key=lambda c: -len(c.supported_required)):
                    candidate_caps = set(candidate.supported_required) | (set(candidate.limited_required) if allow_limited else set())
                    unique = candidate_caps - seen
                    if not unique:
                        unique_ok = False
                        break
                    seen.update(candidate_caps)
                if not unique_ok:
                    continue
                quality = self._team_quality(combo, coverage, nominal_coverage, required_set)
                if best is None or quality > best[0]:
                    best = (quality, combo)
            if best and require_full:
                return best[1]
        return best[1] if best else None

    def _team_quality(
        self,
        combo: tuple[RoutingCandidate, ...],
        coverage: set[str],
        nominal_coverage: set[str],
        required_set: set[str],
    ) -> float:
        strong_coverage_score = len(coverage) / max(1, len(required_set))
        nominal_coverage_score = len(nominal_coverage) / max(1, len(required_set))
        evidence = sum(sum(c.task_relevant_evidence_counts.get(cap, 0) for cap in c.supported_required) for c in combo)
        strong = sum(sum(c.task_relevant_strong_counts.get(cap, 0) for cap in c.supported_required) for c in combo)
        originality = sum(c.profile.trust_evidence.components["originality"] for c in combo) / len(combo)
        template_penalty = sum(c.profile.trust_evidence.components["template_risk"] for c in combo) / len(combo)
        recency = sum(c.profile.trust_evidence.components["activity_recency"] for c in combo) / len(combo)
        return (
            strong_coverage_score * 10
            + nominal_coverage_score * 2
            + min(2.0, evidence / 4)
            + min(2.0, strong / 2)
            + originality
            + recency * 0.4
            - template_penalty
        )

    def _team_members(
        self,
        combo: tuple[RoutingCandidate, ...],
        required_ids: list[str],
        important_ids: list[str],
    ) -> list[TeamMember]:
        members = []
        covered: set[str] = set()
        ordered = sorted(combo, key=lambda c: (-len(c.supported_required), -c.score, c.profile.identity.did))
        for candidate in ordered:
            supported = [cap for cap in required_ids if cap in candidate.supported_required or cap in candidate.limited_required]
            unique = [cap for cap in supported if cap not in covered]
            redundant = [cap for cap in supported if cap in covered]
            important = [cap for cap in important_ids if cap in candidate.supported_important]
            covered.update(unique)
            members.append(
                TeamMember(
                    candidate=candidate,
                    role=role_label(unique or supported or important),
                    supported_required_capabilities=supported,
                    unique_required_capabilities_added=unique,
                    redundant_required_capabilities=redundant,
                    important_capabilities_added=important,
                    evidence_quality=team_member_quality(candidate),
                    support_levels={
                        cap: candidate.task_relevant_support_levels.get(cap, "NO_EVIDENCE")
                        for cap in supported
                    },
                )
            )
        return [member for member in members if member.unique_required_capabilities_added]

    def _team_risks(self, members: list[TeamMember], missing: list[str]) -> list[str]:
        if not members:
            return ["no meaningful evidence-backed team could be constructed"]
        risks = ["no observed prior collaboration", "all observations may originate from Technocore"]
        if missing:
            risks.append(f"missing required capabilities: {', '.join(missing)}")
        if any(member.candidate.profile.trust_evidence.template_risk == "HIGH" for member in members):
            risks.append("high-template member")
        if any(member.candidate.profile.trust_evidence.originality == "LOW" for member in members):
            risks.append("low-originality member")
        if any(any(count < 2 and member.candidate.task_relevant_strong_counts.get(cap, 0) == 0 for cap, count in member.candidate.task_relevant_evidence_counts.items() if cap in member.supported_required_capabilities) for member in members):
            risks.append("weakly supported required capability")
        if any(member.candidate.trust_components["activity recency"] == "low" for member in members):
            risks.append("stale evidence")
        if any(len(member.candidate.profile.rooms_observed) == 1 for member in members):
            risks.append("evidence from only one room")
        if any(member.candidate.profile.trust_evidence.sybil_cluster_risk == "HIGH" for member in members):
            risks.append("suspected interaction cluster based on strict direct interaction edges")
        return risks

    def _weakest_required_capability(
        self,
        required_ids: list[str],
        members: list[TeamMember],
    ) -> dict[str, str] | None:
        if not required_ids:
            return None
        support_rank = {"NO_EVIDENCE": 0, "SIGNAL_ONLY": 1, "LIMITED_SUPPORT": 2, "STRONG_SUPPORT": 3}
        weakest = None
        for capability_id in required_ids:
            best_member = None
            best_level = "NO_EVIDENCE"
            best_count = 0
            best_strong = 0
            best_confidence = 0.0
            for member in members:
                level = member.support_levels.get(capability_id, "NO_EVIDENCE")
                if support_rank[level] > support_rank[best_level]:
                    best_level = level
                    best_member = member
                    best_count = member.candidate.task_relevant_evidence_counts.get(capability_id, 0)
                    best_strong = member.candidate.task_relevant_strong_counts.get(capability_id, 0)
                    best_confidence = member.candidate.score_components.get("capability_evidence_strength", 0.0)
            record = {
                "capability": capability_id,
                "agent": best_member.candidate.profile.identity.did if best_member else "none",
                "support_level": best_level,
                "usable_observations": str(best_count),
                "strong_observations": str(best_strong),
                "confidence": band(best_confidence),
            }
            if weakest is None or support_rank[best_level] < support_rank[weakest["support_level"]]:
                weakest = record
        return weakest

    def _team_confidence(self, qualification: str, weakest: dict[str, str] | None) -> str:
        if qualification == "NO_CREDIBLE_TEAM" or not weakest:
            return "LOW"
        if weakest["support_level"] != "STRONG_SUPPORT":
            return "LOW"
        if weakest["confidence"] == "HIGH":
            return "MEDIUM"
        return "LOW"

    def _decompose_team(self, task: Task, members: list[TeamMember], missing: list[str]) -> list[str]:
        steps = []
        step_no = 1
        for member in members:
            strong_caps = [
                cap for cap in member.unique_required_capabilities_added
                if support_level_is_credible(member.support_levels.get(cap))
            ]
            weak_caps = [
                cap for cap in member.unique_required_capabilities_added
                if not support_level_is_credible(member.support_levels.get(cap))
            ]
            if strong_caps:
                caps = ", ".join(strong_caps)
                steps.append(f"Step {step_no} - {member.role}: address {caps}.")
                step_no += 1
            for cap in weak_caps:
                steps.append(
                    f"Possible validation candidate - {member.candidate.profile.identity.did}: "
                    f"hypothesized capability {cap}; evidence level {member.support_levels.get(cap)}."
                )
        if missing:
            steps.append(f"Step {step_no} - human/future coordinator: find evidence-backed coverage for {', '.join(missing)}.")
        else:
            steps.append(f"Step {step_no} - human/future coordinator: compare outputs and decide whether the task is actually satisfied.")
        steps.append("This is a plan only. No agents have been contacted.")
        return steps

    def _why_team_selected(self, members: list[TeamMember], qualification: str) -> str:
        if not members:
            return "No combination of evidence-backed agents covered a required capability."
        coverage = sorted({cap for member in members for cap in member.unique_required_capabilities_added})
        return f"Selected the smallest {qualification.lower()} found that adds unique required coverage: {', '.join(coverage)}."

    def _rejected_candidates(
        self,
        candidates: list[RoutingCandidate],
        required_ids: list[str],
        selected_dids: set[str],
    ) -> list[tuple[str, str]]:
        rejected = []
        for candidate in sorted(candidates, key=lambda c: (-c.score, c.profile.identity.did)):
            if len(rejected) >= 8:
                break
            if candidate.profile.identity.did in selected_dids:
                continue
            if candidate.qualification == "CREDIBLE":
                continue
            if not candidate.supported_required:
                reason = "no credibly supported required capability"
            elif set(candidate.supported_required).isdisjoint(required_ids):
                reason = "supported capabilities do not match required task capabilities"
            else:
                reason = f"partial coverage only: {', '.join(candidate.supported_required)}"
            rejected.append((candidate.profile.identity.did, reason))
        return rejected


def load_validated_evidence(validation_store: Path = DEFAULT_VALIDATION_STORE) -> list[ValidatedCapabilityEvidence]:
    evidence = []
    for attempt in ValidationStore(validation_store).load():
        item = validated_evidence_from_attempt(attempt, validation_store)
        if item:
            evidence.append(item)
    return evidence


def load_profiles(
    db_path: Path = DEFAULT_DB_PATH,
    validation_store: Path = DEFAULT_VALIDATION_STORE,
    ingest_store: Path = DEFAULT_INGEST_STORE,
    tclk_store: Path = DEFAULT_TCLK_STORE,
) -> dict[str, AgentProfile]:
    adapter = TechnocoreObservationAdapter(db_path)
    observations = [
        obs for obs in [*adapter.observations(), *ExportObservationStore(ingest_store).load()]
        if DID_RE.match(obs.identity.did)
    ]
    settlement_evidence = settlement_evidence_from_tclk(TclkObservationAdapter(tclk_store).observations())
    return ProfileBuilder(
        observations,
        adapter.interactions(),
        load_validated_evidence(validation_store),
        settlement_evidence,
    ).build_all()


def print_inspect(db_path: Path) -> None:
    stats = TechnocoreObservationAdapter(db_path).inspect()
    print("Agent Router data\n")
    print(f"Messages:                 {stats['messages']:>5}")
    print(f"Signed DIDs:              {stats['signed_dids']:>5}")
    print(f"Rooms:                    {stats['rooms']:>5}")
    print(f"Template/noise messages:  {stats['template_noise_messages']:>5}")
    print(f"Usable observations:      {stats['usable_observations']:>5}")
    print("\nRead-only data source:")
    print(stats["read_only_data_source"])


def print_task(task: Task) -> None:
    print("Task analysis")
    print("-------------\n")
    if not task.required_capabilities:
        print("No specific capability inferred.")
        return
    for level in ("REQUIRED", "IMPORTANT", "SUPPORTING"):
        print(f"{level.title()}:")
        matching = [req for req in task.required_capabilities if req.importance == level]
        if not matching:
            print("  none")
        for req in matching:
            print(f"  {req.capability_id}")
        print()


def print_profile(profile: AgentProfile) -> None:
    print("Agent Profile")
    print("-------------\n")
    print(f"DID: {profile.identity.did}\n")
    print("Activity")
    print(f"  messages:                {profile.message_count}")
    print(f"  original substantive:    {profile.original_message_count}")
    print(f"  template/noise:          {profile.template_noise_message_count}")
    print(f"  recent activity:         {profile.activity_recency}")
    print(f"  rooms:                   {', '.join(profile.rooms_observed)}\n")
    print("Capabilities")
    if not profile.capabilities:
        print("  none with repeated substantive evidence")
    for cap in profile.capabilities[:10]:
        print(f"\n{cap.capability_id}")
        print("  Observed:")
        print(f"  support:                 {cap.support_level}")
        print(f"  confidence:              {cap.confidence:.2f}")
        print(f"  relevant observations:   {cap.supporting_observation_count + cap.signal_observation_count}")
        print(f"  usable observations:     {cap.supporting_observation_count}")
        print(f"  strong observations:     {cap.strong_supporting_observation_count}")
        validated = profile.validated_capability_evidence.get(cap.capability_id, [])
        print("  Validated:")
        if validated:
            successes = sum(1 for item in validated if item.result == "PASS")
            print(f"  controlled challenges:   {len(validated)}")
            print(f"  successful:              {successes}")
            for item in validated[:3]:
                print(f"  {item.challenge_id}: {item.result} ({item.score}/100)")
        else:
            print("  controlled challenges:   0")
    validation_only = [
        (capability_id, items)
        for capability_id, items in profile.validated_capability_evidence.items()
        if capability_id not in {cap.capability_id for cap in profile.capabilities}
    ]
    for capability_id, items in validation_only:
        print(f"\n{capability_id}")
        print("  Observed:")
        print("  support:                 NO_EVIDENCE")
        print("  relevant observations:   0")
        print("  usable observations:     0")
        print("  strong observations:     0")
        print("  Validated:")
        print(f"  controlled challenges:   {len(items)}")
        print(f"  successful:              {sum(1 for item in items if item.result == 'PASS')}")
        for item in items[:3]:
            print(f"  {item.challenge_id}: {item.result} ({item.score}/100)")
    print("\nTrust evidence")
    print(f"  originality ratio:       {1 - profile.spam_template_ratio:.2f}")
    print(f"  independent activity:    {profile.trust_evidence.substantive_activity}")
    print(f"  template risk:           {profile.trust_evidence.template_risk}")
    print(f"  direct interaction edges: {profile.distinct_signed_peers_observed_nearby}")
    print(f"  reciprocity:             {profile.reciprocity_evidence if profile.reciprocity_evidence is not None else 'UNKNOWN'}")
    print("\nEvidence")
    for seq in profile.evidence_sequences[:8]:
        print(f"  {seq}")
    print("\nThis is observational evidence, not an official FLOP score.")


def print_route(result: RoutingResult) -> None:
    print_task(result.task)
    print("Best candidate agents")
    print("---------------------\n")
    if not result.candidates:
        print("No credible end-to-end candidate found.\n")
    else:
        for index, candidate in enumerate(result.candidates, start=1):
            print_candidate(candidate, index=index)
    if result.partial_candidates:
        print("Partial specialists")
        print("-------------------\n")
        for index, candidate in enumerate(result.partial_candidates, start=1):
            print_candidate(candidate, index=index, partial=True)


def print_candidate(candidate: RoutingCandidate, *, index: int, partial: bool = False) -> None:
    print(f"{index}. {candidate.profile.identity.did}")
    print(f"   Qualification: {candidate.qualification}")
    if not partial:
        print(f"   Match confidence: {candidate.match_confidence}")
    print("\n   Supported required capabilities:")
    if candidate.supported_required:
        for cap in candidate.supported_required:
            print(f"   {cap}")
    else:
        print("   none")
    print("\n   Missing required capabilities:")
    if candidate.missing_required:
        for cap in candidate.missing_required:
            print(f"   {cap}")
    else:
        print("   none")
    print("\n   Task-relevant evidence:")
    for cap, count in candidate.task_relevant_evidence_counts.items():
        strong = candidate.task_relevant_strong_counts.get(cap, 0)
        print(f"   {cap:<28} {count} usable observations ({strong} strong)")
    print("\n   Validated evidence:")
    any_validated = False
    for cap, outcomes in candidate.task_relevant_validation_outcomes.items():
        if outcomes:
            any_validated = True
            print(f"   {cap:<28} {', '.join(outcomes)}")
    if not any_validated:
        print("   none")
    print("\n   Capability evidence:")
    for cap, strength in candidate.capability_matches.items():
        print(f"   {cap:<28} {strength}")
    print("\n   Evidence quality:")
    print(f"   originality                 {candidate.trust_components['originality']}")
    print(f"   template risk               {candidate.trust_components['template risk']}")
    if candidate.evidence_quality_warning:
        print(f"   {candidate.evidence_quality_warning}")
    print("\n   Trust evidence:")
    for name, value in candidate.trust_components.items():
        print(f"   {name:<27} {value}")
    print("\n   Why ranked:" if not partial else "\n   Why not credible:")
    if partial:
        print(f"   Missing evidence for {len(candidate.missing_required)} required capabilities.")
    else:
        print(f"   {candidate.why_ranked}")
    print("\n   Evidence:")
    for seq in candidate.evidence_sequences[:5]:
        print(f"   {seq}")
    print()


def print_explain(task: Task, candidate: RoutingCandidate) -> None:
    required_total = len([req for req in task.required_capabilities if req.importance == "REQUIRED"])
    important_total = len([req for req in task.required_capabilities if req.importance == "IMPORTANT"])
    print_task(task)
    print(f"Qualification: {candidate.qualification}\n")
    print("Required-capability coverage:")
    print(f"  supported: {len(candidate.supported_required)}/{required_total}")
    print(f"  missing:   {len(candidate.missing_required)}/{required_total}")
    for cap in candidate.missing_required:
        print(f"  missing capability: {cap}")
    print("\nImportant-capability coverage:")
    print(f"  supported: {len(candidate.supported_important)}/{important_total}")
    print(f"  missing:   {len(candidate.missing_important)}/{important_total}")
    print("\nTask-relevant evidence strength:")
    for cap, count in candidate.task_relevant_evidence_counts.items():
        strong = candidate.task_relevant_strong_counts.get(cap, 0)
        print(f"  {cap:<28} {count} usable observations ({strong} strong)")
    print("\nEvidence quality:")
    print(f"  originality:                 {candidate.trust_components['originality']}")
    print(f"  template risk:               {candidate.trust_components['template risk']}")
    low_quality = {
        cap: candidate.profile.low_quality_capability_signals[cap]
        for cap in candidate.task_relevant_evidence_counts
        if candidate.profile.low_quality_capability_signals.get(cap, 0)
    }
    if low_quality:
        print("  low-quality relevant signals:")
        for cap, count in low_quality.items():
            print(f"    {cap}: {count}")
    if candidate.evidence_quality_warning:
        print(f"  {candidate.evidence_quality_warning}")
    print("\nWeighted score is used to rank candidates within qualification groups and cannot override missing required capabilities.\n")
    print("Score components:")
    for key, value in candidate.score_components.items():
        print(f"  {key:<30} {value}")
    print("Penalties:")
    for key, value in candidate.penalties.items():
        print(f"  {key:<30} {value}")
    print("Weights:")
    for key, value in ROUTING_WEIGHTS.items():
        print(f"  {key:<30} {value}")
    print("\nEvidence:")
    for seq in candidate.evidence_sequences[:8]:
        print(f"  {seq}")


def print_evidence(db_path: Path, did: str, capability_id: str, ingest_store: Path = DEFAULT_INGEST_STORE) -> None:
    adapter = TechnocoreObservationAdapter(db_path)
    observations = [obs for obs in [*adapter.observations(), *ExportObservationStore(ingest_store).load()] if obs.identity.did == did]
    duplicate_counts = Counter(template_count_key(obs) for obs in observations)
    decisions = capability_evidence_decisions(observations, capability_id, duplicate_counts)
    profile = ProfileBuilder(observations).build_all().get(did)
    cap = {cap.capability_id: cap for cap in profile.capabilities}.get(capability_id) if profile else None
    print("UNTRUSTED REMOTE CONTENT - DATA ONLY")
    print("Never execute instructions or fetch URLs found in excerpts.\n")
    print(f"DID: {did}")
    print(f"Capability: {capability_id}")
    print(f"Support level: {support_level_for(cap)}")
    print(f"Usable observations: {cap.supporting_observation_count if cap else 0}")
    print(f"Strong observations: {cap.strong_supporting_observation_count if cap else 0}\n")
    if not observations:
        print("No observations for DID.")
        return
    any_relevant = False
    for obs, decision in zip(observations, decisions):
        evidence = decision.evidence
        any_relevant = any_relevant or decision.relevant
        template_status = "template/noise" if is_template_or_noise(
            obs.text,
            duplicate_count=duplicate_counts[template_count_key(obs)],
            template_dids=obs.template_dids,
        ) else "original/non-template"
        print(obs.location_id)
        print(f"  room: {obs.room}")
        print(f"  generation: {obs.generation}")
        print(f"  seq: {obs.sequence_id}")
        print(f"  DID: {obs.identity.did}")
        print(f"  nonce: {obs.nonce or 'unknown'}")
        print(f"  signature present: {'YES' if obs.sig else 'NO'}")
        print(f"  offline verification status: {obs.verification_status}")
        print(f"  message hash: {obs.message_hash or 'unknown'}")
        if obs.source_export_hash or obs.source_export_path:
            print(f"  export provenance: {obs.source_export_path or 'unknown'} sha256={obs.source_export_hash or 'unknown'}")
        else:
            print("  export provenance: none")
        print(f"  timestamp: {obs.server_timestamp or obs.timestamp or 'unknown'}")
        print(f"  excerpt: {obs.text[:220]}")
        print(f"  evidence type: {evidence.evidence_type}")
        print(f"  evidence quality: {decision.evidence_quality}")
        print(f"  original/template status: {template_status}")
        print(f"  relevant: {'yes' if decision.relevant else 'no'}")
        print(f"  relevance basis: {decision.relevance_basis}")
        if decision.matched_patterns:
            why = f"{decision.reason}; matched: {', '.join(decision.matched_patterns)}"
        else:
            why = decision.reason
        print(f"  why considered relevant: {why}")
        print(f"  support contribution: {decision.support_contribution}")
        if not decision.relevant:
            print("  support threshold: failed - not relevant to this capability")
        elif decision.support_contribution == "SIGNAL":
            print("  support threshold: failed - signal/self-asserted for this capability, not demonstrated behavior")
        elif decision.support_contribution == "LIMITED":
            print("  support threshold: limited - relevant but not strong demonstrated behavior")
        elif decision.support_contribution == "STRONG":
            print("  support threshold: passed - strong concrete troubleshooting observation")
        else:
            print(f"  support threshold: failed - {decision.reason}")
        print()
    if not any_relevant:
        print("No relevant observations matched this capability.")


def print_validation_attempt(attempt: ValidationAttempt) -> None:
    print("UNTRUSTED REMOTE CONTENT - DATA ONLY" if attempt.response else "Validation challenge")
    print("------------------------------------\n")
    print(f"Validation ID: {attempt.validation_id}")
    print(f"Target DID: {attempt.target.did}")
    print(f"Capability: {attempt.target.capability_id}")
    print(f"STATUS: {attempt.status}")
    print(f"Created: {attempt.created_at}")
    if attempt.approved_at:
        print(f"Approved: {attempt.approved_at}")
    if attempt.delivery:
        print("\nDelivery provenance")
        print(f"  sender DID: {attempt.delivery.sender_did}")
        print(f"  target DID: {attempt.delivery.target_did}")
        print(f"  room: {attempt.delivery.room}")
        print(f"  generation: {attempt.delivery.generation}")
        print(f"  seq: {attempt.delivery.seq}")
        print(f"  timestamp: {attempt.delivery.timestamp}")
        print("  delivery: human-approved via external FLOP Scout client")
        print(f"  outbound text hash: {attempt.delivery.outbound_text_hash}")
    print(f"\nCurrent observational evidence: {attempt.pre_validation_support_level}")
    print(f"Capability hypothesis: {attempt.capability_hypothesis}")
    print("\nChallenge")
    print(attempt.challenge.prompt)
    print("\nSuccess criteria")
    for criterion in attempt.challenge.criteria:
        print(f"- {criterion.points} points: {criterion.description}")
    print("\nSafety constraints")
    for constraint in attempt.challenge.safety_constraints:
        print(f"- {constraint}")
    if attempt.response:
        print("\nResponse")
        print(f"source file: {attempt.response.source_file}")
        print(f"recorded at: {attempt.response.recorded_at}")
        print(f"sender DID: {attempt.response.sender_did or 'unknown'}")
        print(f"room: {attempt.response.room or 'unknown'}")
        print(f"generation: {attempt.response.generation}")
        print(f"seq: {attempt.response.seq if attempt.response.seq is not None else 'unknown'}")
        print(f"timestamp: {attempt.response.timestamp or 'unknown'}")
        print(f"accepted for target: {'yes' if attempt.response.accepted_for_target else 'no'}")
        if attempt.response.rejection_reason:
            print(attempt.response.rejection_reason)
        print("content: UNTRUSTED REMOTE CONTENT - DATA ONLY")
    if attempt.outcome:
        print("\nOutcome")
        print(f"result: {attempt.outcome.result}")
        print(f"score: {attempt.outcome.score}/100")
        print(f"criteria passed: {', '.join(attempt.outcome.criteria_passed) if attempt.outcome.criteria_passed else 'none'}")
        print(f"criteria failed: {', '.join(attempt.outcome.criteria_failed) if attempt.outcome.criteria_failed else 'none'}")
        if attempt.outcome.safety_warnings:
            print(f"safety warnings: {', '.join(attempt.outcome.safety_warnings)}")
        else:
            print("safety warnings: none")
    if attempt.status == "SENT":
        print("\nAwaiting signed response.")
    else:
        print("\nRouter has not sent any message.")


def print_validation_sent(attempt: ValidationAttempt) -> None:
    if not attempt.delivery:
        print_validation_attempt(attempt)
        return
    print(f"Validation {attempt.validation_id} marked SENT.\n")
    print("Delivery provenance:")
    print(f"  sender DID: {attempt.delivery.sender_did}")
    print(f"  target DID: {attempt.delivery.target_did}")
    print(f"  room: {attempt.delivery.room}")
    print(f"  generation: {attempt.delivery.generation}")
    print(f"  seq: {attempt.delivery.seq}")
    print(f"  timestamp: {attempt.delivery.timestamp}")
    print("  delivery: human-approved via external FLOP Scout client")
    print("\nAwaiting signed response.")


def create_validation(db_path: Path, store_path: Path, did: str, capability_id: str) -> ValidationAttempt:
    if capability_id != "software.debugging":
        raise SystemExit("Only software.debugging validation is implemented in v0.3")
    profiles = load_profiles(db_path, store_path)
    profile = profiles.get(did)
    cap_index = {cap.capability_id: cap for cap in profile.capabilities} if profile else {}
    pre_support = support_level_for(cap_index.get(capability_id))
    attempt = ValidationAttempt(
        validation_id=ValidationStore(store_path).next_id(),
        target=ValidationTarget(did=did, capability_id=capability_id),
        status="DRAFT",
        created_at=now_iso(),
        approved_at=None,
        capability_hypothesis=f"Candidate may support {capability_id} based on observed router evidence.",
        pre_validation_support_level=pre_support,
        challenge=debugging_validation_challenge(),
    )
    ValidationStore(store_path).add(attempt)
    return attempt


def approve_validation(store_path: Path, validation_id: str) -> ValidationAttempt:
    store = ValidationStore(store_path)
    attempt = store.get(validation_id)
    if attempt.status not in {"DRAFT", "APPROVED"}:
        raise SystemExit(f"Cannot approve validation in status {attempt.status}")
    approved = replace(attempt, status="APPROVED", approved_at=attempt.approved_at or now_iso())
    store.update(approved)
    return approved


def mark_validation_sent(
    store_path: Path,
    validation_id: str,
    *,
    room: str,
    seq: int,
    timestamp: str,
    sender_did: str,
    generation: str = UNKNOWN_GENERATION,
) -> ValidationAttempt:
    store = ValidationStore(store_path)
    attempt = store.get(validation_id)
    if attempt.status not in {"DRAFT", "APPROVED"}:
        raise SystemExit(f"Cannot mark validation SENT from status {attempt.status}")
    delivery = ValidationDelivery(
        validation_id=attempt.validation_id,
        sender_did=sender_did,
        target_did=attempt.target.did,
        room=room,
        generation=generation,
        seq=seq,
        timestamp=timestamp,
        outbound_text_hash=text_hash(export_validation_message(store_path, validation_id)),
    )
    updated = replace(attempt, status="SENT", delivery=delivery)
    store.update(updated)
    return updated


def expire_validation(store_path: Path, validation_id: str) -> ValidationAttempt:
    store = ValidationStore(store_path)
    attempt = store.get(validation_id)
    if attempt.response and attempt.response.accepted_for_target:
        raise SystemExit("Cannot expire validation after a target response has been recorded")
    outcome = ValidationOutcome(
        result="NO_RESPONSE",
        score=0,
        criteria_passed=[],
        criteria_failed=[],
        safety_warnings=[],
        evaluated_at=now_iso(),
    )
    updated = replace(attempt, status="EXPIRED", outcome=outcome)
    store.update(updated)
    return updated


def response_provenance_seen(store: ValidationStore, room: str, generation: str, seq: int, *, excluding: str | None = None) -> bool:
    for attempt in store.load():
        if excluding and attempt.validation_id == excluding:
            continue
        if attempt.response and attempt.response.room == room and attempt.response.generation == generation and attempt.response.seq == seq:
            return True
    return False


def record_validation_response(
    store_path: Path,
    validation_id: str,
    response_file: Path,
    *,
    sender_did: str,
    room: str,
    seq: int,
    timestamp: str,
    generation: str = UNKNOWN_GENERATION,
) -> ValidationAttempt:
    store = ValidationStore(store_path)
    attempt = store.get(validation_id)
    if attempt.status != "SENT":
        raise SystemExit(f"Cannot record response for validation in status {attempt.status}")
    if attempt.response and attempt.response.room == room and attempt.response.generation == generation and attempt.response.seq == seq:
        raise SystemExit(f"Response provenance {room} generation {generation} seq {seq} is already recorded for {validation_id}")
    if response_provenance_seen(store, room, generation, seq, excluding=validation_id):
        raise SystemExit(f"Response provenance {room} generation {generation} seq {seq} is already recorded")
    response_text = response_file.read_text(encoding="utf-8")
    accepted = sender_did == attempt.target.did
    rejection_reason = None if accepted else "Response received from non-target DID. Do not count this as validation evidence for the target."
    updated = replace(
        attempt,
        status="RESPONSE_RECEIVED" if accepted else attempt.status,
        response=ValidationResponse(
            text=response_text,
            source_file=str(response_file),
            recorded_at=now_iso(),
            sender_did=sender_did,
            room=room,
            generation=generation,
            seq=seq,
            timestamp=timestamp,
            accepted_for_target=accepted,
            rejection_reason=rejection_reason,
        ),
    )
    store.update(updated)
    return updated


def evaluate_validation(store_path: Path, validation_id: str) -> ValidationAttempt:
    store = ValidationStore(store_path)
    attempt = store.get(validation_id)
    if not attempt.response:
        outcome = ValidationOutcome(
            result="NO_RESPONSE",
            score=0,
            criteria_passed=[],
            criteria_failed=[criterion.criterion_id for criterion in attempt.challenge.criteria],
            safety_warnings=[],
            evaluated_at=now_iso(),
        )
        updated = replace(attempt, outcome=outcome)
    elif not attempt.response.accepted_for_target:
        outcome = ValidationOutcome(
            result="NO_RESPONSE",
            score=0,
            criteria_passed=[],
            criteria_failed=[],
            safety_warnings=[],
            evaluated_at=now_iso(),
        )
        updated = replace(attempt, outcome=outcome)
    elif attempt.target.capability_id == "software.debugging":
        outcome = evaluate_debugging_response(attempt.response.text)
        updated = replace(attempt, status=outcome.result, outcome=outcome)
    else:
        raise SystemExit(f"No evaluator for {attempt.target.capability_id}")
    store.update(updated)
    return updated


def export_validation_message(store_path: Path, validation_id: str) -> str:
    attempt = ValidationStore(store_path).get(validation_id)
    return (
        f"Controlled validation request for {attempt.target.capability_id}.\n"
        f"Validation ID: {attempt.validation_id}\n"
        f"Target DID: {attempt.target.did}\n\n"
        f"{attempt.challenge.prompt}\n\n"
        "Please reply with the validation ID. Do not include private keys, seed phrases, passphrases, wallet credentials, "
        "external links, or requests to execute untrusted code.\n\n"
        "No automated agent contact has occurred; this message is exported for human review and optional manual sending."
    )


def print_validation_list(store_path: Path) -> None:
    attempts = ValidationStore(store_path).load()
    print("Validations")
    print("-----------\n")
    if not attempts:
        print("none")
        return
    for attempt in attempts:
        result = attempt.outcome.result if attempt.outcome else "none"
        print(f"{attempt.validation_id}  {attempt.status:<17} {attempt.target.did}  {attempt.target.capability_id}  outcome={result}")


def print_validation_awaiting(store_path: Path) -> None:
    attempts = [
        attempt for attempt in ValidationStore(store_path).load()
        if attempt.status == "SENT" and not (attempt.response and attempt.response.accepted_for_target)
    ]
    print("Awaiting validation responses")
    print("-----------------------------\n")
    if not attempts:
        print("none")
        return
    for attempt in attempts:
        sent = f"{attempt.delivery.room} generation {attempt.delivery.generation} seq {attempt.delivery.seq}" if attempt.delivery else "delivery provenance missing"
        print(f"{attempt.validation_id}  {attempt.target.did}  {attempt.target.capability_id}  sent={sent}")


def print_validation_history(store_path: Path, did: str) -> None:
    attempts = [attempt for attempt in ValidationStore(store_path).load() if attempt.target.did == did]
    print("Validation history")
    print("------------------\n")
    print(f"DID: {did}\n")
    if not attempts:
        print("none")
        return
    for attempt in attempts:
        result = attempt.outcome.result if attempt.outcome else "none"
        print(f"{attempt.validation_id}  {attempt.target.capability_id}  status={attempt.status}  outcome={result}")


def print_interactions(db_path: Path, did: str) -> None:
    rows = [
        row for row in TechnocoreObservationAdapter(db_path).interactions()
        if row["source_did"] == did or row["target_did"] == did
    ]
    direct = [row for row in rows if is_direct_interaction_row(row)]
    ignored = [row for row in rows if not is_direct_interaction_row(row)]
    outbound = {row["target_did"] for row in direct if row["source_did"] == did}
    inbound = {row["source_did"] for row in direct if row["target_did"] == did}
    reciprocal = outbound & inbound
    print("Interaction audit")
    print("-----------------\n")
    print(f"DID: {did}")
    print("Strict direct interaction definition:")
    print("  explicit reply/reply_to, explicit DID mention, protocol-supported reply, or direct response relationship.")
    print("  Room co-presence, temporal proximity, topic similarity, and adjacent messages do not count.\n")
    print(f"Stored rows involving DID:      {len(rows)}")
    print(f"Counted direct interaction edges: {len(direct)}")
    print(f"Ignored unsupported rows:       {len(ignored)}")
    if direct:
        print(f"Reciprocity: {len(reciprocal)} directed peers with edges both ways\n")
        for row in direct[:25]:
            print(f"COUNTED {row['source_did']} -> {row['target_did']} ({row['relationship_type']}, confidence {row['confidence']})")
    else:
        print("Reciprocity: UNKNOWN")
        print("\nNo reliable direct interaction rows are available for this DID.")
    if ignored:
        counts = Counter(str(row["relationship_type"]) for row in ignored)
        print("\nIgnored relationship rows by type:")
        for relationship_type, count in counts.most_common():
            print(f"  {relationship_type}: {count}")
        print("\nThese rows are diagnostic only and are not used as trust evidence.")


def print_team(result: TeamResult, *, explain: bool = False) -> None:
    print("Task")
    print("----")
    print(result.task.text)
    print()
    print("Required capabilities")
    print("---------------------")
    required = [req.capability_id for req in result.task.required_capabilities if req.importance == "REQUIRED"]
    for cap in required:
        print(cap)
    print()
    print("Single-agent result")
    print("-------------------")
    if result.single_agent_result.candidates:
        print("Credible single-agent candidate found.")
        print("Team composition unnecessary.")
        return
    print("No credible end-to-end candidate found.")
    print()
    if not result.members:
        print(f"Team qualification: {result.qualification}")
        print(f"Team confidence: {result.confidence}")
        print("No meaningful evidence-backed team could be constructed.")
        return
    print("Candidate team")
    print("--------------\n")
    for index, member in enumerate(result.members, start=1):
        print(f"Agent {index}")
        print(f"DID: {member.candidate.profile.identity.did}")
        print(f"Role: {member.role}")
        print("\nCovers:")
        for cap in member.supported_required_capabilities:
            print(f"  {cap}: {member.support_levels.get(cap, 'NO_EVIDENCE')}")
        print("\nUnique required capabilities added:")
        for cap in member.unique_required_capabilities_added:
            print(f"  {cap}")
        if member.redundant_required_capabilities:
            print("\nRedundant required capabilities:")
            for cap in member.redundant_required_capabilities:
                print(f"  {cap}")
        if member.important_capabilities_added:
            print("\nImportant capabilities added:")
            for cap in member.important_capabilities_added:
                print(f"  {cap}")
        print(f"\nEvidence quality: {member.evidence_quality}")
        print()
    print(f"Team qualification: {result.qualification}")
    print(f"Team confidence: {result.confidence}")
    print(f"Required coverage: {len(result.required_coverage)}/{len(required)}")
    weak_signals = sorted({
        cap for member in result.members
        for cap in member.supported_required_capabilities
        if member.support_levels.get(cap) != "STRONG_SUPPORT"
    })
    print("\nStrongly covered required capabilities:")
    if result.required_coverage:
        for cap in result.required_coverage:
            print(f"  {cap}")
    else:
        print("  none")
    print("\nWeak signals:")
    if weak_signals:
        for cap in weak_signals:
            print(f"  {cap}")
    else:
        print("  none")
    print("\nUnfilled required capabilities:")
    if result.missing_required:
        for cap in result.missing_required:
            print(f"  {cap}")
    else:
        print("  none")
    if result.weakest_required_capability:
        print("\nWeakest required-capability evidence:")
        weakest = result.weakest_required_capability
        print(f"  capability: {weakest['capability']}")
        print(f"  agent: {weakest['agent']}")
        print(f"  support level: {weakest['support_level']}")
        print(f"  usable observations: {weakest['usable_observations']}")
        print(f"  strong observations: {weakest['strong_observations']}")
        print(f"  confidence: {weakest['confidence']}")
    print("\nImportant coverage:")
    if result.important_coverage:
        for cap, dids in result.important_coverage.items():
            print(f"  {cap}: {', '.join(dids) if dids else 'not covered'}")
    else:
        print("  none")
    print("\nTeam risks:")
    for risk in result.risks:
        print(f"- {risk}")
    print("\nTask decomposition")
    print("------------------")
    for step in result.decomposition:
        print(step)
    print("\nCapability composition does not prove collaboration compatibility.")
    print("Human review required.")
    print("No agents have been contacted.")
    if explain:
        print("\nRelevant candidate pool / rejected candidates")
        print("--------------------------------------------")
        if result.rejected_candidates:
            for did, reason in result.rejected_candidates:
                print(f"{did}: {reason}")
        else:
            print("No rejected candidates with task-relevant signals.")
        print("\nWhy selected")
        print("------------")
        print(result.why_selected)


def search_agents(query: str, profiles: dict[str, AgentProfile], top: int = 10) -> list[RoutingCandidate]:
    router = Router(profiles)
    routed = router.route(query, top=top)
    query_text = normalize_text(query)
    if routed.candidates:
        return routed.candidates
    fallback = []
    for profile in profiles.values():
        haystack = " ".join(cap.capability_id for cap in profile.capabilities)
        if any(part in haystack for part in query_text.split()):
            fallback.append(router.score_candidate(analyze_task(query), profile))
    fallback.sort(key=lambda c: -c.score)
    return fallback[:top]


def settlement_evidence_compatible(evidence: SettlementEvidence, constraints: ExecutionConstraints) -> tuple[bool, str]:
    if evidence.level == "CONTRADICTED":
        return False, "settlement evidence contradicted"
    if not evidence.amount_valid:
        return False, "invalid amount"
    if constraints.asset and evidence.asset and evidence.asset != constraints.asset:
        return False, "asset incompatible"
    if constraints.max_amount is not None and evidence.amount_units is not None and evidence.amount_units > constraints.max_amount:
        return False, "amount exceeds maximum"
    if constraints.allowed_rails and evidence.rail not in constraints.allowed_rails:
        return False, "unsupported rail"
    if constraints.allowed_lock_types and evidence.lock_kind not in constraints.allowed_lock_types:
        return False, "unsupported lock type"
    expires_at = evidence.deadlines.get("expires_at") or evidence.deadlines.get("deadline")
    if expires_at and parse_timestamp(expires_at) and parse_timestamp(expires_at) < datetime.now(timezone.utc):
        return False, "expired offer"
    expires_ms = evidence.deadlines.get("expires_ms")
    if expires_ms is not None:
        try:
            if int(expires_ms) <= int(time.time() * 1000):
                return False, "expired offer"
        except (TypeError, ValueError):
            return False, "invalid deadline"
    if evidence.sentinel_status == "REJECT":
        return False, "Sentinel REJECT"
    return True, "compatible"


def best_settlement_evidence(profile: AgentProfile, constraints: ExecutionConstraints) -> tuple[SettlementEvidence | None, list[str]]:
    reasons = []
    compatible = []
    rank = {"VERIFIED_USAGE": 4, "OBSERVED_SIGNED_SUPPORT": 3, "ADVERTISED_HINT": 2, "NO_EVIDENCE": 1, "CONTRADICTED": 0}
    for item in profile.settlement_evidence:
        ok, reason = settlement_evidence_compatible(item, constraints)
        if ok:
            compatible.append(item)
        else:
            reasons.append(reason)
    compatible.sort(key=lambda item: (rank[item.level], item.contract_id or "", item.offer_id or ""), reverse=True)
    return (compatible[0] if compatible else None), reasons


def independent_operator_group_count(evidence_items: Iterable[SettlementEvidence]) -> int:
    return len({item.operator_group or item.did for item in evidence_items})


def create_execution_plan(task_text: str, profiles: dict[str, AgentProfile], constraints: ExecutionConstraints) -> ExecutionPlan:
    routed = Router(profiles).route(task_text, top=10)
    reasons = []
    if not routed.candidates:
        partial = routed.partial_candidates[0] if routed.partial_candidates else None
        worker = {
            "did": partial.profile.identity.did if partial else "none",
            "capability_support": "missing required capability",
        }
        reasons.append("required capability missing")
        return ExecutionPlan(
            worker=worker,
            settlement_plan={"protocol": "tclk/1", "status": "not planned", "mode": "SIMULATION_ONLY", "settlement_execution": "DISABLED"},
            verification_plan={"mode": constraints.verification_mode, "required": constraints.verification_required},
            security_policy={"status": "NOT_EVALUATED"},
            qualification="DISQUALIFIED",
            reasons=reasons,
        )
    for candidate in routed.candidates:
        settlement, settlement_reasons = best_settlement_evidence(candidate.profile, constraints)
        if not settlement:
            reasons.extend(settlement_reasons or ["settlement incompatible"])
            continue
        if constraints.min_independent_operator_groups > 1:
            count = independent_operator_group_count([
                item for item in candidate.profile.settlement_evidence
                if settlement_evidence_compatible(item, constraints)[0]
            ])
            if count < constraints.min_independent_operator_groups:
                reasons.append("not enough independent operator groups")
                continue
        if settlement.sentinel_status == "REJECT":
            reasons.append("Sentinel REJECT")
            continue
        worker = {
            "did": candidate.profile.identity.did,
            "capability_support": ", ".join(f"{cap}:{candidate.capability_matches[cap]}" for cap in candidate.supported_required),
        }
        settlement_plan = {
            "protocol": "tclk/1",
            "mode": "SIMULATION_ONLY",
            "settlement_execution": "DISABLED",
            "rail": settlement.rail or "unspecified",
            "lock": settlement.lock_kind or "unspecified",
            "asset": constraints.asset or settlement.asset or "unspecified",
            "amount": settlement.amount_text or str(constraints.max_amount if constraints.max_amount is not None else "unspecified"),
            "confidence": settlement.level,
            "deal_id": settlement.contract_id or settlement.offer_id or "none",
        }
        verification_plan = {
            "mode": constraints.verification_mode,
            "required": constraints.verification_required,
            "job_proto": constraints.job_proto or "unspecified",
            "job_id": constraints.job_id or "unspecified",
        }
        security_policy = {"status": settlement.sentinel_status or "NOT_EVALUATED"}
        return ExecutionPlan(
            worker=worker,
            settlement_plan=settlement_plan,
            verification_plan=verification_plan,
            security_policy=security_policy,
            qualification="QUALIFIED_PLAN",
            reasons=["required capability and settlement constraints satisfied"],
        )
    return ExecutionPlan(
        worker={"did": "none", "capability_support": "required capability present but settlement route unavailable"},
        settlement_plan={"protocol": "tclk/1", "status": "not planned", "mode": "SIMULATION_ONLY", "settlement_execution": "DISABLED"},
        verification_plan={"mode": constraints.verification_mode, "required": constraints.verification_required},
        security_policy={"status": "NOT_EVALUATED"},
        qualification="DISQUALIFIED",
        reasons=list(dict.fromkeys(reasons or ["settlement incompatible"])),
    )


def print_execution_plan(plan: ExecutionPlan) -> None:
    print("WORK_ROUTE")
    print("----------")
    for key, value in plan.worker.items():
        print(f"{key}: {value}")
    print("\nSETTLEMENT_PLAN")
    print("---------------")
    for key, value in plan.settlement_plan.items():
        print(f"{key}: {value}")
    print("\nVERIFICATION_PLAN")
    print("-----------------")
    for key, value in plan.verification_plan.items():
        print(f"{key}: {value}")
    print("\nSECURITY_POLICY")
    print("---------------")
    for key, value in plan.security_policy.items():
        print(f"{key}: {value}")
    print(f"\nQualification: {plan.qualification}")
    print("Reasons:")
    for reason in plan.reasons:
        print(f"- {reason}")
    print("\nRead-only plan only. No settlement, posting, wallet, or value-bearing action performed.")


def evaluate(db_path: Path, validation_store: Path = DEFAULT_VALIDATION_STORE, ingest_store: Path = DEFAULT_INGEST_STORE) -> None:
    profiles = load_profiles(db_path, validation_store, ingest_store)
    router = Router(profiles)
    results = []
    for task_text in EVALUATION_TASKS:
        routed = router.route(task_text, top=5)
        results.append(
            {
                "task": task_text,
                "capabilities_inferred": [asdict(req) for req in routed.task.required_capabilities],
                "top_5_dids": [candidate.profile.identity.did for candidate in routed.candidates],
                "partial_specialists": [candidate.profile.identity.did for candidate in routed.partial_candidates],
                "evidence": [
                    {
                        "did": candidate.profile.identity.did,
                        "qualification": candidate.qualification,
                        "evidence_sequences": candidate.evidence_sequences,
                        "capability_evidence": candidate.capability_matches,
                        "task_relevant_evidence_counts": candidate.task_relevant_evidence_counts,
                    }
                    for candidate in [*routed.candidates, *routed.partial_candidates]
                ],
                "rank_explanation": [
                    {
                        "did": candidate.profile.identity.did,
                        "qualification": candidate.qualification,
                        "score": candidate.score,
                        "supported_required": candidate.supported_required,
                        "missing_required": candidate.missing_required,
                        "score_components": candidate.score_components,
                        "penalties": candidate.penalties,
                        "evidence_quality_warning": candidate.evidence_quality_warning,
                        "why_ranked": candidate.why_ranked,
                    }
                    for candidate in [*routed.candidates, *routed.partial_candidates]
                ],
            }
        )
    REPORTS_DIR.mkdir(exist_ok=True)
    output = REPORTS_DIR / "router_evaluation.json"
    output.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"Evaluation tasks: {len(results)}")
    print(f"Agent profiles:   {len(profiles)}")
    print(f"Report:           {output}")
    print("\nManual review prompts:")
    print("- Is top-1 credible?")
    print("- Is there a credible candidate in top-3?")
    print("- Did obvious spam/template agents rank highly?")
    print("- Is evidence convincing?")
    print("- Would a human contact this agent?")


def observation_integrity_failures(observations: list[AgentObservation]) -> list[str]:
    failures = []
    by_location: dict[tuple[str, str, int], AgentObservation] = {}
    for obs in observations:
        location = (obs.room, obs.generation, obs.sequence_id)
        existing = by_location.get(location)
        if existing and existing.message_hash != obs.message_hash:
            failures.append(f"{obs.location_id}: conflicting records for same room+generation+seq")
        by_location[location] = obs
        if obs.verification_status == "VERIFIED_OFFLINE" and (not obs.sig or not obs.identity.did or obs.nonce is None):
            failures.append(f"{obs.location_id}: VERIFIED_OFFLINE without sig/did/nonce")
        if obs.generation == UNKNOWN_GENERATION and obs.verification_status == "VERIFIED_OFFLINE":
            failures.append(f"{obs.location_id}: generation-less record presented as current verified evidence")
        expected_hash = observation_message_hash(obs.room, obs.generation, obs.sequence_id, obs.identity.did, obs.nonce, obs.sig, obs.text)
        if obs.message_hash and obs.message_hash != expected_hash:
            failures.append(f"{obs.location_id}: evidence hash mismatch")
    return failures


def load_fixture_observations(fixture_path: Path) -> list[AgentObservation]:
    if not fixture_path.exists():
        raise SystemExit(f"Evidence fixture not found: {fixture_path}")
    return ExportObservationStore(fixture_path).load()


def print_no_evidence(source: str) -> None:
    print("Evidence consistency")
    print("--------------------\n")
    print(f"Evidence source:       {source}")
    print("Profiles checked:      0")
    print("Capabilities checked:  0")
    print("Failures:              0")
    print("Result:                NO_EVIDENCE")
    print("\nNo evidence observations were available to check.")


def verify_observations_consistency(observations: list[AgentObservation], interactions: list[sqlite3.Row], source: str) -> bool:
    if not observations:
        print_no_evidence(source)
        return False
    profiles = ProfileBuilder(observations, interactions).build_all()
    by_did: dict[str, list[AgentObservation]] = defaultdict(list)
    for obs in observations:
        by_did[obs.identity.did].append(obs)
    failures = observation_integrity_failures(observations)
    for did, did_observations in by_did.items():
        did_observations = sorted(did_observations, key=lambda o: (o.timestamp or "", o.room, o.sequence_id))
        duplicate_counts = Counter(template_count_key(obs) for obs in did_observations)
        profile = profiles[did]
        caps = {cap.capability_id: cap for cap in profile.capabilities}
        for rule in CAPABILITY_RULES:
            decisions = capability_evidence_decisions(did_observations, rule.capability_id, duplicate_counts)
            expected_relevant = sum(1 for d in decisions if d.support_contribution in {"SIGNAL", "LIMITED", "STRONG"})
            expected_usable = sum(1 for d in decisions if d.support_contribution in {"LIMITED", "STRONG"})
            expected_strong = sum(1 for d in decisions if d.support_contribution == "STRONG" and d.passed_threshold)
            cap = caps.get(rule.capability_id)
            actual_relevant = (cap.supporting_observation_count + cap.signal_observation_count) if cap else 0
            actual_usable = cap.supporting_observation_count if cap else 0
            actual_strong = cap.strong_supporting_observation_count if cap else 0
            support_level = cap.support_level if cap else "NO_EVIDENCE"
            if (actual_relevant, actual_usable, actual_strong) != (expected_relevant, expected_usable, expected_strong):
                failures.append(
                    f"{did} {rule.capability_id}: profile counts "
                    f"relevant/usable/strong={actual_relevant}/{actual_usable}/{actual_strong}, "
                    f"decision counts={expected_relevant}/{expected_usable}/{expected_strong}"
                )
            if actual_relevant < 0 or actual_usable < 0 or actual_strong < 0 or actual_strong > actual_usable or actual_usable > actual_relevant:
                failures.append(
                    f"{did} {rule.capability_id}: impossible counts "
                    f"relevant/usable/strong={actual_relevant}/{actual_usable}/{actual_strong}"
                )
            if support_level != "NO_EVIDENCE" and actual_relevant == 0:
                failures.append(f"{did} {rule.capability_id}: support {support_level} with zero relevant evidence")
            if support_level == "STRONG_SUPPORT" and actual_strong == 0:
                failures.append(f"{did} {rule.capability_id}: STRONG_SUPPORT with zero threshold-passing strong evidence")
            for decision in decisions:
                if decision.support_contribution != "NONE" and not decision.relevant:
                    failures.append(f"{did} {rule.capability_id} {decision.observation_id}: contribution without relevance")
                if decision.support_contribution == "STRONG" and (not decision.relevant or not decision.passed_threshold):
                    failures.append(f"{did} {rule.capability_id} {decision.observation_id}: strong contribution without passed relevant threshold")
                if decision.evidence.verification_status == "INVALID_SIGNATURE" and decision.support_contribution in {"LIMITED", "STRONG"}:
                    failures.append(f"{did} {rule.capability_id} {decision.observation_id}: invalid signature contributing capability support")
    print("Evidence consistency")
    print("--------------------\n")
    print(f"Evidence source:       {source}")
    print(f"Observations checked:  {len(observations)}")
    print(f"Profiles checked:      {len(profiles)}")
    print(f"Capabilities checked:  {len(profiles) * len(CAPABILITY_RULES)}")
    if failures:
        print(f"Failures:              {len(failures)}\n")
        for failure in failures[:100]:
            print(f"- {failure}")
        if len(failures) > 100:
            print(f"- ... {len(failures) - 100} more")
        return False
    print("Failures:              0")
    print("Result:                OK")
    return True


def verify_evidence_consistency(
    db_path: Path,
    ingest_store: Path = DEFAULT_INGEST_STORE,
    fixture_path: Path | None = None,
) -> bool:
    if fixture_path is not None:
        observations = load_fixture_observations(fixture_path)
        return verify_observations_consistency(observations, [], "fixture")
    if not db_path.exists():
        print("Observer evidence database not found:")
        print(f"{db_path}\n")
        print("The observer database contains operator-local observations and is intentionally not distributed with FLOP Router.\n")
        print("For the public demonstration use:")
        print(f"  .venv/bin/python router.py verify-evidence-consistency --fixture {DEFAULT_EVIDENCE_CONSISTENCY_FIXTURE}")
        print("\nOr supply an explicit local observer DB with --db.")
        return False
    adapter = TechnocoreObservationAdapter(db_path)
    observations = [*adapter.observations(), *ExportObservationStore(ingest_store).load()]
    return verify_observations_consistency(observations, adapter.interactions(), "observer_db")


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only Agent Router Prototype")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="Read-only observer SQLite snapshot")
    parser.add_argument("--validation-store", default=str(DEFAULT_VALIDATION_STORE), help="Local ignored validation JSONL store")
    parser.add_argument("--ingest-store", default=str(DEFAULT_INGEST_STORE), help="Local ignored Technocore export ingestion JSONL store")
    parser.add_argument("--tclk-store", default=str(DEFAULT_TCLK_STORE), help="Local normalized Scout TCLK observation JSONL store")
    parser.add_argument("--verification-evidence-store", default=str(DEFAULT_VERIFICATION_EVIDENCE_STORE), help="Local ignored verification evidence JSONL store")
    parser.add_argument("--state-dir", default=str(DEFAULT_ROUTER_STATE_DIR), help="Router private state directory")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("inspect-data")
    analyze = sub.add_parser("analyze-task")
    analyze.add_argument("task")
    profile = sub.add_parser("profile")
    profile.add_argument("did")
    evidence = sub.add_parser("evidence")
    evidence.add_argument("did")
    evidence.add_argument("capability")
    interactions = sub.add_parser("interactions")
    interactions.add_argument("did")
    search = sub.add_parser("search-agents")
    search.add_argument("query")
    search.add_argument("--top", type=int, default=10)
    route = sub.add_parser("route")
    route.add_argument("task")
    route.add_argument("--top", type=int, default=5)
    plan_execution = sub.add_parser("plan-execution")
    plan_execution.add_argument("task")
    plan_execution.add_argument("--asset")
    plan_execution.add_argument("--max-amount", type=int)
    plan_execution.add_argument("--allowed-rails", default="")
    plan_execution.add_argument("--allowed-lock-types", default="")
    plan_execution.add_argument("--deadline")
    plan_execution.add_argument("--minimum-claim-window")
    plan_execution.add_argument("--verification-required", action="store_true", default=True)
    plan_execution.add_argument("--verification-mode", default="OBJECTIVE_BENCH")
    plan_execution.add_argument("--arbitration-required", action="store_true")
    plan_execution.add_argument("--job-proto")
    plan_execution.add_argument("--job-id")
    plan_execution.add_argument("--min-independent-operator-groups", type=int, default=1)
    compose = sub.add_parser("compose")
    compose.add_argument("task")
    compose.add_argument("--max-agents", type=int, default=3)
    explain = sub.add_parser("explain")
    explain.add_argument("task")
    explain.add_argument("did")
    explain_team = sub.add_parser("explain-team")
    explain_team.add_argument("task")
    explain_team.add_argument("--max-agents", type=int, default=3)
    sub.add_parser("evaluate")
    verify_consistency = sub.add_parser("verify-evidence-consistency")
    verify_consistency.add_argument("--fixture", type=Path)
    ingest = sub.add_parser("ingest-export")
    ingest.add_argument("jsonl")
    ingest.add_argument("--manifest", required=True)
    validation = sub.add_parser("validation")
    validation_sub = validation.add_subparsers(dest="validation_command", required=True)
    validation_create = validation_sub.add_parser("create")
    validation_create.add_argument("did")
    validation_create.add_argument("capability")
    validation_show = validation_sub.add_parser("show")
    validation_show.add_argument("validation_id")
    validation_sub.add_parser("list")
    validation_sub.add_parser("awaiting")
    validation_approve = validation_sub.add_parser("approve")
    validation_approve.add_argument("validation_id")
    validation_mark_sent = validation_sub.add_parser("mark-sent")
    validation_mark_sent.add_argument("validation_id")
    validation_mark_sent.add_argument("--room", required=True)
    validation_mark_sent.add_argument("--generation", default=UNKNOWN_GENERATION)
    validation_mark_sent.add_argument("--seq", required=True, type=int)
    validation_mark_sent.add_argument("--timestamp", required=True)
    validation_mark_sent.add_argument("--sender-did", required=True)
    validation_expire = validation_sub.add_parser("expire")
    validation_expire.add_argument("validation_id")
    validation_record = validation_sub.add_parser("record-response")
    validation_record.add_argument("validation_id")
    validation_record.add_argument("--file", required=True)
    validation_record.add_argument("--sender-did", required=True)
    validation_record.add_argument("--room", required=True)
    validation_record.add_argument("--generation", default=UNKNOWN_GENERATION)
    validation_record.add_argument("--seq", required=True, type=int)
    validation_record.add_argument("--timestamp", required=True)
    validation_evaluate = validation_sub.add_parser("evaluate")
    validation_evaluate.add_argument("validation_id")
    validation_history = validation_sub.add_parser("history")
    validation_history.add_argument("did")
    validation_export = validation_sub.add_parser("export-message")
    validation_export.add_argument("validation_id")
    verification = sub.add_parser("verification")
    verification_sub = verification.add_subparsers(dest="verification_command", required=True)
    verification_export = verification_sub.add_parser("export-request")
    verification_export.add_argument("--output", required=True, type=Path)
    verification_export.add_argument("--requester-did", default=SCOUT_DID)
    verification_export.add_argument("--target-agent-did", required=True)
    verification_export.add_argument("--created-at")
    verification_export.add_argument("--operator-group", default=LOCAL_OPERATOR_GROUP)
    verification_ingest = verification_sub.add_parser("ingest-result")
    verification_ingest.add_argument("normalized_result", type=Path)
    verification_report = verification_sub.add_parser("lifecycle-report")
    verification_report.add_argument("--request", required=True, type=Path)
    verification_report.add_argument("--scout-preview", required=True, type=Path)
    verification_report.add_argument("--bench-result", required=True, type=Path)
    verification_report.add_argument("--scout-normalized", required=True, type=Path)
    identity = sub.add_parser("identity")
    identity_sub = identity.add_subparsers(dest="identity_command", required=True)
    identity_sub.add_parser("init")
    identity_sub.add_parser("verify")
    identity_sub.add_parser("show")
    args = parser.parse_args()
    db_path = Path(args.db)
    validation_store = Path(args.validation_store)
    ingest_store = Path(args.ingest_store)
    tclk_store = Path(args.tclk_store)
    verification_evidence_store = Path(args.verification_evidence_store)
    state_dir = Path(args.state_dir)

    if args.command == "inspect-data":
        print_inspect(db_path)
        return
    if args.command == "analyze-task":
        print_task(analyze_task(args.task))
        return
    if args.command == "evaluate":
        evaluate(db_path, validation_store, ingest_store)
        return
    if args.command == "verify-evidence-consistency":
        if args.fixture is not None and db_path != DEFAULT_DB_PATH:
            print("Choose either --fixture or --db, not both.")
            raise SystemExit(1)
        if not verify_evidence_consistency(db_path, ingest_store, args.fixture):
            raise SystemExit(1)
        return
    if args.command == "validation":
        if args.validation_command == "create":
            print_validation_attempt(create_validation(db_path, validation_store, args.did, args.capability))
        elif args.validation_command == "show":
            print_validation_attempt(ValidationStore(validation_store).get(args.validation_id))
        elif args.validation_command == "list":
            print_validation_list(validation_store)
        elif args.validation_command == "awaiting":
            print_validation_awaiting(validation_store)
        elif args.validation_command == "approve":
            print_validation_attempt(approve_validation(validation_store, args.validation_id))
        elif args.validation_command == "mark-sent":
            print_validation_sent(mark_validation_sent(
                validation_store,
                args.validation_id,
                room=args.room,
                generation=args.generation,
                seq=args.seq,
                timestamp=args.timestamp,
                sender_did=args.sender_did,
            ))
        elif args.validation_command == "expire":
            print_validation_attempt(expire_validation(validation_store, args.validation_id))
        elif args.validation_command == "record-response":
            print_validation_attempt(record_validation_response(
                validation_store,
                args.validation_id,
                Path(args.file),
                sender_did=args.sender_did,
                room=args.room,
                generation=args.generation,
                seq=args.seq,
                timestamp=args.timestamp,
            ))
        elif args.validation_command == "evaluate":
            print_validation_attempt(evaluate_validation(validation_store, args.validation_id))
        elif args.validation_command == "history":
            print_validation_history(validation_store, args.did)
        elif args.validation_command == "export-message":
            print(export_validation_message(validation_store, args.validation_id))
        return
    if args.command == "verification":
        if args.verification_command == "export-request":
            request = export_signing_verification_request(
                args.output,
                requester_did=args.requester_did,
                target_agent_did=args.target_agent_did,
                created_at=args.created_at,
                operator_group=args.operator_group,
            )
            print(json.dumps({
                "status": "REQUEST_CREATED",
                "request_id": request["request_id"],
                "output": str(args.output),
                "verification_mode": request["verification_mode"],
                "network_writes": 0,
                "private_key_accesses": 0,
                "tclk_settlement_actions": 0,
            }, indent=2, sort_keys=True))
        elif args.verification_command == "ingest-result":
            record = ingest_normalized_bench_result(args.normalized_result, verification_evidence_store)
            print(json.dumps({
                "status": "ROUTER_INGESTED_EVIDENCE",
                "request_id": record["classification"]["request_id"],
                "evidence_class": record["classification"]["evidence_class"],
                "same_operator": record["classification"]["same_operator"],
                "independent_reputation": record["classification"]["independent_reputation"],
                "capability_support": record["classification"]["capability_support"],
                "network_writes": 0,
                "private_key_accesses": 0,
                "tclk_settlement_actions": 0,
            }, indent=2, sort_keys=True))
        elif args.verification_command == "lifecycle-report":
            report = verification_lifecycle_report(
                args.request,
                args.scout_preview,
                args.bench_result,
                args.scout_normalized,
                verification_evidence_store,
            )
            print(json.dumps(report, indent=2, sort_keys=True))
        return
    if args.command == "identity":
        if args.identity_command == "init":
            metadata = create_router_identity(state_dir)
            print("FLOP Router identity created.")
            print(f"DID: {metadata['did']}")
            print(f"state_dir: {state_dir.expanduser()}")
            print("private key: encrypted at rest")
            print("network writes: 0")
        elif args.identity_command == "verify":
            result = verify_router_identity(state_dir)
            print("FLOP Router identity verified.")
            print(f"DID: {result['did']}")
            print(f"key_type: {result['key_type']}")
            print(f"operator_group: {result['operator_group']}")
            print("encrypted_private_key: YES")
            print("network writes: 0")
        elif args.identity_command == "show":
            metadata = load_router_identity_metadata(state_dir)
            print("FLOP Router identity")
            print("--------------------")
            for key in ("did", "key_type", "created_at", "operator_group", "canonical_room", "mailbox"):
                print(f"{key}: {metadata.get(key)}")
            print("private_key_accessed: NO")
            print("network writes: 0")
        return
    if args.command == "ingest-export":
        total, added, digest = ingest_export(Path(args.jsonl), Path(args.manifest), ingest_store)
        print("Technocore export ingestion")
        print("---------------------------\n")
        print(f"source: {args.jsonl}")
        print(f"manifest: {args.manifest}")
        print(f"source export hash: {digest}")
        print(f"records read: {total}")
        print(f"records added: {added}")
        print(f"records unchanged: {total - added}")
        print("No content executed. No Technocore writes performed.")
        return
    if args.command == "evidence":
        print_evidence(db_path, args.did, args.capability, ingest_store)
        return
    if args.command == "interactions":
        print_interactions(db_path, args.did)
        return

    profiles = load_profiles(db_path, validation_store, ingest_store, tclk_store)
    if args.command == "profile":
        agent_profile = profiles.get(args.did)
        if not agent_profile:
            raise SystemExit(f"No signed DID profile found for {args.did}")
        print_profile(agent_profile)
    elif args.command == "route":
        print_route(Router(profiles).route(args.task, top=args.top))
    elif args.command == "plan-execution":
        constraints = ExecutionConstraints(
            asset=args.asset,
            max_amount=args.max_amount,
            allowed_rails=[item for item in args.allowed_rails.split(",") if item],
            allowed_lock_types=[item for item in args.allowed_lock_types.split(",") if item],
            deadline=args.deadline,
            minimum_claim_window=args.minimum_claim_window,
            verification_required=args.verification_required,
            verification_mode=args.verification_mode,
            arbitration_required=args.arbitration_required,
            job_proto=args.job_proto,
            job_id=args.job_id,
            min_independent_operator_groups=args.min_independent_operator_groups,
        )
        print_execution_plan(create_execution_plan(args.task, profiles, constraints))
    elif args.command == "compose":
        print_team(Router(profiles).compose(args.task, max_agents=args.max_agents))
    elif args.command == "search-agents":
        print_route(RoutingResult(task=analyze_task(args.query), candidates=search_agents(args.query, profiles, top=args.top), weights=ROUTING_WEIGHTS))
    elif args.command == "explain":
        candidate = Router(profiles).explain(args.task, args.did)
        if not candidate:
            raise SystemExit(f"No signed DID profile found for {args.did}")
        print_explain(analyze_task(args.task), candidate)
    elif args.command == "explain-team":
        print_team(Router(profiles).compose(args.task, max_agents=args.max_agents), explain=True)


if __name__ == "__main__":
    main()
