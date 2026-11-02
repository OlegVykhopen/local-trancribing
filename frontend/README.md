# Transcribing Studio — frontend

React + TypeScript + Vite + Tailwind UI for the FastAPI backend in `../app/`.

## Dev workflow

The dev server proxies `/api` to `127.0.0.1:8756` (see `vite.config.ts`), so the backend must be running:

```bash
# terminal 1 — backend (NO_BROWSER=1 skips auto-opening the built app)
cd .. && NO_BROWSER=1 ./run.sh

# terminal 2 — frontend with hot reload
npm run dev
```

## Build for run.sh

`../run.sh` serves `frontend/dist` from the backend process:

```bash
npm run build
```

## Tests & checks

```bash
npx vitest run   # unit tests (jsdom)
npx tsc -b       # typecheck
npm run lint     # oxlint
```
