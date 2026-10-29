<img src="assets/icon.svg" width="64" height="64" alt="">

# Call Analyzer

Pulls sales call recordings from the GoVoice VoIP manager, transcribes them, and uses Claude to give
per-call feedback and coaching reports (team + per agent) on how to improve the pitch.

```
GoVoice list API ──► download mp3 ──► speech-to-text ──► Claude: per-call feedback ──► Claude: coaching report
   (sync)             (download)        (transcribe)            (analyze)                    (report)
```

Everything is stored in a PostgreSQL database (`DATABASE_URL`), so every step is resumable and only processes new
calls. Docker Compose runs one for you; see [Database](#database).

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
copy .env.example .env     # then fill it in, including DATABASE_URL
# A PostgreSQL server, if you don't have one (then DATABASE_URL=postgresql://postgres:dev@localhost:5432/postgres):
docker run -d --name call-analyzer-db -e POSTGRES_PASSWORD=dev -p 5432:5432 -v call-analyzer-db:/var/lib/postgresql/data postgres:17
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
   Sales calls and customer service calls are judged separately: the AI first decides which kind a call is, then
   scores it with the matching score card and the matching parts of `business.md` (sections whose title mentions
   "service" or "support" are for service calls, "Who we call" / "Our ideal call" for sales calls, the rest for
   both). Service calls get their own score card (greeting, understanding, solution, clarity, empathy, resolution)
   and their own coaching report (`...-service-team.md`, `...-service-agent-<ext>.md`). Calls nobody picked up
   (voicemail, no answer), wrong numbers and internal calls are not rated: they get a one-line summary but no score,
   and are left out of every report and of the agents' average scores.

## Web interface

```powershell
.venv\Scripts\python -m call_analyzer ui
```

Opens http://127.0.0.1:8765 in your browser and asks you to sign in:

- **Dashboard**: pipeline progress, per-agent call counts, average score and wins, and one-click actions.
- **Calls**: filter by agent, status, date, length or text; open a call to play the audio, read and **edit the
  transcript**, then "Save & re-analyze"; see the full feedback. Tick several calls to process them in bulk.
- **Pipeline**: choose steps and filters, start or stop a job, and watch the live log.
- **Reports**: read the coaching reports, or generate new ones. Reports take the human feedback written on the
  calls into account: reviewers' notes and scores outweigh the AI's analysis, and a "Human review" section compares
  the two.
- **Business context**: edit `context/business.md`.
- **Remote agents**: PCs that do the transcription/analysis for a hosted server; see [Remote agents](#remote-agents).
- **Settings**: edit every `.env` value (cookie, models, backends) and run a setup check.
  Turn on **Ongoing mode** (`AUTO_PROCESS`) and, while the UI runs, it fetches new calls from GoVoice every
  `AUTO_PROCESS_MINUTES` (5) and downloads, transcribes and analyzes them. Runs show up on the Pipeline page.
  List numbers in `SKIP_NUMBERS` (comma-separated, e.g. your agents' own phones called through the VoIP) and
  their calls are never downloaded, transcribed or analyzed; they show as **Skipped** on the Calls page.
- **CRM tab** (call drawer, next to Feedback and Transcript): looks up the customer's number in your
  [Twenty CRM](https://twenty.com) and lists the matching contacts with their opportunities. Set `CRM_BASE_URL`
  and `CRM_API_KEY` (Twenty: Settings > APIs & Webhooks) in Settings. Numbers are matched on their last 8 digits,
  so `+21694721843` and `94721843` find the same contact (the CRM must store the number without spaces).
- **Call desk** (Operations): agents and admins switch on **Taking calls** and are served CRM contacts one at a
  time. The queue is the opportunities at the New stage that have a phone number, oldest first, whoever owns them;
  the next free agent gets the oldest contact nobody holds, and callbacks go in front once they're due. The agent
  sees what's known about the contact (CRM details and notes, earlier desk calls, recorded calls with that number),
  presses **Start call**, fills in what they learn (business type, daily revenue, how and where they buy their
  vouchers and at what price…; saved as they type), then **End call** and closes it with an outcome, a note, the
  contact's next stage and optionally a callback (for anyone, or kept for themselves). Closing a call moves the
  opportunity to the chosen stage, copies the city and "has a POS" answers to the contact, and attaches a note with
  everything to the opportunity and the contact. Admins also get a **Team board**: who is on a call, the queue,
  scheduled callbacks and the latest results (with a retry when the CRM couldn't be updated). A contact served to
  someone whose desk is closed goes back to the queue after 5 minutes unless the call was started; a contact
  closed on the desk isn't served from the queue again (book a callback to call it again). The API key needs
  permission to edit records.
  **Test call** (in the desk bar) serves a made-up contact with a number you type in, to try the whole flow without
  touching the queue: nothing about it is written to the CRM, it isn't counted in the day's figures, its callbacks
  are kept for whoever made it, and it pauses you so no real contact follows.
  **New call** starts a sales call outside the queue: type the number and the CRM is searched for it. A contact
  found there can be called right away (on one of their opportunities, or a new one if they have none); a new number
  asks for the contact's name, city and email, adds them to the CRM with a New opportunity ("<name> Call Desk
  Lead", owned by the agent's **CRM user**, set per account in Users), then calls them now or leaves them in the queue. The call then goes like any other: questions, outcome,
  appointment, CRM note. A contact you were served but hadn't called yet goes back to the queue.
- **Campaigns** (Operations > Campaigns, admins): each campaign is a queue (the CRM opportunities at the stages you
  pick), the questions agents ask on its calls, the outcomes calls can end with (each says whether the contact was
  **reached**, whether it's a **win** for the KPIs, the stage it suggests, and whether to suggest a callback), and its
  calling rules: how many unanswered calls in a row before giving up (and the stage those contacts move to), how long
  to wait before trying again, and the days and hours its queue is served (callbacks that come due are served at any
  time). The first campaign, "New leads", holds the questions and outcomes the desk had before. Agents pick their
  campaign in the desk bar when there are several. A campaign with calls can't be deleted, only archived.
- **Power dial** (desk bar, needs the browser phone): each contact served is dialed after a 3-second countdown, and a
  call nobody answers is saved with the suggested outcome (no answer, busy…) and the campaign's retry after 5 seconds
  unless the agent touches the form, so the next contact follows straight away.
- **Recordings**: after each GoVoice sync, every desk call is matched to its recording (same number, the agent's
  extension, closest start time within 3 minutes). The call's page then shows the desk outcome, and the desk's
  history links to the recording. If GoVoice's clock differs from the server's (e.g. a server on UTC), set
  `RECORDING_CLOCK_OFFSET_MINUTES` (GoVoice's time minus the server's, e.g. 60).
- **Real-time alerts** (admins, on every page): an agent idle too long (taking calls but no call, a contact served
  but not dialed, or a call ended but not closed), an unusually long call, five unanswered calls in a row, a sudden
  drop in a campaign's contact rate (the last hour against the 7 days before), and a callback overdue. Each new alert
  pops up as a toast (and as a desktop notification while the app is in the background, once allowed from the team
  board's Alerts card); the Call desk menu entry shows how many are open and the team board lists them. An alert turns
  critical at twice its threshold. The thresholds are in Settings > Call desk (`ALERT_*`; 0 turns one off).
- **Idle prompts**: an agent taking calls who stays on the desk without calling anyone (no contact dialed, no call
  closed) for `DESK_IDLE_PROMPT_MINUTES` (5 by default, Settings > Call desk; 0 turns it off) is prompted to call,
  again every as many minutes while it lasts. Time with the desk closed doesn't count. Each idle stretch is logged:
  admins see it in Operations > KPIs (the agent table's Idle column, and the Idle prompts list: when, how long, what
  the agent was doing, and whether they then called, paused or left the desk).
- **Earned breaks** (off by default; Settings > Call desk, `DESK_EARNED_BREAK`): an agent who closes
  `DESK_EARNED_BREAK_CALLS` calls (20 by default; test calls don't count) is offered a break of
  `DESK_EARNED_BREAK_MINUTES` (10 by default) before their next contact. They can take it now or later from the desk
  bar, which also counts down the calls to the next one. The count starts again after each break taken. The break is
  logged as an "Earned break" pause with its length as the limit, so it shows on the team board, the wallboard and the
  KPIs, and turns red if it runs over.
- **KPIs** (Operations > KPIs; agents see their own): calls closed, contact rate, wins and conversion rate, calls
  and wins per desk hour (time spent with "Taking calls" on), talk and wrap-up time, callbacks booked, contacts
  given back, and the AI's average score of the recorded calls, per agent and day by day.
- **Insights** (Operations > Insights, admins): the desk outcomes against the AI's scores of the same recordings:
  the win rate per AI score band, which score card criteria the wins score higher on, the AI's own reading of the
  outcome next to the agent's, and the rated calls to listen to.
  **Quick actions** send the contact a WhatsApp message in one click while they're on the desk (the price list, how to
  make a deposit, how to create an account…), through the WhatsApp Cloud API (Settings > WhatsApp). A business may
  only write first with a template Meta approved, so each quick action is an approved template: pick it in Settings,
  say what fills its variables (the contact's name, the agent's name or a fixed text) and, for a template that sends
  a document/image/video, the public link to the file. What was sent is listed in the call's CRM note.

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

### Softphone (calls in the browser)

Agents can make and take their GoVoice calls in the app instead of GoVoice's web phone: the phone button in the
bottom corner opens a dialer, and incoming calls ring on every page (answer, decline, mute, hold, keypad, hang up).

GoVoice is an Asterisk PBX with a WebRTC WebSocket (`wss://otn.govoice.tn:8089/ws`). The browser connects to it
directly and signs in as the agent's extension, like GoVoice's own web phone does. The call audio goes between the browser and
GoVoice. It doesn't pass through this server.

To set it up, open **Users**, edit the account and fill in **Phone**: the extension (e.g. `100`) and the GoVoice
account it belongs to (**My Account** on otn.govoice.tn: the username, e.g. `user100`, and its password). The SIP
password isn't typed in: the server fetches it from GoVoice's account API with that login when you save, and again
each time the agent opens the app, so a SIP password changed in GoVoice is picked up. If GoVoice refuses the login,
the agent's phone says so and the account password has to be entered again in Users. The SIP username comes
from GoVoice too (e.g. `1759512535_100`; GoVoice sends both Caesar-shifted and the app shifts them back like GoVoice's web phone does). Phones set up before this used `SOFTPHONE_USER_PREFIX` + extension (taken
from `GOVOICE_RECORDINGS_DIR` when empty) until they are saved again. The other settings are in Settings > Softphone.

- The microphone only works over **HTTPS** (or on `localhost`), so serve the app over HTTPS when it's hosted.
- Only one tab registers the phone. Other tabs say so, and take over when that tab closes.
- If the agent also has GoVoice's web phone open on the same extension, both ring.
- No audio from some networks: add a TURN server to `SOFTPHONE_ICE_SERVERS`.

**Sound** (the sound-wave button in the dialer or on the call card) cleans the call audio in the browser, with no
server or outside service. The settings are saved per browser and apply right away, also during a call:

- **Noise reduction:** Off (only the browser's own), **Standard** (RNNoise: keyboards, fans, street noise, most
  chatter; light on the PC) or **Strong** (GTCRN: cleaner voice, removes more background voices, uses more CPU).
- **Cut background voices:** a voice gate lowers the agent's line by about 26 dB while they aren't speaking, so
  colleagues aren't heard between their sentences. The slider sets how loud the agent's voice must be to open it.
  The level meter (or **Test my microphone** outside a call) turns green on the voice and should stay grey when only
  the room is heard. It works best with a headset whose microphone is close to the mouth: a laptop microphone hears
  colleagues nearly as loud as the agent.
- **Clean the customer's audio:** the same noise reduction on what the agent hears. Use it with a headset.

The models (a few hundred KB) are part of the UI bundle. If a browser can't run them, the microphone is sent as is.

The GoVoice account passwords, SIP passwords and access tokens are stored encrypted in the database (`softphones`
table, AES with `cryptography`'s Fernet). The key is `SECRET_KEY` if set, else a random key created once in
`data/secret.key`: **back that file up with the database**; without it the saved passwords can't be read and have to
be entered again in Users. Passwords saved before encryption are encrypted the next time the app starts. The SIP
password is only sent to the account's own browser; the account password never leaves the server.

#### Incoming calls

When a call rings, the call card shows who's calling: their CRM contact, the desk's last call with them, the agent
who knows them, a callback planned, and how many times they called before without an answer.

- **Picked up**: the desk opens a call for them (badge *Incoming call*), in the **Incoming calls** campaign: its own
  questions (why they called, how they heard of us...) and outcomes (support solved / to follow up, complaint...),
  edited on Operations > Campaigns like the others. It's closed like any desk call: outcome, stage, callback, note to
  the CRM. A contact the agent was served but hadn't called yet goes back to the queue. A caller who isn't in the CRM
  can be added during the call; until then nothing about them is written to the CRM.
- **Missed** (nobody answered, declined, or turned away because the agent was on another call): it waits on the
  **Missed calls** list (desk and team board), one line per number. The desk serves missed calls before anything else:
  for 5 minutes only to the agent who last spoke with the contact (else whose phone rang), then to anyone. An agent
  can also call one back from the list, or dismiss it (spam, dealt with elsewhere). It leaves the list once someone
  calls the number from the desk or the caller gets through.
- A call that rings several agents (a ring group) counts once: the agents who didn't pick it up get no missed call.
- **Alerts**: a missed call nobody called back within `ALERT_MISSED_CALL_MINUTES` (10) shows on the team board.
- **Figures**: Operations > KPIs > Incoming calls: answer rate, missed calls, how many were dealt with, and how fast
  they were called back; per agent, the calls that rang them, answered, missed and called back.

## Connecting another CRM or phone system

The CRM and the phone system are adapters. The rest of the app (call desk, pipeline, KPIs, the UI's API) only calls
`call_analyzer/crm.py` and `call_analyzer/telephony.py`, which hand the work to the adapter chosen in Settings:

| Setting | Built in | Adapters live in | Interface |
| --- | --- | --- | --- |
| `CRM_PROVIDER` | `twenty` | `call_analyzer/adapters/crm/` | `adapters/crm/base.py` (`CrmAdapter`) |
| `TELEPHONY_PROVIDER` | `govoice` | `call_analyzer/adapters/telephony/` | `adapters/telephony/base.py` (`TelephonyAdapter`) |

To add one, e.g. HubSpot:

1. Create `call_analyzer/adapters/crm/hubspot.py` with a `class HubSpotCrm(CrmAdapter)`. Implement its methods so
   they return the shapes described in `base.py` (`Person`, `Lead`, `Stage`, `Note`, ...). `twenty.py` is a complete
   example. Raise `CrmError` with a message people can act on when the CRM can't be reached. List its settings in
   `setting_keys` and `secret_keys`, and add them to `.env.example` so they show up in Settings.
2. Register it in `BUILTIN` in `call_analyzer/crm.py`: `"hubspot": ".crm.hubspot:HubSpotCrm"`.
3. Set `CRM_PROVIDER=hubspot` in Settings.

A phone system works the same way: subclass `TelephonyAdapter` (recordings: `check`, `iter_recordings`, `download`;
softphone: `softphone_defaults`, `sip_login`; optional login pages: `routers`), add it to `BUILTIN` in
`call_analyzer/telephony.py`, and set `TELEPHONY_PROVIDER`. Restart the app after changing `TELEPHONY_PROVIDER`, since
the web routes an adapter adds are mounted at startup. Caching, phone number matching (last 8 digits), the connection
status and the session keepalive are shared and stay out of the adapters. `GET /api/providers` shows which adapters
exist and which are in use. `tests/test_providers.py` shows a minimal adapter of each kind.

## Hosting with Docker

Settings come from environment variables (see `.env.example` for the full list). Anything changed later on
the **Settings** page is saved to `/app/data/.env` inside the data volume and takes precedence over the
environment variables.

### Coolify

1. New resource → your Git repository → build pack **Docker Compose** (file: `docker-compose.yml`).
2. **Environment variables**: at least `POSTGRES_PASSWORD` (letters and digits), `ADMIN_USERNAME`, `ADMIN_PASSWORD` (8+ characters), `PUBLIC_URL=https://your.domain`,
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

**Data** lives in Docker volumes: `pgdata` (the database), `data` (audio, Whisper models, saved settings),
`reports`, `context` (business.md). The first transcription downloads the Whisper model (~1.6 GB) into `data`.
Set `POSTGRES_PASSWORD` (letters and digits) before the first start. See [Database](#database) for backups.

**GPU** (NVIDIA, with the NVIDIA Container Toolkit installed):
`docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build`. Without a GPU, Whisper runs on the
CPU, which is much slower; on a small server consider `TRANSCRIBE_PROVIDER=elevenlabs` or `openai`.

**Tunisian Derja Whisper models** (`tunisian-large-v3`, `arabic-dialectal-turbo`) are converted once on first
use, which needs torch: build with `INSTALL_CONVERT=true docker compose up -d --build` (adds ~1 GB). On Coolify,
add the environment variable `INSTALL_CONVERT=true` as a build variable and redeploy. Converting
`tunisian-large-v3` needs about 6–8 GB of free RAM.

## Database

The app keeps everything in PostgreSQL, at `DATABASE_URL`. `docker-compose.yml` runs PostgreSQL 17 next to the app
(service `db`, volume `pgdata`, not reachable from outside); to use another server, set `DATABASE_URL`. The schema
is in `call_analyzer/migrations/`: new files there are applied in order when the app starts.

**Backups**: `pg_dump` gives a consistent copy while the app runs, e.g. every night:

```bash
docker compose exec -T db pg_dump -U call_analyzer -Fc call_analyzer > backup-$(date +%F).dump
# restore into an empty database:
docker compose exec -T db pg_restore -U call_analyzer -d call_analyzer --clean --if-exists < backup-2026-10-29.dump
```

On Coolify, turn on scheduled backups for the database. Keep `data/secret.key` with the backups: the softphone
passwords in the database are encrypted with it.

**Coming from SQLite** (`data/calls.db`, before PostgreSQL): the app refuses to start on an empty database while
that file still has data. Copy it in once, with the app stopped: `python -m call_analyzer db-copy --from
data/calls.db` (in Docker: `docker compose run --rm app python -m call_analyzer db-copy --from /app/data/calls.db`).
It checks every value first, copies in one transaction and compares every table before committing; `--dry-run` only
checks. The SQLite file is never changed. See `docs/postgres-migration.md` for the full switch-over.

**Tests** use a scratch database, emptied at each run (`TEST_DATABASE_URL`, its name must end in `_test`):

```bash
docker run -d --name ca-pg-test -e POSTGRES_PASSWORD=test -p 55432:5432 postgres:17
python -m unittest discover tests
```

## Voice tone

Claude only reads the transcript, which can't show *how* the agent sounds. **Voice analysis** listens to the
recording itself:

1. The speech is cut at pauses into windows of a few seconds.
2. An audio classification model (`VOICE_MODEL`, default `superb/wav2vec2-base-superb-er`, neutral / happy /
   angry / sad) gives each window an emotion, and loudness and pitch variation are measured (a flat monotone
   voice has little pitch variation, a tense one is loud and high).
3. These measurements are stored with the call and given to the analysis, which returns a **voice tone score
   (1–10)** for the agent (`voice` in the analysis): how calm, warm and steady they sound, the agent's and the
   customer's tone, the evidence by timestamp, and a tip on how to sound better. The tone/empathy score of the
   card also takes it into account. It shows on the call page (score, timeline of the call by emotion, emotion
   shares, pauses) and in the shared/PDF page.

It is a pipeline step of its own, **voice**, between download and transcription (download → voice → transcribe →
analyze), with its own section in Settings (`VOICE_ANALYSIS`, `VOICE_MODEL`). Like transcription and analysis it runs
on this server or on remote agents: `VOICE_RUNS_ON` = `host`, `agent` or `auto` (Settings, or the Agents page). When
a run includes the analysis, a call is analyzed as soon as both its transcript and its voice analysis are in.
`voice --redo` measures again, e.g. after changing the model.

Like the Tunisian Whisper models, the emotion model is **converted once on the server** (it is exported to ONNX,
which needs torch: `pip install -r requirements-voice.txt --extra-index-url https://download.pytorch.org/whl/cpu`;
Docker: build with `INSTALL_VOICE=true`, ~1 GB; the conversion takes about a minute and happens at the first voice
step) and from then on runs with onnxruntime, without torch. A remote agent that doesn't have the model downloads the
converted one from the server (it is packed on first request) and unpacks it into its model folder, so even the
installed Windows agent app, which has no torch, can do the voice step. The server only offers its own
`VOICE_MODEL`. If no converted model is available, the server still measures loudness and pitch, but an agent
fails the task rather than send back less. Roughly 1 s of processing per 8 s of audio on a CPU. `VOICE_ANALYSIS=false` turns it off.

Know its limits: GoVoice recordings are **mono**, so the audio can't say who is speaking: Claude attributes the
windows to the agent from the transcript timestamps (stereo recordings with one voice per channel are measured per
channel). The model was trained on English acted speech, and phone audio in Derja/French is a different thing, so
single windows are weak evidence; the analysis is told to trust patterns, not one window, and to mark low
confidence. Treat the score as a guide next to the human feedback, which always outweighs it. Existing analyses
get the voice score when you re-analyze them (`analyze --redo`).

## Remote agents

A hosted server often has no GPU and no Claude login. A **remote agent** is a PC (yours, or a colleague's) that
connects to the server and does the heavy steps, **transcription** (Whisper), **voice analysis** and **analysis** (Claude/Cursor), with
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

**The Whisper model downloads itself.** Right after connecting, and again whenever the server's `WHISPER_MODEL`
changes, the agent checks that the model is on the PC and, if not, downloads it in the background: the standard
models from Hugging Face, the Tunisian Derja models *from the server* (which converts each once: Settings →
Install now). While it downloads, the tray icon turns blue and says so, and the Remote agents page shows the
progress; the PC is not offered transcription work until the model is there (in `auto` mode the server does that
work meanwhile), and then it starts at once. It checks the free disk space first (a model is 0.1–3 GB, the Tunisian
ones twice that while unpacking) and retries a failed download after 5 minutes. Models go to
`%LOCALAPPDATA%\CallAnalyzerAgent\data\models`: set `whisper_model_dir` in `agent.toml` to put them on another drive.
Old models are not deleted when the default changes.

What else a PC needs: **Analysis** with `CLAUDE_BACKEND=subscription` needs the Claude Code CLI installed and
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
.venv\Scripts\python -m call_analyzer voice       # listen to the recordings (voice tone)
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
objection handling, closing, tone), a voice tone score from the audio itself, strengths, mistakes with the exact quote and a better sentence to use
instead, objections and better answers, missed opportunities, top coaching tip, follow-up action.

**Reports** (`reports/`): one for the team and one per agent: recurring patterns, top 3 priorities,
a rewritten pitch script in Derja/French, an objection playbook, best/worst calls to listen to, and hot
leads to follow up.

Feedback language is set with `FEEDBACK_LANGUAGE` (quotes and suggested sentences stay in the call's language).
