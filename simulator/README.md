# CloudSentry Simulator

AWS-like fake cloud. This skeleton only serves a health check. It does not import the API or the worker.

The API listens on port **8000**. This service listens on port **8001**.

## Run locally

From the repository root:

```bash
source .venv/bin/activate
pip install -e ./simulator
cloudsentry-simulator
```

Then, in a second terminal:

```bash
curl -s -D - http://127.0.0.1:8001/health
```

Expected response: HTTP 200 and `{"status":"ok"}`.

Stop the server with Ctrl+C.
