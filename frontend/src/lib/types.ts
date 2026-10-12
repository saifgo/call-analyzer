// Shapes returned by call_analyzer/web/server.py.

export type CallStatus = "new" | "downloaded" | "transcribed" | "analyzed" | "stale" | "skipped";

export type CallKind = "sales" | "service" | "other";

export type CallSummary = {
  id: string;
  type: string;
  agent: string;
  customer: string;
  date_call: string;
  duration: number;
  filename: string;
  status: CallStatus;
  error: string | null;
  score: number | null;
  /** Average of the scores people gave this call in Human feedback (calls list only). */
  human_score?: number | null;
  /** Sales outcome, or for a service call how it ended (resolved, escalated...). */
  outcome: string | null;
  interest: string | null;
  /** sales | service | other; null until analyzed. */
  kind: CallKind | null;
  /** Last time anything about the call changed (download, transcript, analysis, error). */
  updated_at: string | null;
};

/** How the agent sounds, scored by the analysis from the audio measurements (VoiceData). */
export type VoiceTone = {
  score: number;
  agent_tone: string;
  customer_tone: string;
  evidence: string;
  coaching_tip: string;
  confidence: "high" | "medium" | "low";
};

/** What both kinds of analysis have; sales calls add outcome/interest/objections, service calls issue/resolution.
 * "other" calls (voicemail, no answer...) are not rated: they only have call_kind and summary. */
export type Analysis = {
  /** Missing on analyses written before service calls got their own score card (those are sales or other). */
  call_kind?: CallKind;
  is_sales_conversation?: boolean;
  call_category?: string;
  outcome?: string;
  customer_interest?: string;
  issue_category?: string;
  resolution_status?: string;
  customer_sentiment?: string;
  overall_score: number;
  scores: Record<string, number>;
  summary: string;
  strengths: string[];
  mistakes: { quote: string; problem: string; better_version: string }[];
  objections?: { objection: string; how_handled: string; better_answer: string }[];
  missed_opportunities: string[];
  top_coaching_tip: string;
  follow_up_action: string;
  /** Missing on analyses made before voice analysis, or when the recording wasn't measured. */
  voice?: VoiceTone | null;
};

/** Measurements of the recording itself (call_analyzer/voice.py): per stretch of speech, then summed up. */
export type VoiceWindow = {
  start: number;
  end: number;
  /** Loudness in dBFS: compare within one call. */
  db: number;
  /** Pitch spread in semitones: about 1-2 is monotone, 3-5 lively. */
  pitch_st?: number;
  /** Probability of each emotion (neutral, happy, angry, sad...), highest first. */
  emotion?: Record<string, number>;
};

export type VoiceData = {
  /** Emotion classifier; null when only loudness and pitch could be measured. */
  model: string | null;
  duration: number;
  /** True when each channel of a stereo recording was measured on its own. */
  separated: boolean;
  tracks: {
    label: string;
    windows: VoiceWindow[];
    summary: {
      speech_seconds: number;
      speech_share: number;
      long_pauses: number;
      longest_pause_s: number;
      loudness_std_db?: number;
      pitch_variation_st?: number;
      emotion_share?: Record<string, number>;
      dominant?: string;
      angry_seconds?: number;
    };
  }[];
};

export type CallDetail = CallSummary & {
  transcript: string | null;
  transcribed_at: string | null;
  /** Model that wrote the transcript, e.g. "Whisper large-v3-turbo (local, GPU) · edited by omar". */
  transcribed_by: string | null;
  analyzed_at: string | null;
  /** System that wrote the analysis, e.g. "Claude claude-opus-5-5 (API)" or "Cursor composer-2.5". */
  analyzed_by: string | null;
  analysis: Analysis | null;
  /** What the recording sounds like; null until it was measured. */
  voice: VoiceData | null;
  has_audio: boolean;
  /** The call desk call this recording is, when it was made from the desk. */
  desk: DeskLink | null;
};

