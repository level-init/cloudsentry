# CloudSentry Product Overview

This document is the shared north star for CloudSentry. When scope debates come up, prefer this file over chat history.

## 1. What we are building

CloudSentry is a **closed-loop FinOps system**.

It continuously inspects cloud infrastructure, finds waste and inefficient patterns, proposes risk-aware optimization plans, waits for human approval, executes approved changes safely (preferably through infrastructure as code), verifies whether predicted savings were realized, and learns from prediction errors.

### Product statement

> An autonomous FinOps platform that converts cloud-cost recommendations into evidence-backed, reversible infrastructure changes.

### Core operating loop

```text
Observe → Diagnose → Propose → Simulate → Approve → Execute → Verify → Learn
```

That full loop is the product. Recommendation lists alone are not enough.

## 2. Problem

Cloud waste rarely comes from one obvious mistake. It usually comes from idle resources, oversizing, poor pricing choices, expensive storage tiers, duplicate stacks, always-on development environments, weak ownership, and fear of deleting anything because blast radius is unclear.

Existing tools surface suggestions. Engineers still need answers to:

- Is this resource actually safe to shut down?
- Does another service depend on it?
- Is the inactivity temporary?
- Could downsizing hurt latency or availability?
- What happens at peak demand?
- How do we reverse the change?
- Did the recommendation really save money afterward?

CloudSentry is designed to answer those questions with evidence, policy, and measurement.

## 3. Differentiator

The differentiator is not “AI agents.”

It is the combination of:

- Financial impact estimation
- Dependency awareness
- Reliability analysis
- Policy-controlled execution
- Automated rollback paths
- Post-change measurement
- Learning from prediction error

### Reward function

The system is **not** rewarded for recommending the largest savings.  
It is rewarded for producing **verified savings without violating operational constraints**.

### Design principle

> AI proposes and explains. Deterministic systems validate, constrain, and execute.

## 4. Central object: Optimization Proposal

Everything important flows through one lifecycle object:

```text
Finding
  → Optimization Proposal
  → Risk Assessment
  → Approval
  → Execution Run
  → Verification Result
  → Realized Savings Record
```

A proposal carries:

- affected resources
- category (idle, rightsizing, scheduling, storage, etc.)
- current / predicted cost and savings
- confidence and risk score
- evidence, dependencies, preconditions
- proposed actions and rollback plan
- approval, execution, and verification status
- realized savings after measurement

## 5. System roles (pipeline stages)

These are specialist stages with different authority — not peer chatbots sharing one prompt.

| Stage | Job |
| --- | --- |
| Inventory / telemetry | Build shared truth: resources, tags, metrics, billing, deps |
| Usage analysis | Detect idle / underused / oversized waste |
| Architecture analysis | Detect expensive architectural patterns (later) |
| Pricing strategy | Recommend purchase / commitment models (later) |
| Reliability / risk | Veto or soften unsafe proposals |
| Planning | Emit machine-readable change plans |
| Approval | Human gate (v1 required) |
| Execution | Apply via Terraform / guarded workflows |
| Verification | Compare predicted vs realized savings + ops impact |
| Learning | Calibrate future estimates from outcomes |

### Deterministic vs AI

**Deterministic code owns:**

- billing math and savings calculation
- metric aggregation and thresholds
- policy enforcement
- dependency checks
- execution and rollback triggers
- verification baselines

**AI assists with:**

- explaining recommendations
- summarizing tradeoffs
- drafting plans / PR descriptions
- interpreting unusual patterns and owner feedback

AI must not freely mutate infrastructure.

## 6. Locked product decisions

| Topic | Decision |
| --- | --- |
| Goal | Real product **and** portfolio demo |
| Stack | FastAPI + Next.js + PostgreSQL |
| Cloud path | AWS-like simulator first; real AWS later |
| v1 autonomy | **Approval-required** — no auto-apply without human Approve |
| Preferred execution | Terraform / IaC pull-request style changes |
| Collaboration | GitHub issues + PRs; see git standards |

