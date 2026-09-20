/**
 * API client.
 *
 * Everything is same-origin `/api/*`: in the container stack Caddy routes
 * those to the backend, and in development a Next rewrite does. Cookies
 * are sent with every request because the session is an HttpOnly cookie
 * the JavaScript here cannot read — which is the point.
 */

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const response = await fetch(path, {
    ...init,
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      ...(init.headers ?? {}),
    },
  });

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      // Non-JSON error body; the status text will do.
    }
    throw new ApiError(response.status, detail);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: JSON.stringify(body ?? {}) }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PATCH", body: JSON.stringify(body ?? {}) }),
  del: <T>(path: string) => request<T>(path, { method: "DELETE" }),
  /** For binary responses (e.g. the marks .xlsx export) that `request`'s
   * JSON parsing can't handle -- triggers a normal browser download. */
  download: async (path: string, filename: string) => {
    const response = await fetch(path, { credentials: "same-origin" });
    if (!response.ok) {
      let detail = response.statusText;
      try {
        const body = await response.json();
        if (typeof body?.detail === "string") detail = body.detail;
      } catch {
        // Non-JSON error body; the status text will do.
      }
      throw new ApiError(response.status, detail);
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    link.click();
    URL.revokeObjectURL(url);
  },
};

/**
 * A stable key for one action *instance*.
 *
 * Disabling a button on click is not enough on its own: a network retry,
 * a refresh mid-flight, or a second tab can still deliver the same action
 * twice. The server rejects or replays a duplicate key, so the worst case
 * of a double-fire is a repeated response rather than a duplicate row or
 * a second billed inference call.
 */
export function newIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

// --- shared response shapes ------------------------------------------------

export interface Me {
  id: string;
  email: string;
  name: string;
  role: "student" | "faculty" | "admin";
  reg_no: string | null;
  profile_complete: boolean;
  /** What the UI may offer; every staff route still re-checks on the server. */
  capabilities?: { settings: boolean; admin: boolean };
}

export interface Classroom {
  id: string;
  name: string;
  join_open?: boolean;
  /** Present only when the caller is faculty/admin (own section, or an
   * admin-listed one) -- a student's /enrolled view omits both codes. */
  student_join_code?: string;
  faculty_join_code?: string;
  active_experiment_id: string | null;
  active_session_id: string | null;
  student_count?: number;
  /** True when the current (student) caller reaches this classroom via a
   * classroom-scoped co-faculty promotion rather than plain enrolment. */
  co_faculty?: boolean;
  /** "Deleted" classes are archived: hidden from lists, data kept. */
  archived?: boolean;
  archived_at?: string | null;
}

export interface SessionListItem {
  id: string;
  experiment_id: string;
  experiment_title: string;
  status: "active" | "ended";
  started_at: string | null;
  ended_at: string | null;
  duration_minutes: number | null;
  started_by: string;
  students: number;
  prompts: number;
}

export interface SessionReportStudent {
  student_id: string;
  name: string;
  email: string;
  reg_no: string | null;
  prompts: number;
  first_at: string | null;
  last_at: string | null;
  tutor_replies: number;
  avg_latency_ms: number | null;
  fallback_replies: number;
  llm_calls: number;
  attempts: number;
  attempts_passed: number;
  diagnoses: {
    status: string;
    tier: number;
    signature_code: string | null;
    action: string;
    low_confidence: boolean;
    created_at: string | null;
  }[];
  summary: string | null;
  summary_flagged: boolean;
  marks: { pre: number | null; pre_max: number; post: number | null; post_max: number } | null;
}

export interface SessionReport {
  session: {
    id: string;
    experiment_id: string;
    experiment_title: string;
    status: "active" | "ended";
    started_at: string | null;
    ended_at: string | null;
  };
  totals: {
    students: number;
    prompts: number;
    attempts: number;
    diagnoses: number;
    fallback_replies: number;
  };
  students: SessionReportStudent[];
}

export interface TranscriptMessage {
  id: string;
  author: "student" | "tutor";
  kind: string;
  content: string;
  created_at: string | null;
  meta: Record<string, unknown>;
  citations: number;
}

export interface RosterStudent {
  id: string;
  email: string;
  name: string;
  joined_at: string;
}

export interface RosterFaculty {
  id: string;
  email: string;
  name: string;
  joined_at: string;
  /** True when this row is a student promoted to co-faculty for this
   * classroom, not a genuine platform-faculty peer. */
  promoted: boolean;
}

export interface AdminUser {
  id: string;
  email: string;
  name: string;
  role: "student" | "faculty" | "admin";
  role_override: "student" | "faculty" | "admin" | null;
}

export interface TopicCoverage {
  experiment_id: string;
  steps_attempted: number;
  steps_passed: number;
  submissions: number;
  diagnoses_passed: number;
  diagnoses_failed: number;
  diagnoses_escalated: number;
  qa_messages: number;
  coverage_score: number;
}

export interface StudentCoverage {
  student_id: string;
  student_email: string;
  student_name: string;
  topics: TopicCoverage[];
}

export interface ActiveSessionInfo {
  active: boolean;
  session_id?: string;
  experiment_id?: string;
  started_at?: string;
}

export interface ClassSessionInfo {
  id: string;
  experiment_id: string;
  status: "active" | "ended";
  started_at: string;
  ended_at: string | null;
}

export interface Experiment {
  id: string;
  title: string;
  kind: string;
  ready: boolean;
  manual_reference: string;
  /** Evaluation priority, not a restriction -- all 10 experiments are
   * available; "P0+"/"P0" got the most testing effort. */
  priority: string;
}

export type TutorIntent =
  | "lab_question"
  | "safety_incident"
  | "safety_question"
  | "distress"
  | "off_scope";