/** A recording's call desk call (call_analyzer/desk_stats.py desk_call_for_recording). */
export type DeskLink = {
  id: number;
  outcome: string | null;
  outcome_label: string | null;
  reached: boolean;
  success: boolean;
  campaign: string;
  agent_name: string;
  finished_at: string | null;
  note: string | null;
  stage_before: string | null;
  stage_after: string | null;
  lead_url: string | null;
};

export type CallList = { total: number; calls: CallSummary[]; agents: string[] };

export type Stats = {
  total: number;
  downloaded: number;
  transcribed: number;
  analyzed: number;
  stale: number;
  errors: number;
  last_call: string | null;
  agents: {
    agent: string;
    /** Name of the account linked to this extension, if any. */
    name: string | null;
    calls: number;
    analyzed: number;
    /** Average score of the sales calls (service calls have their own score card). */
    avg_score: number | null;
    /** How many scored sales calls avg_score is over. */
    scored: number;
    wins: number | null;
    service_calls: number | null;
    service_score: number | null;
    minutes: number | null;
  }[];
  outcomes: { outcome: string; n: number }[];
};

export type JobHistoryItem = { label: string; started_at: string; finished_at: string; exit_code: number };

export type JobState = {
  running: boolean;
  label: string;
  /** Started by ongoing mode (AUTO_PROCESS) rather than from the UI. */
  auto: boolean;
  started_at: string | null;
  finished_at: string | null;
  exit_code: number | null;
  offset: number;
  lines: string[];
  history: JobHistoryItem[];
};

export type JobArgs = Record<string, string | number | boolean | null | undefined>;

export type SettingField = {
  key: string;
  section: string;
  help: string;
  default: string;
  secret: boolean;
  value: string;
};

export type Share = { token: string | null; url: string | null; lan: boolean };

export type ReportFile = { name: string; modified: string };

/** connected: null = GoVoice couldn't be reached (network), not a login problem. */
export type GoVoiceStatus = {
  connected: boolean | null;
  total: number | null;
  message: string;
  checked_at: string | null;
};

export type WhisperModel = { name: string; label: string; repo: string; size_gb: number; installed: boolean };

export type Role = "admin" | "agent";

/** The signed-in account. Agent accounts only see the calls and reports of `agents`. */
export type Me = { user: string; role: Role; display_name: string | null; agents: string[] };

export type Account = {
  username: string;
  role: Role;
  display_name: string | null;
  created_at: string;
  /** Agent extensions linked to the account. */
  agents: string[];
  /** The CRM user (Twenty workspace member) the account is; owns the leads they add from the call desk. */
  crm_member_id: string | null;
};

export type CrmMember = { id: string; name: string; email: string | null };
export type CrmMembers = { configured: boolean; members: CrmMember[] };

/** An agent extension seen in calls, and the accounts linked to it. */
export type AgentInfo = { agent: string; calls: number; accounts: string[] };

export type CrmOpportunity = {
  id: string;
  name: string;
  /** Twenty stage value, e.g. "IN_TALK" or "ACTIVE". */
  stage: string | null;
  amount: number | null;
  currency: string | null;
  close_date: string | null;
  company: string | null;
  owner: string | null;
  created_at: string | null;
  updated_at: string | null;
  url: string;
};

export type CrmPerson = {
  id: string;
  name: string;
  email: string | null;
  phones: string[];
  job_title: string | null;
  city: string | null;
  company: string | null;
  created_at: string | null;
  last_contact_at: string | null;
  url: string;
  opportunities: CrmOpportunity[];
};

/** `searched` is false when the number is too short to look up (an internal extension). */
export type CrmLookup = { configured: boolean; number: string; searched: boolean; people: CrmPerson[] };

/** An opportunity still at the "new" stage in the CRM, with its point of contact: a lead to call. */
export type CrmLead = CrmOpportunity & {
  contact: Omit<CrmPerson, "opportunities"> | null;
  /** How often the contact's numbers appear in our recorded calls (last 8 digits). */
  calls: { count: number; match: string | null; last_id: string | null; last_date: string | null };
};

export type CrmLeads = { configured: boolean; stage: string; leads: CrmLead[]; truncated: boolean };

