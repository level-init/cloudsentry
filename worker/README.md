# CloudSentry Worker

Background jobs will live here. This skeleton runs one no-op job and exits. It does not import the API.

## Run locally

From the repository root:

```bash
source .venv/bin/activate
pip install -e ./worker
cloudsentry-worker
```

Expected log line: `worker ok`. The process exits with code 0.

`DATABASE_URL` is optional. The default in `worker/config.py` is a placeholder and this job does not connect to Postgres.