export interface SocraticState {
  session_id: string;
  experiment_id: string;
  current_step: number;
  total_steps: number;
  prompt: string;
  complete: boolean;
  actor_type?: string;
}

export interface AttemptResult {
  passed: boolean;
  current_step: number;
  total_steps: number;
  message: string;
  hint_level: number;
  complete: boolean;
  prompt: string;
}

export interface SubmissionResult {
  submission_id: string;
  experiment_id: string;
  status: string;
  tier: number;
  action: string;
  explanation: string;
  citation: string;
  low_confidence: boolean;
}

// --- Unified Chat -----------------------------------------------------------

export interface ChatThread {
  id: string;
  title: string;
  classroom_id: string;
  experiment_id: string;
  created_at: string;
  updated_at: string;
}

export interface WalkthroughOption {
  key: string;
  text: string;
}

export interface WalkthroughQuizItem {
  n: number;
  kind: "recall" | "preview";
  stem: string;
  options: WalkthroughOption[];
}

export interface WalkthroughUi {
  kind: "hook" | "step" | "quiz" | "paused" | "done";
  progress?: { label: string; index: number; total: number; chapter: string };
  phase?: string;
  step_id?: string;
  title?: string;
  question_id?: string | null;
  options?: WalkthroughOption[];
  quiz?: WalkthroughQuizItem[];
  chips?: string[];
}

export interface ChatMessageMetadata {
  type?: "qa" | "socratic" | "diagnostic" | "triage" | "walkthrough";
  status?: string;
  tier?: number;
  action?: string;
  explanation?: string;
  citation?: string;
  citations?: QaCitation[];
  low_confidence?: boolean;
  intent?: TutorIntent;
  passed?: boolean;
  current_step?: number;
  total_steps?: number;
  complete?: boolean;
  prompt?: string;
  /** Guided-walkthrough turn: rendering hints and the raw controller event,
   * for the step card, options/chips and (elsewhere) analytics. */
  ui?: WalkthroughUi;
  walkthrough?: Record<string, unknown>;
}


export interface UnifiedChatMessage {
  id: string;
  author: "student" | "tutor";
  content: string;
  kind: "qa" | "socratic" | "diagnostic";
  metadata?: ChatMessageMetadata;
  created_at: string;
}

// --- Q&A chat ---------------------------------------------------------------


export interface QaCitation {
  text: string;
  page: number;
  tier: string;
}

export interface QaAskResult {
  reply: string;
  status: string | null;
  citations: QaCitation[];
  answer_source: string;
  experiment_id: string | null;
  intent: TutorIntent;
}

export interface QaHistoryMessage {
  author: "student" | "tutor";
  content: string;
  experiment_id: string | null;
  created_at: string;
}

// --- faculty/admin dashboard -------------------------------------------------

export interface DashboardSubmission {
  submission_id: string;
  student_email: string;
  experiment_id: string;
  created_at: string;
  status: string;
  tier: number | null;
  signature: string | null;
  expected_value: number | null;
  reported_value: number | null;
  explanation: string;
  low_confidence: boolean;
}

export interface Escalation {
  id: string;
  student_email: string;
  reason: string;
  resolved: boolean;
  created_at: string;
  expected_value: number | null;
  reported_value: number | null;
}

export interface SummaryJob {
  job_id: string;
  status: string;
  total: number;
  completed: number;
  skipped: number;
  error: string | null;
}

export interface StudentSummary {
  student_id: string;
  student_email: string;
  experiment_id: string;
  text: string;
  flagged: boolean;
  flag_reason: string | null;
  generated_at: string;
}

// --- pre/post-test marks -----------------------------------------------------

export interface ExperimentMarksRow {
  student_id: string;
  student_name: string;
  student_email: string;
  pre_test_marks: number | null;
  pre_test_max: number;
  post_test_marks: number | null;
  post_test_max: number;
}

export interface MarksAnalyticsRow {
  experiment_id: string;
  n: number;
  mean_pre: number | null;
  mean_post: number | null;
  mean_gain: number | null;
  percent_improved: number | null;
  std_gain: number | null;
}

// --- faculty/admin Activity & Data ------------------------------------------

export interface ActivityStudent {
  student_id: string;
  /** student | faculty | co-faculty | admin */
  role: string;
  thinking_tokens: number;
  cached_tokens: number;
  llm_calls: number;
  retries: number;
  fallback_replies: number;
  name: string;
  email: string;
  reg_no: string | null;
  logins: number;
  last_login_at: string | null;
  last_seen_at: string | null;
  active_seconds: number;
  prompts_total: number;
  prompts_by_kind: Record<string, number>;
  experiments: string[];
  avg_llm_latency_ms: number | null;
  avg_response_ms: number | null;
  prompt_tokens: number;
  completion_tokens: number;
  /** null until an admin sets both price env vars -- see .env.example. */
  estimated_cost_usd: number | null;
}

export interface ActivitySession {
  student_id: string;
  role: string;
  name: string;
  email: string;
  reg_no: string | null;
  login_at: string;
  logout_at: string | null;
  last_seen_at: string | null;
  duration_seconds: number;
  end_reason: string;
}

export interface ActivityResponse {
  classroom: { id: string; name: string };
  role_filter: string;
  by_role: Record<string, { users: number; prompts: number }>;
  totals: {
    thinking_tokens: number;
    cached_tokens: number;
    llm_calls: number;
    retries: number;
    fallback_replies: number;
    students: number;
    students_with_activity: number;
    logins: number;
    prompts: number;
    active_seconds: number;
    prompt_tokens: number;
    completion_tokens: number;
    avg_llm_latency_ms: number | null;
    estimated_cost_usd: number | null;
  };
  students: ActivityStudent[];
  sessions: ActivitySession[];
}
