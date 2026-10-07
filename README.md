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
├── docker-compose.yml
├── docs/           # Product and process documentation
├── api/            # FastAPI backend (health skeleton)
├── worker/         # Background worker (no-op skeleton)
├── simulator/      # AWS-like simulator (health skeleton, port 8001)
├── web/            # Next.js app shell
└── terraform/      # IaC templates / generated change examples (planned)
```

The API skeleton is documented in [api/README.md](api/README.md). The web shell is documented in [web/README.md](web/README.md). The worker skeleton is documented in [worker/README.md](worker/README.md). The simulator skeleton is documented in [simulator/README.md](simulator/README.md). Local Postgres is documented below. Terraform is not scaffolded yet.

## Documentation

- [Product overview](docs/product-overview.md) — what we are building and why
- [Git standards](docs/git-standards.md) — branching, commits, PRs, bootstrap
- [API](api/README.md) — how to run the backend locally, including `/docs`
- [Web](web/README.md) — how to run the frontend locally
- [Worker](worker/README.md) — how to run the worker locally
- [Simulator](simulator/README.md) — how to run the simulator locally

## Quickstart

From the repository root:

```bash
make install
make compose-up
```

`make install` creates `.venv`, installs the Python packages and dev tools, and installs the web dependencies. `make compose-up` copies `.env.example` to `.env` when `.env` is missing, then starts Postgres. `.env` is gitignored.

Start each process in its own terminal. These keep running until you stop them with Ctrl+C:

```bash
make run-api
make run-web
make run-simulator
make run-worker
```

| Command | Address |
| --- | --- |
| `make run-api` | http://127.0.0.1:8000/health and http://127.0.0.1:8000/docs |
| `make run-simulator` | http://127.0.0.1:8001/health |
| `make run-web` | http://localhost:3000 |
| `make run-worker` | logs `worker ok`, then exits |

`make migrate` applies the Alembic migrations to the Compose database. `make migrate-down` removes those tables. Run both from the repository root after `make install` and `make compose-up`. Postgres listens on `localhost:5432`. The API and worker read `DATABASE_URL` from `.env`. The application does not query these tables yet.

## Python checks

From the repository root, after `make install`:

```bash
make lint
make test
```

`make lint` runs Ruff on `api`, `worker`, and `simulator`. `make test` runs pytest and discovers the tests in those packages. Frontend lint is separate and not part of these commands.

## Pull request checks

Pull requests into `dev` and `main` run `.github/workflows/ci.yml`. Both of these checks must pass:

- **Python lint and test** runs `make lint` and `make test`.
- **Web lint and build** runs `npm run lint` and `npm run build` in `web/`.

A lint failure fails the check. This workflow does not deploy the app.

## Development workflow

We use long-lived `main` and `dev` branches. All feature work happens on short-lived, issue-linked task branches merged into `dev` via pull request. Details: [docs/git-standards.md](docs/git-standards.md).

## Status

**API, web, worker, and simulator shells.** `GET /health` for the API is documented in [api/README.md](api/README.md). The Next.js home page is documented in [web/README.md](web/README.md). The worker no-op job is documented in [worker/README.md](worker/README.md). The simulator health check is documented in [simulator/README.md](simulator/README.md). Next work follows the phased plan in the product overview (inventory → detectors → proposals → approval → execution → verification → dashboard).
