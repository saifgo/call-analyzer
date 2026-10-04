# Call Analyzer web UI

React + [coss ui](https://coss.com/ui) (Base UI + Tailwind CSS v4), built with Vite into
`../call_analyzer/web/static`, which the Python server serves. The build output is committed so
`python -m call_analyzer ui` works without Node; the Docker image rebuilds it.

```powershell
npm install
npm run dev     # http://localhost:5173, proxies /api to the Python server on :8765 (start it first)
npm run build   # after changing the UI: type-checks and rewrites ../call_analyzer/web/static
```

- `src/components/ui/`: coss components, added with `npx shadcn@latest add @coss/<name>`. Keep them as shipped.
- `src/pages/`: one file per screen; `src/lib/`: API client, hash router, job polling, Arabic/French bidi helpers.