/** A note a person wrote about a call. `score` is their own 1-10 score, to compare with the AI's. */
export type HumanFeedback = {
  id: number;
  call_id: string;
  author: string;
  author_name: string;
  body: string;
  score: number | null;
  created_at: string;
  updated_at: string;
  call: Pick<CallSummary, "id" | "customer" | "agent" | "type" | "date_call" | "duration" | "score">;
};

export type FeedbackList = { total: number; feedback: HumanFeedback[]; authors: string[] };

export type WorkerStep = "transcribe" | "voice" | "analyze";
/** Where a pipeline step runs: this server, remote agents only, or agents while one is online (else the server). */
export type RunsOn = "host" | "agent" | "auto";

export type WorkerCapability = { ok: boolean; reason: string; detail: string; slots: number };

/** What an agent reports about itself. */
export type WorkerInfo = {
  hostname?: string;
  os?: string;
  version?: string;
  gpu?: boolean;
  slots?: Partial<Record<WorkerStep, number>>;
  capabilities?: Partial<Record<WorkerStep, WorkerCapability>>;
  /** The Whisper model the agent needs: downloaded in the background when it isn't on the PC yet. */
  model?: { name: string; status: "ready" | "downloading" | "error"; detail: string } | null;
  /** Settings the agent sets itself (agent.toml); the server's defaults apply to the rest. */
  overrides?: Record<string, string>;
  /** The settings the agent works with right now: server defaults merged with its overrides. */
  effective?: Record<string, string>;
};

export type WorkerRunning = {
  id: number;
  kind: WorkerStep;
  call_id: string;
  progress: string | null;
  started_at: string;
};

export type Worker = {
  id: string;
  name: string;
  /** false = paused by an admin: stays connected but gets no work. */
  enabled: boolean;
  online: boolean;
  last_seen: string | null;
  created_at: string;
  created_by: string | null;
  info: WorkerInfo;
  running: WorkerRunning[];
  done: number;
  failed: number;
  ready: Record<WorkerStep, boolean>;
};

export type WorkersState = {
  runs_on: Record<WorkerStep, RunsOn>;
  queue: { queued: number; running: number };
  /** The settings agents receive from the server. */
  defaults: Record<string, string>;
  /** PUBLIC_URL: the address agents should connect to (empty: the address this page was opened at). */
  public_url: string;
  /** AGENT_DOWNLOAD_URL: where to get the installer (optional). */
  download_url: string;
  /** Installers found in the server's data/downloads folder. */
  installers: AgentInstaller[];
  workers: Worker[];
};

export type WorkerTask = {
  id: number;
  kind: WorkerStep;
  call_id: string;
  status: "queued" | "running" | "done" | "failed" | "cancelled";
  worker_name: string | null;
  progress: string | null;
  error: string | null;
  attempts: number;
  created_at: string;
  finished_at: string | null;
  filename: string | null;
  extension: string | null;
  customer: string | null;
};

/** An agent installer stored on the server (data/downloads). */
export type AgentInstaller = {
  name: string;
  size: number;
  /** "gpu" = includes the NVIDIA libraries. */
  kind: "cpu" | "gpu";
  version: string | null;
  modified: string;
};

// --- Operations (call desk): call_analyzer/operations.py ---

export type OpQuestionType = "select" | "multi" | "number" | "text" | "textarea" | "boolean";

/** A question the agent asks during the call. `crm` copies the answer to that field of the CRM contact. */
export type OpQuestion = {
  key: string;
  section: string;
  label: string;
  type: OpQuestionType;
  /** [value, label] pairs, for select and multi. */
  options?: [string, string][];
  help?: string;
  unit?: string;
  step?: number;
  /** Only asked when another answer is one of these values. */
  show_if?: Record<string, string[]>;
  crm?: string;
};

export type OpAnswers = Record<string, string | number | boolean | string[]>;

export type OpOutcome = {
  value: string;
  label: string;
  /** Stage suggested for the contact (null when the CRM has no such stage). */
  stage: string | null;
  /** The agent spoke with the contact. */
  reached?: boolean;
  /** A win: what the conversion KPIs count. */
  success?: boolean;
  /** Booking a callback is suggested. */
  callback?: boolean;
};

