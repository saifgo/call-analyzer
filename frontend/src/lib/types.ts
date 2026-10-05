// Shapes returned by call_analyzer/web/server.py.

export type CallStatus = "new" | "downloaded" | "transcribed" | "analyzed" | "stale";

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
  outcome: string | null;
  interest: string | null;
  /** Last time anything about the call changed (download, transcript, analysis, error). */
  updated_at: string | null;
};

export type Analysis = {
  is_sales_conversation: boolean;
  call_category: string;
  outcome: string;
  customer_interest: string;
  overall_score: number;
  scores: Record<string, number>;
  summary: string;
  strengths: string[];
  mistakes: { quote: string; problem: string; better_version: string }[];
  objections: { objection: string; how_handled: string; better_answer: string }[];
  missed_opportunities: string[];
  top_coaching_tip: string;
  follow_up_action: string;
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
    avg_score: number | null;
    wins: number | null;
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
