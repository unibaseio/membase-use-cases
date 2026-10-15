# Working in this repo

Each demo is a small app that shows one thing long-term memory makes possible. It runs against
the real Membase API and a real model. `02-book-memory/` is the reference: copy its shape.

## A demo's layout

```
NN-name/
  app.py          FastAPI server: demokit.web.create_app(title, HERE, mode=mem.mode); run(app, port=87NN)
  static/         index.html (+ any js/css); link /kit/kit.css and import from /kit/kit.js
  README.md       what it shows, "Shows:" and "Base:" lines, how to run, what to try
  smoke.py        the demo's flow end to end against the real API; prints OK or fails with why
  seed.py / load.py   synthetic or public-domain data, when the demo needs some
  docs/screenshot.png
```

- **Port:** `87NN`, where NN is the demo's number.
- **Memory:** use `demokit.Memory(demo_dir_name, user=..., default_mode="local"|"hosted")`.
  Local mode keeps one directory per `user`, which is how an app keeps its end users apart.
  Hosted mode needs containers that already exist in the account; `scripts/bootstrap_hosted.py`
  makes a test account with them.
- **Writes off the request path:** use `demokit.writes.BackgroundWriter` on the local engine
  (one person's writes run in order; `pending`, `error` and `flush()` are there for the page).
  On hosted, use `demokit.writes.HostedQueue`. It waits for each learning run to finish before
  starting the next write (see that module for why).
- **Dated memories:** use `demokit.dated` (`remember_sessions`, `recall`) when a memory needs the
  time the thing happened rather than the time of the write. This works on the local engine only.
- **Model:** use `demokit.llm` (`chat`, `stream`, `json_reply`, `vision`, `transcribe`). The
  default model is `gpt-4.1-mini`, set by `DEMO_MODEL`.
- **Pages:** plain HTML and ES modules with no build step and no CDN. Use canvas or SVG for
  visuals. The pages are in English.

## Rules

- **No mocks, no fake success.** Show an error in the UI; never swallow it.
- **Count your hosted writes.** Each hosted write starts a learning run in the account's agent,
  so write once per finished exchange or session. Local writes take about 5–8 s each; run them
  off the request path when the user should not wait.
- **Wait out a cold hosted account.** The first search on a cold hosted account can come back as
  an error while the account wakes. Use `recall(..., wait=60)`.
- **Use synthetic or public-domain data only.** No real people. Health and family demos say
  plainly that they are demos, not services.
- **Stay in your demo's directory.** Do not edit `demokit/`, `pyproject.toml` or other demos.
  If you need something from them, add a helper in your demo and report what you needed.

## Verifying

- Run `.venv/bin/python NN-name/smoke.py` on the demo's default base. A local smoke run uses a
  fresh `DEMO_DATA_DIR`. A hosted smoke run uses its own test account:
  `.venv/bin/python scripts/bootstrap_hosted.py --name NN-name --containers ...`, then
  `DEMO_ENV_FILE=.secrets/NN-name.env`.
- Take a screenshot after one real interaction (Playwright: `~/miniconda3/bin/python` has it,
  with Chromium). Save it to `docs/screenshot.png`, then look at it.