/** A call desk campaign (call_analyzer/campaigns.py): its queue, questions, outcomes and calling rules. */
export type OpCampaign = {
  id: number;
  name: string;
  description: string | null;
  /** The CRM stages the queue is made of. */
  stages: string[];
  questions: OpQuestion[];
  outcomes: OpOutcome[];
  /** Unanswered calls in a row before giving up; 0: no limit. */
  max_attempts: number;
  /** When to try again after an unanswered call. */
  retry_minutes: number;
  exhausted_stage: string | null;
  call_start: string | null;
  call_end: string | null;
  /** ISO weekdays (1 = Monday); null: every day. */
  call_days: number[] | null;
  active: boolean;
  position: number;
  /** e.g. "Mon, Tue 09:00–18:00". */
  hours?: string;
};

export type OpStage = { value: string; label: string };

export type OpConfig = {
  /** Every campaign, archived ones too (to read their calls). */
  campaigns: OpCampaign[];
  /** All campaigns' outcomes by value, to label any call. */
  outcomes: OpOutcome[];
  stages: OpStage[];
  crm_configured: boolean;
};

export type OpStatus = "scheduled" | "assigned" | "in_call" | "done" | "released" | "cancelled";

/** A contact served on the desk, or a callback waiting to be. */
export type OpCall = {
  id: number;
  opportunity_id: string;
  person_id: string | null;
  /** The opportunity and its contact as the CRM had them when served. */
  lead: CrmLead | null;
  /** direct: a sales call the agent started themselves, outside the queue. */
  source: "queue" | "callback" | "direct" | "test";
  /** A test call (or a callback booked from one): a made-up contact, never written to the CRM. */
  test: boolean;
  status: OpStatus;
  agent: string | null;
  agent_name?: string | null;
  due_at: string | null;
  assign_to: string | null;
  assign_to_name?: string | null;
  scheduled_by: string | null;
  scheduled_by_name?: string | null;
  callback_note: string | null;
  assigned_at: string | null;
  call_started_at: string | null;
  call_ended_at: string | null;
  finished_at: string | null;
  answers: OpAnswers;
  outcome: string | null;
  note: string | null;
  stage_before: string | null;
  stage_after: string | null;
  crm_error: string | null;
  campaign_id: number | null;
  /** The number dialed. */
  phone: string | null;
  /** The GoVoice recording of the call, once linked. */
  call_id: string | null;
  /** Set by finish: that was the campaign's last try at an unanswered contact. */
  attempts_exhausted?: boolean;
};

export type OpQueue = {
  campaign_id?: number;
  campaign?: string;
  hours?: string;
  /** Within the campaign's calling hours. */
  open?: boolean;
  due_callbacks: number;
  scheduled: number;
  /** New contacts with a phone number nobody has had yet; null when the CRM couldn't be read. */
  waiting: number | null;
  no_phone: number | null;
  error: string | null;
  truncated: boolean;
};

export type OpDesk = {
  ready: boolean;
  current: OpCall | null;
  /** The campaign the agent works. */
  campaign_id: number;
  today: { done: number; reached: number; success: number; talk_seconds: number };
  /** Callbacks the agent booked or that are kept for them. */
  callbacks: OpCall[];
  queue: OpQueue;
};

export type OpContext = {
  history: OpCall[];
  previous_answers: OpAnswers;
  callback_from: OpCall | null;
  recorded_calls: {
    id: string;
    date_call: string;
    duration: number;
    agent: string;
    type: string;
    summary: string | null;
    outcome: string | null;
  }[];
  notes: { id: string; title: string; text: string; created_at: string | null; author: string | null }[];
  notes_error: string | null;
  /** Unanswered calls in a row before this one. */
  attempts: number;
  max_attempts: number;
  /** This is the campaign's last try if it goes unanswered. */
  last_try: boolean;
  /** When to try again if unanswered (within calling hours); null: no retry. */
  retry_at: string | null;
};

export type OpAgentState = "on_call" | "wrap_up" | "serving" | "ready" | "paused" | "offline";

