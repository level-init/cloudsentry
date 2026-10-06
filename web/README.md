# CloudSentry Web

## Run locally

From the repository root:

```bash
cd web
npm install
npm run dev
```

Open `http://localhost:3000`. The page should show CloudSentry.

Copy `web/.env.example` to `web/.env.local` only if you need to change the API base URL. Do not commit `.env` or `.env.local`. The example value is `NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000`.
