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
};

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