export type OpBoard = {
  agents: {
    username: string;
    name: string;
    state: OpAgentState;
    ready: boolean;
    online: boolean;
    since: string | null;
    last_seen: string | null;
    current: OpCall | null;
    done_today: number;
    campaign: string | null;
  }[];
  /** All campaigns together. */
  queue: OpQueue;
  queues: OpQueue[];
  callbacks: OpCall[];
  recent: OpCall[];
  outcomes_today: Record<string, number>;
};

/** A WhatsApp template approved on the account (see call_analyzer/whatsapp.py). */
export type WaTemplate = {
  name: string;
  language: string;
  category: string | null;
  status: string | null;
  named: boolean;
  /** TEXT, DOCUMENT, IMAGE, VIDEO or LOCATION; null when it has no header. */
  header_format: string | null;
  header_text: string | null;
  body: string;
  footer: string | null;
  buttons: { type: string; text: string; url: string | null }[];
  /** What has to be filled in: "body.1", "header.name", "button.0.1"... */
  variables: string[];
};

/** A call desk quick action: a template sent in one click. `params` maps a variable to a source key or "text:...". */
export type WaAction = {
  id: number;
  label: string;
  template: string;
  language: string;
  params: Record<string, string>;
  header_link: string | null;
  header_filename: string | null;
  position: number;
};

export type WaActions = { configured: boolean; actions: WaAction[]; sources: Record<string, string> };

export type WaMessage = {
  id: number;
  op_id: number;
  action_id: number;
  label: string;
  to_number: string;
  status: "sent" | "failed";
  error: string | null;
  sent_by: string;
  sent_at: string;
};

// --- Call desk figures: call_analyzer/desk_stats.py ---

export type OpKpiRow = {
  username: string | null;
  name: string;
  calls: number;
  reached: number;
  success: number;
  outcomes: Record<string, number>;
  contact_rate: number | null;
  /** Wins out of reached contacts. */
  conversion_rate: number | null;
  success_rate: number | null;
  talk_seconds: number;
  avg_talk_seconds: number | null;
  avg_wrap_seconds: number | null;
  /** Time spent taking calls on the desk. */
  desk_seconds: number;
  calls_per_hour: number | null;
  success_per_hour: number | null;
  /** Talk time out of desk time. */
  talk_share: number | null;
  callbacks_booked: number;
  given_back: number;
  linked: number;
  scored: number;
  avg_score: number | null;
};

export type OpKpis = {
  since: string;
  until: string;
  team: OpKpiRow;
  agents: OpKpiRow[];
  days: { day: string; calls: number; reached: number; success: number }[];
};

export type OpInsights = {
  since: string;
  until: string;
  total: number;
  linked: number;
  rated: number;
  won_rated: number;
  other_rated: number;
  overall: { criterion: string; won: number | null; other: number | null; gap: number | null };
  outcomes: {
    outcome: string;
    label: string;
    reached: boolean;
    success: boolean;
    calls: number;
    linked: number;
    rated: number;
    avg_score: number | null;
    avg_voice: number | null;
    criteria: Record<string, number | null>;
    avg_talk_seconds: number | null;
    avg_recording_seconds: number | null;
    /** What the AI said the call's outcome was. */
    ai_outcomes: Record<string, number>;
  }[];
  /** Score card criteria: won calls vs the other reached calls, biggest gap first. */
  drivers: { criterion: string; won: number | null; other: number | null; gap: number | null }[];
  bands: { band: string; calls: number; success: number; success_rate: number | null }[];
  agents: {
    username: string;
    name: string;
    calls: number;
    reached: number;
    success: number;
    conversion_rate: number | null;
    rated: number;
    avg_score: number | null;
    avg_score_won: number | null;
    avg_score_other: number | null;
  }[];
  calls: {
    op_id: number;
    call_id: string;
    finished_at: string;
    agent_name: string;
    contact: string | null;
    outcome: string;
    outcome_label: string;
    success: boolean;
    reached: boolean;
    score: number;
    kind: string;
    ai_outcome: string | null;
    summary: string | null;
  }[];
};
