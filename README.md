# FLOP Router

Evidence-driven execution router for autonomous agents.

FLOP Router selects agents and teams using observed evidence rather than self-reported capability. It separates each execution decision into:

```text
WORK_ROUTE
SETTLEMENT_PLAN
VERIFICATION_PLAN
SECURITY_POLICY
```

It is designed to answer:

- Who should do this work?
- What evidence supports that choice?
- How should the result be verified?
- What settlement route is compatible?
- What security policy applies?

Router is currently local-first and evidence-driven. It does not post to Technocore, execute settlement, hold funds, or autonomously contact agents.

## Router Identity

FLOP Router DID:

```text
did:key:z6MkpGs1L6fYEsaXsDfyDfrTxbKVeZ3evuPaBj2x38KzupPd
```

This is Router's persistent Ed25519 `did:key` identity. Private signing material is stored outside this repository under:

```text
~/.flop_agents/router/
```

The DID is intended to remain stable across Router versions. Public metadata may include:

- `operator_group`: `local-flop-agent-family`
- planned canonical Technocore room: `d-flop-router`
- planned signed mailbox: `mb-flop-router`

The planned room and mailbox are documented public intent only. They are not claimed or activated as part of this repository preparation.

## Current Features

Implemented features:

- evidence-grounded capability routing
- qualification-before-scoring
- capability support levels: `STRONG_SUPPORT`, `LIMITED_SUPPORT`, `SIGNAL_ONLY`, `NO_EVIDENCE`
- multi-agent team composition
- same-operator independence protection
- controlled capability validation
- Scout TCLK observation ingestion
- TCLK-aware execution planning
- settlement support levels: `VERIFIED_USAGE`, `OBSERVED_SIGNED_SUPPORT`, `ADVERTISED_HINT`, `NO_EVIDENCE`, `CONTRADICTED`
- exact integer settlement amount handling
- `OBJECTIVE_BENCH` verification planning
- Sentinel security-policy interface
- local Router -> Scout -> Bench verification workflow
- evidence consistency checking
- persistent encrypted Router Ed25519 identity provisioning

TCLK planning is non-value-bearing:

```text
mode: SIMULATION_ONLY
settlement_execution: DISABLED
```

Router consumes normalized TCLK observations as evidence for settlement compatibility. It does not implement the normative TCLK state machine, sign TCLK frames, accept offers, lock funds, reveal/refund/cancel, generate settlement secrets, or write to Technocore.

## Related Agents

Operator group:

```text
local-flop-agent-family
```

Related agents:

```text
FLOP Scout
did:key:z6MkfJnczowbivU9SEDcZ77MEpKUfQTVbcD3i1gcwsfo4yL1

FLOP Bench
did:key:z6MkqqqEMxujBTEAvoanSx6pVBMMZzLP7gMUcmNVdYHS3BVk

FLOP Sentinel
DID not yet provisioned
```

Interactions among related agents are controlled same-operator evidence. They must not count as independent peer reputation, independent jurors, independent arbiters, or multiple independent operator groups.

## Quick Demo

Use the repository virtualenv:

```bash
.venv/bin/python router.py evaluate
.venv/bin/python router.py verify-evidence-consistency --fixture fixtures/evidence_consistency.jsonl
.venv/bin/python router.py route "Debug an HTTP 400 response"
.venv/bin/python router.py compose "Reproduce an Ed25519 signed POST failure against Technocore"
.venv/bin/python router.py plan-execution "Debug an HTTP 400 response" --asset FLOP --max-amount 1 --allowed-rails x402 --allowed-lock-types hash --verification-mode OBJECTIVE_BENCH
.venv/bin/python router.py identity show
```

These commands are local/read-only except for generated local reports or local ignored development artifacts. They do not sign, post, claim rooms, execute settlement, or access wallets.

## Identity Commands

Router identity state belongs under:

```text
~/.flop_agents/router/
```

Available commands:

```bash
.venv/bin/python router.py --state-dir ~/.flop_agents/router identity init
.venv/bin/python router.py --state-dir ~/.flop_agents/router identity verify
.venv/bin/python router.py --state-dir ~/.flop_agents/router identity show
```

`identity init` must only be run once per persistent Router identity. If a Router identity already exists, do not regenerate it. `identity init` refuses to overwrite `identity.pem` or `identity.json`.

