# CloudSentry

An autonomous FinOps platform that turns cloud-cost findings into **evidence-backed, reversible infrastructure changes** — then verifies whether the predicted savings were actually realized.

CloudSentry is built as a real product and doubles as a portfolio-ready demonstration of closed-loop cloud cost optimization: observe, diagnose, propose, approve, execute, verify, and learn.

## Product in one loop

```text
Observe → Diagnose → Propose → Simulate → Approve → Execute → Verify → Learn
```

Most cost tools stop at recommendations. CloudSentry owns the harder questions: Is the change safe? What depends on this resource? How do we roll back? Did we actually save money?

## Locked v1 decisions

| Decision | Choice |
| --- | --- |
| Goal | Real product that also works as a portfolio demo |
| Autonomy | **Approval-required** — humans must approve before execution |
| Cloud approach | AWS-like **simulator first**, real AWS adapters later |
| Backend | Python + FastAPI |
| Frontend | Next.js / React |
| Database | PostgreSQL |
| Execution style | Prefer Terraform / IaC change generation over raw API mutation |

See [docs/product-overview.md](docs/product-overview.md) for the full north-star description.

## Repository layout

```text
cloudsentry/
├── docs/           # Product and process documentation
├── api/            # FastAPI backend (health skeleton)
├── worker/         # Background worker (no-op skeleton)
├── simulator/      # AWS-like fake cloud environment (planned)
├── web/            # Next.js app shell
└── terraform/      # IaC templates / generated change examples (planned)
```

The API skeleton is documented in [api/README.md](api/README.md). The web shell is documented in [web/README.md](web/README.md). The worker skeleton is documented in [worker/README.md](worker/README.md). The other application packages are not scaffolded yet.

## Documentation

- [Product overview](docs/product-overview.md) — what we are building and why
- [Git standards](docs/git-standards.md) — branching, commits, PRs, bootstrap
- [API](api/README.md) — how to run the backend locally
- [Web](web/README.md) — how to run the frontend locally
- [Worker](worker/README.md) — how to run the worker locally

## Development workflow

We use long-lived `main` and `dev` branches. All feature work happens on short-lived, issue-linked task branches merged into `dev` via pull request. Details: [docs/git-standards.md](docs/git-standards.md).

## Status

**API, web, and worker shells.** `GET /health` is available from [api/README.md](api/README.md). The Next.js home page is available from [web/README.md](web/README.md). The worker no-op job is available from [worker/README.md](worker/README.md). Next work follows the phased plan in the product overview (simulator → inventory → detectors → proposals → approval → execution → verification → dashboard).
