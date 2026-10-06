<img src="assets/icon.svg" width="64" height="64" alt="">

# Call Analyzer

Pulls sales call recordings from the GoVoice VoIP manager, transcribes them, and uses Claude to give
per-call feedback and coaching reports (team + per agent) on how to improve the pitch.

```
GoVoice list API ──► download mp3 ──► speech-to-text ──► Claude: per-call feedback ──► Claude: coaching report
   (sync)             (download)        (transcribe)            (analyze)                    (report)
```

Everything is stored in `data/calls.db` (SQLite), so every step is resumable and only processes new calls.

**No paid APIs needed:**
- **Speech-to-text** runs locally with [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
  (`large-v3-turbo`), on the NVIDIA GPU if available, otherwise on the CPU. If a recording is stereo
  (agent and customer on separate channels) each side is transcribed separately, giving clean speaker labels.
- **Claude** runs through the Claude Code CLI you're already logged into (`claude -p`), so it uses your
  Claude Pro/Max subscription limits instead of an API key.

ElevenLabs/OpenAI transcription and the Anthropic API remain available as options in `.env`.

## Setup

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt -r requirements-gpu.txt   # skip requirements-gpu.txt without an NVIDIA GPU
copy .env.example .env     # then fill it in
.venv\Scripts\python -m call_analyzer user add <name>   # your login for the web interface
```

1. **GoVoice login**: start the web interface (below) and click **Log in to GoVoice** (Settings, or the prompt
   that appears when a job needs GoVoice). The real GoVoice login page opens in a new tab; sign in as usual and
   the session is captured and saved to `GOVOICE_COOKIE` automatically. See [GoVoice session](#govoice-session).
2. **Recordings folder**: `GOVOICE_RECORDINGS_DIR=govoice_enreg_1759512535`. Leave it empty to auto-detect it
   from the page if it ever changes.
3. **Claude**: make sure `claude` works in a terminal and you're logged in with your subscription.
4. **Whisper**: the model (~1.6 GB) downloads on first use into `WHISPER_MODEL_DIR` (set to `D:\call-analyzer-models`
   because C: is nearly full). Optional tuning: `WHISPER_LANGUAGE=ar` or `fr` if auto-detection picks the wrong
   language, and `WHISPER_PROMPT` with a sample sentence in your calls' style and product names.

### Tunisian Derja models

Stock Whisper handles Tunisian Derja poorly (published word error rates are above 50%). `WHISPER_MODEL` can also be set
to a community model fine-tuned on Derja; switch between models in Settings like with large-v3 / turbo:

| `WHISPER_MODEL` | Model | Notes |
|---|---|---|
| `tunisian-large-v3` | [oddadmix/Whisperv3-tunisian-codeswitch](https://huggingface.co/oddadmix/Whisperv3-tunisian-codeswitch) | large-v3 fine-tuned on ~46K Tunisian utterances with French/English mixed in; 15% WER on its blind test. Most accurate, slower. |
| `arabic-dialectal-turbo` | [oddadmix/whisper-large-v3-turbo-arabic-dialectal-v2](https://huggingface.co/oddadmix/whisper-large-v3-turbo-arabic-dialectal-v2) | turbo fine-tuned on several Arabic dialects including Tunisian. Faster. |

These are published for `transformers`, so the first use downloads and converts them for faster-whisper
(into `WHISPER_MODEL_DIR\ct2`). That needs torch and transformers, once:

```powershell
.venv\Scripts\pip install -r requirements-convert.txt --extra-index-url https://download.pytorch.org/whl/cpu
.venv\Scripts\python -m call_analyzer install-model tunisian-large-v3   # or Settings → Install now
```

These models were trained without timestamps, so the app cuts each call at pauses and transcribes the pieces
in batches (about 10 s per line). `WHISPER_PROMPT` is not used with them, because it makes them repeat words. Keep `WHISPER_LANGUAGE=ar`.
On a laptop, plug in the charger: on battery the GPU is slowed down about 10×. Re-transcribe existing calls to compare (Calls → tick calls → Re-transcribe, or
`transcribe --redo`).
5. **Fill in `context/business.md`**: what you sell, your ideal call, common objections, who is on which
   extension. Claude judges every call against this, so it makes a big difference.

## Web interface

```powershell
.venv\Scripts\python -m call_analyzer ui
```

Opens http://127.0.0.1:8765 in your browser and asks you to sign in:

- **Dashboard**: pipeline progress, per-agent call counts, average score and wins, and one-click actions.
- **Calls**: filter by agent, status, date, length or text; open a call to play the audio, read and **edit the
  transcript**, then "Save & re-analyze"; see the full feedback. Tick several calls to process them in bulk.
- **Pipeline**: choose steps and filters, start or stop a job, and watch the live log.
- **Reports**: read the coaching reports, or generate new ones.
- **Business context**: edit `context/business.md`.
- **Remote agents**: PCs that do the transcription/analysis for a hosted server; see [Remote agents](#remote-agents).
- **Settings**: edit every `.env` value (cookie, models, backends) and run a setup check.
  Turn on **Ongoing mode** (`AUTO_PROCESS`) and, while the UI runs, it fetches new calls from GoVoice every
  `AUTO_PROCESS_MINUTES` (5) and downloads, transcribes and analyzes them. Runs show up on the Pipeline page.
- **CRM tab** (call drawer, next to Feedback and Transcript): looks up the customer's number in your
  [Twenty CRM](https://twenty.com) and lists the matching contacts with their opportunities. Set `CRM_BASE_URL`
  and `CRM_API_KEY` (Twenty: Settings > APIs & Webhooks) in Settings. Numbers are matched on their last 8 digits,
  so `+21694721843` and `94721843` find the same contact (the CRM must store the number without spaces).

The interface is built with React and [coss ui](https://coss.com/ui), with light and dark themes; its source is in
`frontend/` (see `frontend/README.md` to change it).

**Export & share** (on each call):
- **PDF**: feedback + transcript, printed by Microsoft Edge so Arabic/French text is laid out correctly.
  Includes a link to the recording on GoVoice (and the share link, when network sharing is on).
- **HTML with audio**: one file with the recording built in. Send it by WhatsApp or email; it opens in any browser, even offline.
- **Share link**: a private link to a review page with an audio player; can be revoked. Links only work on this
  PC unless `SHARE_ON_LAN=true` (Settings → Sharing, then restart the UI). Other computers can then open
  `/share/...` links and nothing else; the UI, settings and cookie stay local-only.

The UI only listens on your own machine (127.0.0.1) unless `SHARE_ON_LAN=true`. It runs one job at a time,
using the same commands as below.

### GoVoice session

GoVoice sessions expire after about 2 hours of inactivity. The app handles this for you:

- Before a job that talks to GoVoice (sync, download, run, processing new calls) it tests the session. If it has
  expired, a **Log in to GoVoice** dialog opens. Sign in in the tab it opens; the tab closes itself and
  the job starts.
- If the session expires in the middle of a job, the job stops with exit code 3 and the same dialog offers to log
  in and run it again. The CLI prints `GoVoice login needed` in that case.
- While the UI is running it uses the session every 10 minutes so it doesn't expire, and saves any cookie GoVoice
  rotates. The header shows **Log in to GoVoice** whenever the saved session isn't valid.

How it works: `/govoice-login/` serves GoVoice's own login page through this app. Your browser talks to the app, and the app
talks to GoVoice, so the session cookies GoVoice sets on the login request are captured on the server.
Your password is passed to GoVoice and never stored. The cookies go only into `.env`, never to the browser.
This works in Docker and from other computers too. Pasting a `Cookie:` header from the browser's DevTools into
`GOVOICE_COOKIE` (Settings) still works.

**Logins**: everything except share links needs a sign-in. There are two roles:

- **Admin**: full access, including the pipeline, Settings and **Users**.
- **Agent**: a read-only view of their own work. They see the dashboard, calls (audio, transcript and AI feedback)
  and coaching reports of the agent extensions linked to their account, and can export a call or report as PDF.
  An account can be linked to one or more extensions. They can't see the team report or other agents' calls,
  run jobs, edit transcripts, create share links or open Settings.

Admins manage accounts on the **Users** page: add a user, choose the role, tick the extensions and set a password.
The page also lists extensions that have calls but no account yet. Every user can change their own password from
the account menu (bottom left).

From the command line:

```powershell
.venv\Scripts\python -m call_analyzer user add <name>                                  # admin (asks for the password)
.venv\Scripts\python -m call_analyzer user add <name> --role agent --agents 102,103 --name "Ali Ben Salah"
.venv\Scripts\python -m call_analyzer user set <name> --agents 102                     # change role/extensions/name
.venv\Scripts\python -m call_analyzer user passwd <name>   # change password, signs them out everywhere
.venv\Scripts\python -m call_analyzer user delete <name>
.venv\Scripts\python -m call_analyzer user list
```

Accounts created before roles existed stay admins.

## Hosting with Docker

Settings come from environment variables (see `.env.example` for the full list). Anything changed later on
the **Settings** page is saved to `/app/data/.env` inside the data volume and takes precedence over the
environment variables.

### Coolify

1. New resource → your Git repository → build pack **Docker Compose** (file: `docker-compose.yml`).
2. **Environment variables**: at least `ADMIN_USERNAME`, `ADMIN_PASSWORD` (8+ characters), `PUBLIC_URL=https://your.domain`,
   `COOKIE_SECURE=true`, plus the GoVoice and Claude settings.
3. **Domains**: set the `app` service's domain to `https://your.domain:8765` (Coolify routes it to port 8765 and
   handles HTTPS). You can delete the `ports:` lines from `docker-compose.yml` if port 8765 is taken on the server.