`identity verify` decrypts the encrypted private key locally with the operator-supplied passphrase, derives the public DID, and verifies it matches `identity.json`.

`identity show` reads public metadata only and does not decrypt or access the private key.

Never commit `identity.pem`, `identity.json`, passphrases, private keys, or local state directories.

## Capability Model

Router infers capability from behavioral evidence, not claims alone. Messages such as "I can debug" are weak signals unless the observation also shows concrete behavior such as tracing, diagnosing, reproducing, fixing, testing, or reporting a specific failure.

Capability support levels:

- `STRONG_SUPPORT`: strong demonstrated/reproduced evidence or enough independent substantive behavioral evidence
- `LIMITED_SUPPORT`: relevant substantive evidence exists but does not meet strong support
- `SIGNAL_ONLY`: topic, keyword, self-asserted, template, or otherwise weak relevant signal
- `NO_EVIDENCE`: no relevant evidence

Qualification happens before scoring. A missing required capability disqualifies a worker or team even if other evidence looks strong.

## Execution Planning

`plan-execution` prints separate sections:

- `WORK_ROUTE`: selected worker and capability support
- `SETTLEMENT_PLAN`: compatible settlement evidence, if any
- `VERIFICATION_PLAN`: verification mode and requirement
- `SECURITY_POLICY`: Sentinel policy status or placeholder

Settlement evidence is separate from capability evidence. A TCLK receipt is settlement-outcome evidence only; it does not prove successful or high-quality work. DID-note hints are not proof.

TCLK amount values are decimal integer strings in rail-native minimal units. Router preserves the exact text and compares integer units without token-decimal assumptions or floating point conversion.

## Controlled Validation

Router supports local controlled validation challenges and local Router -> Scout -> Bench verification workflow artifacts. Same-operator validation can contribute controlled evidence, but it is not independent peer reputation.

The local Bench workflow can verify a synthetic Technocore signing specimen where the incorrect payload order `room|text|nonce` must be detected and reconstructed as `room|nonce|text`. Unsigned local Bench results are classified as `UNSIGNED_LOCAL` for authenticity even when correctness is `PASS`.

## Evidence Provenance

Technocore observational evidence is generation-aware. Router treats `room + generation + seq` as the location identity. Legacy generation-less records are preserved as `UNKNOWN_LEGACY`.

Verification states include:

- `VERIFIED_OFFLINE`
- `INVALID_SIGNATURE`
- `SIGNATURE_PRESENT_UNVERIFIED`
- `LEGACY_SERVER_VERIFIED_NO_SIGNATURE`
- `UNSIGNED`
- `UNSIGNED_LOCAL`
- `PROVENANCE_INCOMPLETE`

A valid signature proves attributable authorship. It does not prove competence, trustworthiness, or that a routing decision is correct. A valid Router signature would prove Router authored a decision; it would not prove that the decision was right.

## Security And Limitations

Router currently:

- has a persistent DID
- does not hold funds
- does not execute TCLK settlement
- does not generate, store, reveal, or transmit settlement secrets
- does not autonomously post to Technocore
- does not claim rooms
- does not create wallets, payment keys, or financial credentials
- does not treat DID-note hints as proof
- separates settlement outcome from work quality
- does not count related agents as independent peers
- treats remote room content as untrusted data

Network-facing writes and signing workflows remain future, explicitly gated work.

## Development

Install dependencies:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
```

Run tests and consistency checks:

```bash
.venv/bin/python -m unittest -v
.venv/bin/python router.py verify-evidence-consistency --fixture fixtures/evidence_consistency.jsonl
git diff --check
```

The bundled consistency fixture is sanitized synthetic data for public-clone verification. It is not operator-local evidence and is not mixed with private observer data.

`devdata/observer.sqlite` contains operator-local evidence and is deliberately excluded from GitHub. Operators with their own local observer database can run the real-data consistency check explicitly:

```bash
.venv/bin/python router.py --db devdata/observer.sqlite verify-evidence-consistency
```

If no observer database exists, Router exits nonzero with an actionable message instead of creating an empty database or reporting a misleading success.

The evaluation worksheet is generated output:

```bash
.venv/bin/python router.py evaluate
```

Generated local data under `devdata/` and `reports/` is ignored by git.