Approval-required means the system may classify risk (`SAFE_AUTOMATION`, `APPROVAL_REQUIRED`, etc.), but **v1 still waits for a human Approve click before execution**.

## 7. Safety model

Safety is first-class.

Organizations define policies such as:

- allow (for future guarded automation)
- require approval
- prohibit (for example: delete production databases)

Additional safeguards every action should support when applicable:

- dry-run
- dependency verification
- maintenance windows
- canary / blast-radius limits
- rate and budget limits
- approval requirements
- automatic rollback
- post-change monitoring
- immutable audit logging
- idempotent execution
- least-privilege credentials

## 8. MVP scope

Do not start with every cloud provider or every optimization class.

### First recommendation types

1. Idle compute detection
2. Compute rightsizing
3. Development-environment scheduling
4. Unattached storage cleanup
5. Storage lifecycle optimization

### MVP workflow

```text
Inventory ingestion
→ Recommendation generation
→ Savings calculation
→ Risk classification
→ Human approval
→ Terraform change generation
→ Simulated / sandbox execution
→ Post-change savings verification
```

Architecture redesign proposals and reserved-capacity strategy come after this loop works.

## 9. Phased build plan

### Phase 0 — Docs and process

- Product overview, README, git standards
- Empty-repo bootstrap (`main` docs-only, then `dev`)

### Phase 1 — AWS-like simulator

Fake company cloud with accounts, environments, resources, metrics, billing, tags, dependencies, incidents, and planted waste scenarios. Must support controlled apply/rollback so the loop can be proven safely.

### Phase 2 — Data platform

Ingest simulator data into PostgreSQL. Expose inventory, cost, metrics, and dependency queries. Relational dependency model first (no graph DB required for MVP).

### Phase 3 — Detection and proposals

Deterministic detectors for the five MVP types. Create Optimization Proposals with evidence, savings, confidence, rollback, and risk classification including veto behavior.

### Phase 4 — Approval and execution

Dashboard/API approval flow. Generate Terraform (or equivalent IaC) changes. Apply approved plans into the simulator. Audit every run.

### Phase 5 — Verification and learning

Capture baselines, observe post-change windows, compute predicted vs realized savings, record operational impact, store simple calibration lessons.

### Phase 6 — Dashboard product surface

Executive view (spend, potential/approved/realized savings, accuracy) and engineering view (proposal detail, evidence, deps, risk, diff, rollback, post metrics).

### Phase 7 — Deeper intelligence (still on simulator)

Architecture patterns, pricing strategy, agent negotiation/compromise plans, counterfactual cost simulation, canary rightsizing.

### Phase 8 — Real AWS

Read-only adapters first, then recommendation-only on sandbox, then Terraform PRs against real repos. Same proposal lifecycle; swap simulator for AWS adapters. The swap boundary is [docs/simulator-adapter.md](simulator-adapter.md).

## 10. Evaluation

Success is broader than “money saved.”

Track:

- detection precision / recall / false positives
- predicted vs realized savings and prediction error
- incidents, rollbacks, change failure rate
- approval acceptance rate and time from detection to execution
- risk-adjusted realized savings  
  `realized savings − operational damage − implementation cost`

## 11. Demo story we are aiming for

A simulated company with multiple accounts, environments, hundreds of resources, months of metrics/billing, planted waste, dependencies, and incidents.

The demo should show that CloudSentry can:

1. Discover meaningful potential monthly savings
2. Reject a dangerous production change
3. Require approval for an actionable low-risk change
4. Generate a Terraform change
5. Apply it in simulation
6. Detect a regression if one occurs and roll back
7. Report predicted vs realized savings
8. Learn and adjust future estimates

## 12. Non-goals for early versions

- Multi-cloud support on day one
- Fully autonomous production mutation
- LLM-only agents without deterministic validators
- Architecture migrations as the first shipped optimization class
- Perfect forecasting for long reserved-capacity commitments

## 13. How to use this document

- New contributors read this before picking issues
- Scope decisions should point back to phases and MVP types above
- If a feature does not strengthen the closed loop, it waits

Related docs:

- [README](../README.md)
- [Git standards](git-standards.md)