4. Deploy, then sign in with `ADMIN_USERNAME` / `ADMIN_PASSWORD`.

### Plain Docker

On a Linux server with Docker and Docker Compose:

```bash
git clone <this repo> call-analyzer && cd call-analyzer
cp .env.example .env && nano .env   # GoVoice cookie, Claude settings, ADMIN_USERNAME / ADMIN_PASSWORD, PUBLIC_URL
docker compose up -d --build
```

The app is on port 8765 (change with `APP_PORT=80 docker compose up -d`). Sign in with `ADMIN_USERNAME` /
`ADMIN_PASSWORD` (the account is created on first start).
Add agents on the **Users** page, or with `docker compose exec app python -m call_analyzer user add <name> --role agent --agents 102`.

**HTTPS** (recommended on the internet): point a domain at the server, open ports 80 and 443, set
`PUBLIC_URL=https://your.domain` and `COOKIE_SECURE=true` in `.env`, then:

```bash
DOMAIN=your.domain docker compose -f docker-compose.yml -f docker-compose.https.yml up -d
```

Caddy gets a Let's Encrypt certificate automatically. Close port 8765 in the firewall so the app is only
reachable through HTTPS.

**Analysis** (Settings, or `.env`):
- `ANALYSIS_BACKEND=claude` uses Claude. `CLAUDE_BACKEND=api` with `ANTHROPIC_API_KEY` is the simplest
  on a server. `CLAUDE_BACKEND=subscription` works too: run `claude setup-token` on your PC and put the
  token in `CLAUDE_CODE_OAUTH_TOKEN`.
