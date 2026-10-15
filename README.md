# Collaplex Agent OS

[![License: AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-blue?style=flat-square)](LICENSE)

**The program keeps the state. The model only reasons.**

Collaplex Agent OS is a local-first agent runtime for real machine work. It reads the actual state of the machine and the material you point it at, decides what has to be done, hands the doing to tool-bearing executors, and brings the output and the exit code back unchanged. Every step is visible while it runs, and every figure in an answer can be traced to the command output it came from.

Repository `collaplex-agent` · CLI `collaplex-agent` · Source [collaplex.me/git/edgevoid/collaplex-agent](https://collaplex.me/git/edgevoid/collaplex-agent)

---

## Why it exists

Mainstream agent frameworks treat context as the model's private business: the model summarises, the model decides what to forget, the model remembers. That approach charges three taxes.

| Tax | Where it comes from | What it costs |
|---|---|---|
| **Compression tax** | The window fills up, so the *model* summarises its own history | Tokens burned at every compaction, and the summary grows vaguer each time — the model has no idea what will still matter later |
| **Guessing tax** | Tool calls are written from the model's recollection of an interface | A wrong call stays in the context and contaminates every reasoning step after it |
| **Noise tax** | Retrieval hits and raw history are dumped in wholesale | Most of the window goes on managing the window instead of doing the work |

It snowballs: *a few turns → compaction → detail lost → wrong answer → compaction again*. By the end the model cannot reliably restate what it said ten minutes ago.

Local deployment sharpens the point. On an 8 GB GPU a 14B model leaves roughly 8K of context, while a serious agent system prompt alone runs past 13K. Leaving context management to the model is not an option on local hardware.

**So context is not the model's job.** The model reasons. The program remembers.

---

## What it does

Capabilities below are verified, not designed. Each row states what was actually measured.

| # | Capability | Evidence |
|---|---|---|
| 1 | **Context allocated by budget, not by "stuff it in"** | The window is requested from the API; the skill budget is 40% of it; output and read-only regions are subtracted, and the remainder is the memory allowance |
| 2 | **Hot memory drains to cold memory on its own** | End-to-end run: hot store 377 → 375, cold store 12 → 18, timestamps updated, driven entirely by cron |
| 3 | **Hypernym queries still recall** | Alias path measured 0.5178 (miss) → **0.8163** (hit) |
| 4 | **Interchangeable models, zero code changes** | Switch local llama.cpp ↔ cloud API by editing `OPENAI_BASE_URL` in `.env` |
| 5 | **Prompts live outside the code** | `grep '^[A-Z_]*_SYSTEM =' *.py` → **0 hits**; they are files under `config/skills/` |
| 6 | **Failures degrade explicitly, never silently** | Unreachable endpoint, bad key, wrong model name — four distinct messages, no raw traceback |
| 7 | **Shipped self-check** | Config, dependencies, libraries, code, structure and timers; exit code `0` when clean, `1` when not — usable as a CI or boot gate |
| 8 | **Idempotent cleanup** | Interrupt it halfway, rerun once, it catches up without double-counting |
| 9 | **Long jobs outlive the conversation** | A long task goes to the job ledger: it keeps a log on disk, can be resumed, never holds the foreground, and reports `started` / `finished · exit code` inside the process panel |
| 10 | **Answers are checked against the run** | Hard figures in an answer — percentages, sizes, core counts, temperatures — are matched against this round's real command output with plain regex, no extra model call; mismatches are flagged without rewriting the answer |
| 11 | **Everything the model sees is editable** | Per-role endpoints and models, memory counts, a retrieval test entry point and the skill list all live on the settings page |
| 12 | **One entry point** | `cli.py`: `web`, `自检` / `selfcheck`, `模型` / `models`, `chat` |

---

## Architecture at a glance

```
                 ┌───────────────────────────────┐
  question ─────▶│  the program  (memory side)   │
                 │  · context budget             │
                 │  · two-tier memory store      │
                 │  · retrieval + command library│
                 │  · ledger of what really ran  │
                 └───────────────┬───────────────┘
                                 │  decides, writes
                 ┌───────────────▼───────────────┐
                 │  the model  (reasoning side)  │
                 └───────────────┬───────────────┘
                                 │  declares the command
                 ┌───────────────▼───────────────┐
                 │  executors  (the hands)       │
                 │  run it, return stdout/stderr │
                 │  and the exit code            │
                 └───────────────────────────────┘
```

**Three roles, each with its own endpoint and model.** All of them are interchangeable and all default to the main line:

- **main** — answers and writes.
- **sub** — works out what needs looking up, and decides whether a skill is required.
- **exec** — actually runs the commands.

**Two memory tiers.** A hot store holds the current work; a scheduled pass drains what is no longer needed into a cold store. The program owns both, so compaction is never delegated to the model.

**A skill is a directory.** `SKILL.md` for the model, `metadata.json` for the program, the corpus inside it. Copy the directory to another machine and it runs there.

---

## Requirements

- Python **3.11+**
- An OpenAI-compatible endpoint — a local [llama.cpp](https://github.com/ggml-org/llama.cpp) server, or any cloud provider
- PostgreSQL with `pgvector` — optional, needed only when the memory store backend is `pg`
- Linux (developed and tested on Ubuntu). Windows packaging is in progress.

Direct runtime dependencies are deliberately few — `openai`, `python-dotenv`, `numpy`, `psycopg[binary]` and `websocket-client` (see `requirements.txt`). Around them, the stack is llama.cpp for local inference, PostgreSQL with pgvector for the memory store, and `uv` for the environment.

---

## Install

```bash
git clone https://collaplex.me/git/edgevoid/collaplex-agent.git
cd collaplex-agent
uv venv && uv pip install -r requirements.txt
cp .env.example .env          # then edit .env
```

Below, `PY` means `.venv/bin/python` in this checkout. (`source .venv/bin/activate` also works, after which plain `python` does.)

## Configure

Every model call is read from `.env`. Nothing is hard-coded in the source.

```ini
# Main line — shared by the main, exec and sub agents
OPENAI_BASE_URL=https://api.example.com/v1
OPENAI_MODEL=your-model-name
OPENAI_API_KEY=sk-...

# Embedding model, used by the retrieval path
EMBEDDING_BASE_URL=http://127.0.0.1:8199/v1
EMBEDDING_MODEL=qwen3-embedding-0.6b

# Memory store — required when the store backend is "pg"
RAG_PG_DSN=host=/var/run/postgresql dbname=collaplex_rag user=collaplex password=CHANGE_ME
```

To run fully locally, point the three main-line keys at a local server:

```ini
OPENAI_BASE_URL=http://127.0.0.1:8790/v1
OPENAI_MODEL=qwen3-vl-8b
OPENAI_API_KEY=local
```

`EXEC_*` and `SUBAGENT_*` optionally give the exec agent and the sub agent their own endpoints; both fall back to the main line when left empty. That is useful when the local model is too slow for judgement work but perfectly good at execution.

## Run

```bash
PY cli.py 自检         # self-check: config / dependencies / libraries / code / structure / timers
PY cli.py 模型 start   # start local model services (llama.cpp on :8790, embeddings on :8199)
PY cli.py web          # web interface
PY cli.py chat         # command-line chat
```

`cli.py` accepts the English aliases as well: `selfcheck`, `models`.

In the web interface you can ask a question or dispatch a task. Answers arrive next to a process panel that shows the judgement, the skill that was selected, the command that actually ran and its output — which is also where long-job status is reported.

---

## Skills

14 skills ship with the runtime:

| Skill | Purpose | Docs |
|---|---|---|
| `linux` | Command library for system work: disk, ports, services, processes, logs | 65 entries · 1,325 lines |
| `ops` | Operations handbook for this runtime itself | 29 |
| `file` | Reading, writing and verifying code changes | 17 |
| `kali` | Security self-checks | 16 |
| `math` | Deterministic arithmetic — never routed through a model | 13 |
| `vision` | Looking at images | 13 |
| `search` | Fetching pages from the network | 10 |
| `skill_search` | Routing a question to the right skill | 6 |
| `rag` | Chunking, retrieval and cleanup | — |
| `seek` | The main skill text | 1 |
| `outsource` | Budgeted help from an outside model, used when the local one stalls | 1 |
| `mtp` | Cross-checking one model's answer with another | 1 |
| `timer` | Scheduled work | 1 |
| `orchestra` | Multi-step pipelines | 1 |

To add one: create a directory under `skill/`, write `SKILL.md` for the model and `metadata.json` for the program, put the corpus inside, then rebuild the index.

---

## Repository layout

```
cli.py          single entry point (web / selfcheck / models / chat)
main.py         the main agent loop
sub_agent.py    judgement: what to look up, whether a skill is needed
exec_agent.py   command extraction, execution, output capture
web/            web interface (server, bridge, static assets)
config/         externalised configuration and prompt files
skill/          14 skills, each a self-contained directory
state/          runs, job ledger, conversations
logs/           run logs and job logs
dist/           build output
```

---

## Status

- **Source available now**, under AGPL-3.0.
- **Beta by invitation.** A `.deb`, a drop-in `.tar.zst` and a Windows installer (bundled database and local model) are being finished and ship with the beta.
- Models and credentials are never bundled. Configure endpoints and keys through `.env`.

---

## License

GNU Affero General Public License v3.0 — see [LICENSE](LICENSE).

Copyright (c) 2026 Collaplex Studio (edgevoid).

AGPL-3.0 lets you use, study, modify and redistribute this software, including as a network service, **provided that** users interacting with it over a network are offered the corresponding source. To build on it under different terms, get in touch.

## Links

- Source and issues: <https://collaplex.me/git/edgevoid/collaplex-agent>
- Project site: <https://collaplex.me>
- 中文文档（含完整架构设计）: [docs/README.zh.md](docs/README.zh.md)