- `ANALYSIS_BACKEND=cursor` uses Cursor instead. Paste a user API key from
  [Cursor Dashboard → API Keys](https://cursor.com/dashboard) into `CURSOR_API_KEY`.
- `ANALYSIS_BACKEND=auto` tries Claude first and switches to Cursor when the Claude CLI is missing or
  the session limit is hit.

**Data** lives in Docker volumes: `data` (database, audio, Whisper models, saved settings), `reports`, `context` (business.md).
The first transcription downloads the Whisper model (~1.6 GB) into `data`. Back up with e.g.
`docker compose cp app:/app/data ./backup-data`.

**GPU** (NVIDIA, with the NVIDIA Container Toolkit installed):
`docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build`. Without a GPU, Whisper runs on the
CPU, which is much slower; on a small server consider `TRANSCRIBE_PROVIDER=elevenlabs` or `openai`.

**Tunisian Derja Whisper models** (`tunisian-large-v3`, `arabic-dialectal-turbo`) are converted once on first
use, which needs torch: build with `INSTALL_CONVERT=true docker compose up -d --build` (adds ~1 GB). On Coolify,
add the environment variable `INSTALL_CONVERT=true` as a build variable and redeploy. Converting
`tunisian-large-v3` needs about 6–8 GB of free RAM.

## Remote agents

A hosted server often has no GPU and no Claude login. A **remote agent** is a PC (yours, or a colleague's) that
connects to the server and does the heavy steps, **transcription** (Whisper) and **analysis** (Claude/Cursor), with
its own hardware and logins. The server keeps everything else: GoVoice sync and download, the database, the web
interface.

```
Hosted server                                     Agent PCs (any number)
sync + download from GoVoice                      Whisper on the PC's GPU
task queue (transcribe / analyze)  <-- HTTPS --   Claude with the PC's login
calls, reports, UI                                 (the agent only connects out: no open ports, any router)
```

**Choose where each step runs** in Settings → *Remote agents* (or on the **Remote agents** page):

| `TRANSCRIBE_RUNS_ON` / `ANALYZE_RUNS_ON` | |
|---|---|
| `host` (default) | This server does it, as before. Agents are not used. |
| `agent` | Only agents do it. With none online the calls wait in a queue and are processed as soon as one connects; the server never takes over. |
| `auto` | An agent while one is online, otherwise this server (also when the last agent drops out in the middle of a run). |

The two steps are independent, e.g. transcribe on a PC with a GPU and analyze on the server with an API key.

**Add an agent (any Windows PC, no Python needed)**

1. On the **Remote agents** page click **Add agent** and give it a name. You get a **connection code** (shown once:
   **New token** replaces it if it leaks, **Remove** revokes the agent).
2. Install **Call Analyzer Agent** on the PC with `CallAnalyzerAgent-Setup-<version>.exe` (a normal installer, no
   administrator rights). Use `CallAnalyzerAgent-GPU-Setup-<version>.exe` on a PC with an NVIDIA GPU (it carries
   the CUDA libraries, so it is much bigger). Both are downloaded from the **Get the agent for Windows** section at
   the top of the Remote agents page. An admin puts them there once with **Upload installer** (or copies them
   into the server's `data/downloads` folder; `AGENT_DOWNLOAD_URL` adds an outside link, e.g. a GitHub release).
   A proxy in front of the server must allow request bodies of ~1.2 GB for the GPU installer.
3. The app opens and asks for the connection code. Paste it, click **Connect**. The agent then lives in the
   system tray (near the clock): the dot on its icon shows if it is online, working, or paused, and its menu can
   pause it, open the dashboard or its settings file, and toggle *Start with Windows*. The server's address must
   be reachable from that PC (use `https://`: the token and the recordings travel over it); set `PUBLIC_URL` so
   the code carries the public address.

What the PC still needs for each step: **transcription** needs nothing (Whisper is in the app; models are
downloaded when first used; the Tunisian Derja models are downloaded *from the server*, which converts them once:
Settings → Install now). **Analysis** with `CLAUDE_BACKEND=subscription` needs the Claude Code CLI installed and
signed in on that PC (`claude`); with `api` it needs `ANTHROPIC_API_KEY` in `%LOCALAPPDATA%\CallAnalyzerAgent\.env`.
The Remote agents page tells you what a PC is missing.

Settings, models and the log of the installed app are in `%LOCALAPPDATA%\CallAnalyzerAgent` (they stay when you
update or uninstall). Command line, same as below: `CallAnalyzerAgent.exe login --code ca1.…`, `run`, `status`,
`autostart [--off]`.

**Build the installer** (on a Windows PC with this project's venv; you need to do this when the agent code changes):

```powershell
.venv\Scripts\pip install -r requirements.txt -r requirements-agent.txt     # once
winget install JRSoftware.InnoSetup                                          # once
.\packaging\build_agent.ps1          # CPU installer
.\packaging\build_agent.ps1 -Gpu     # GPU installer (adds the NVIDIA libraries, needs requirements-gpu.txt)
```

The installers are written to `D:\call-analyzer-build` (or `.\build` without a D: drive; change with `-OutDir`).

**Or from source** (developers; the same agent without the tray app): install Call Analyzer as in [Setup](#setup),
then:

```powershell
.venv\Scripts\python -m call_analyzer agent login --code ca1.…
.venv\Scripts\python -m call_analyzer agent run
.venv\Scripts\python -m call_analyzer agent status        # what it will use, and whether it is ready
.venv\Scripts\python -m call_analyzer agent autostart     # Windows: start it whenever you sign in (--off removes it)
```

**Settings: server defaults, agent overrides.** With every task the agent receives the server's current defaults
(`WHISPER_MODEL`, `WHISPER_LANGUAGE`, `WHISPER_PROMPT`, `WHISPER_DEVICE`, `TRANSCRIBE_PROVIDER`, `ANALYSIS_BACKEND`,
`CLAUDE_BACKEND`, `CLAUDE_MODEL`, `CURSOR_MODEL`, `FEEDBACK_LANGUAGE`, plus the text of `business.md`), so changing
them in Settings applies to the agents too. Anything the agent sets itself wins. `agent login` creates
`agent.toml` in the agent's folder (`%LOCALAPPDATA%\CallAnalyzerAgent` for the installed app,
`~/.call-analyzer-agent` from source; `AGENT_HOME` changes it; the tray menu opens it):

```toml
[tasks]
transcribe = 1      # how many at once; 0 turns the step off on this PC
analyze = 2

[overrides]
whisper_model = "large-v3-turbo"   # a lighter model than the server's default, for a weaker GPU
whisper_device = "cpu"
claude_backend = "subscription"    # use this PC's Claude Code login instead of the server's API setting
```

API keys (`ANTHROPIC_API_KEY`, `ELEVENLABS_API_KEY`, ...), the Claude login and the model folder
(`whisper_model_dir`) are never sent by the server: an agent uses its own, from its environment or its `.env`.
The Remote agents page shows, per agent, what it overrides and which steps it is ready for (a missing `claude`
login or Whisper install is reported there).

**Several agents** share the queue: each takes the next waiting call as soon as it has a free slot, so more PCs
means faster processing. An agent can be **paused** (finishes its current call, takes no new ones). If an agent
goes silent for two minutes, or you stop it, its calls go back to the queue for the others; a call is tried up to
3 times before it is marked as failed (the error is shown on the call and in *Recent tasks*). Results are marked
with the agent that produced them (e.g. `Whisper tunisian-large-v3 (local, GPU) · agent Office PC`).

Pipeline jobs work the same as before: they wait for the agents and show their progress in the log, and **Stop**
cancels the calls the job queued. When a run includes both steps, a transcript is analyzed as soon as it arrives.
Ongoing mode (`AUTO_PROCESS`) also uses agents.

## Command line

```powershell
# Try it on a few calls first
.venv\Scripts\python -m call_analyzer run --since 2026-10-01 --limit 5

# Full pipeline for the last month
.venv\Scripts\python -m call_analyzer run --since 2026-09-01

# Or step by step
.venv\Scripts\python -m call_analyzer sync          # fetch the list of recordings
.venv\Scripts\python -m call_analyzer download
.venv\Scripts\python -m call_analyzer transcribe
.venv\Scripts\python -m call_analyzer analyze
.venv\Scripts\python -m call_analyzer report        # writes reports/*.md

.venv\Scripts\python -m call_analyzer stats         # progress + avg score per agent
.venv\Scripts\python -m call_analyzer show 15711    # transcript + feedback for one call
```

Filters on every command: `--since`, `--until`, `--agent 102`, `--min-duration 30` (default: skip calls under
30 s), `--limit N`, `--workers N` (parallel Claude calls; lower it if you hit subscription rate limits). `analyze --redo` re-runs feedback (e.g. after editing `business.md`).

## What you get

**Per call** (`show <id>`): summary, outcome, customer interest, 1–10 scores (opening, discovery, pitch,
objection handling, closing, tone), strengths, mistakes with the exact quote and a better sentence to use
instead, objections and better answers, missed opportunities, top coaching tip, follow-up action.

**Reports** (`reports/`): one for the team and one per agent: recurring patterns, top 3 priorities,
a rewritten pitch script in Derja/French, an objection playbook, best/worst calls to listen to, and hot
leads to follow up.

Feedback language is set with `FEEDBACK_LANGUAGE` (quotes and suggested sentences stay in the call's language).
