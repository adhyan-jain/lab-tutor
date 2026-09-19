"use client";

import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  api,
  ApiError,
  type ActivityResponse,
  type Classroom,
  type Me,
} from "@/lib/api";
import { AppNav } from "./AppNav";

function fmtDuration(seconds: number): string {
  if (!seconds) return "0m";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (h) return `${h}h ${m}m`;
  if (m) return `${m}m`;
  return `${seconds}s`;
}

function fmtTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function fmtMs(ms: number | null): string {
  if (ms === null || ms === undefined) return "—";
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.round(ms)}ms`;
}

export function ActivityWorkspace({ me }: { me: Me }) {
  const searchParams = useSearchParams();
  const [classrooms, setClassrooms] = useState<Classroom[]>([]);
  const [classroomId, setClassroomId] = useState<string>(searchParams.get("classroom") || "");
  const [data, setData] = useState<ActivityResponse | null>(null);
  const [tab, setTab] = useState<"students" | "sessions">("students");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const path = me.role === "admin" ? "/api/classrooms" : "/api/classrooms/mine";
        const res = await api.get<{ classrooms: Classroom[] }>(path);
        setClassrooms(res.classrooms);
        if (!classroomId && res.classrooms.length > 0) setClassroomId(res.classrooms[0].id);
      } catch (e) {
        setError(e instanceof ApiError ? e.message : String(e));
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const load = async (id: string) => {
    setLoading(true);
    setError("");
    try {
      setData(await api.get<ActivityResponse>(`/api/dashboard/classrooms/${id}/activity`));
    } catch (e) {
      setData(null);
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (classroomId) load(classroomId);
  }, [classroomId]);

  const handleExport = async () => {
    if (!classroomId) return;
    setError("");
    try {
      const name = classrooms.find((c) => c.id === classroomId)?.name || "classroom";
      await api.download(
        `/api/dashboard/classrooms/${classroomId}/research-export.xlsx`,
        `labtutor_research_export_${name.replace(/\s+/g, "_")}.xlsx`
      );
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  };

  const q = query.trim().toLowerCase();
  const matches = (s: { name: string; email: string; reg_no: string | null }) =>
    !q ||
    (s.name ?? "").toLowerCase().includes(q) ||
    s.email.toLowerCase().includes(q) ||
    (s.reg_no ?? "").toLowerCase().includes(q);
  const students = useMemo(() => (data?.students ?? []).filter(matches), [data, q]);
  const sessions = useMemo(() => (data?.sessions ?? []).filter(matches), [data, q]);

  const t = data?.totals;

  return (
    <>
      <AppNav me={me} current="/faculty/activity" />
      <div className="page">
        <h1 className="page-title">Student activity &amp; collected data</h1>
        <p className="muted" style={{ marginTop: 0 }}>
          Everything recorded for this classroom: sign-ins, time on the system, prompts, and model
          response times. Nothing here is deleted when a class session ends.
        </p>

        {error && <div className="error">{error}</div>}

        <div className="toolbar">
          <div className="field">
            <label className="muted">Classroom</label>
            <select value={classroomId} onChange={(e) => setClassroomId(e.target.value)}>
              {classrooms.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </div>
          <div className="field grow">
            <label className="muted">Search name, email or reg no</label>
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="e.g. 23BCE1234"
            />
          </div>
          <div className="field">
            <label className="muted">&nbsp;</label>
            <button className="btn btn-primary" onClick={handleExport} disabled={!classroomId}>
              Download research data (.xlsx)
            </button>
          </div>
        </div>

        {t && (
          <div className="stat-grid">
            <div className="card stat">
              <span className="muted">Students</span>
              <strong>
                {t.students_with_activity} / {t.students}
              </strong>
              <span className="muted">with activity</span>
            </div>
            <div className="card stat">
              <span className="muted">Sign-ins</span>
              <strong>{t.logins}</strong>
            </div>
            <div className="card stat">
              <span className="muted">Prompts</span>
              <strong>{t.prompts}</strong>
            </div>
            <div className="card stat">
              <span className="muted">Time on system</span>
              <strong>{fmtDuration(t.active_seconds)}</strong>
            </div>
            <div className="card stat">
              <span className="muted">Avg reply time</span>
              <strong>{fmtMs(t.avg_llm_latency_ms)}</strong>
            </div>
            <div className="card stat">
              <span className="muted">Tokens in / out (total)</span>
              <strong>
                {t.prompt_tokens.toLocaleString()} / {t.completion_tokens.toLocaleString()}
              </strong>
            </div>
          </div>
        )}

        <div className="tabs" role="tablist">
          <button
            role="tab"
            aria-selected={tab === "students"}
            className={`tab ${tab === "students" ? "active" : ""}`}
            onClick={() => setTab("students")}
          >
            Students ({students.length})
          </button>
          <button
            role="tab"
            aria-selected={tab === "sessions"}
            className={`tab ${tab === "sessions" ? "active" : ""}`}
            onClick={() => setTab("sessions")}
          >
            Sign-in sessions ({sessions.length})
          </button>
        </div>

        <div className="card" style={{ padding: 0 }}>
          {loading ? (
            <p className="muted" style={{ padding: 16 }}>
              Loading...
            </p>
          ) : tab === "students" ? (
            students.length === 0 ? (
              <p className="muted" style={{ padding: 16 }}>
                No students match.
              </p>
            ) : (
              <div className="table-scroll">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Student</th>
                      <th>Reg no</th>
                      <th>Sign-ins</th>
                      <th>Last sign-in</th>
                      <th>Time on system</th>
                      <th>Prompts</th>
                      <th>Experiments</th>
                      <th title="Average time the tutor took to reply, over this student's prompts that used the model">
                        Avg reply time
                      </th>
                      <th title="Total tokens sent to / received from the model across all of this student's prompts">
                        Tokens in / out (total)
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {students.map((s) => (
                      <tr key={s.student_id}>
                        <td>
                          <div>{s.name || "—"}</div>
                          <div className="muted">{s.email}</div>
                        </td>
                        <td className="mono">{s.reg_no || "—"}</td>
                        <td>{s.logins}</td>
                        <td>{fmtTime(s.last_login_at)}</td>
                        <td>{fmtDuration(s.active_seconds)}</td>
                        <td>
                          <strong>{s.prompts_total}</strong>
                        </td>
                        <td>{s.experiments.map((e) => e.toUpperCase()).join(", ") || "—"}</td>
                        <td>{fmtMs(s.avg_llm_latency_ms)}</td>
                        <td>
                          {s.prompt_tokens.toLocaleString()} / {s.completion_tokens.toLocaleString()}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )
          ) : sessions.length === 0 ? (
            <p className="muted" style={{ padding: 16 }}>
              No sign-ins recorded yet.
            </p>
          ) : (
            <div className="table-scroll">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Student</th>
                    <th>Reg no</th>
                    <th>Signed in</th>
                    <th>Signed out</th>
                    <th>Last seen</th>
                    <th>Duration</th>
                    <th>Ended by</th>
                  </tr>
                </thead>
                <tbody>
                  {sessions.map((s, i) => (
                    <tr key={`${s.student_id}-${s.login_at}-${i}`}>
                      <td>
                        <div>{s.name || "—"}</div>
                        <div className="muted">{s.email}</div>
                      </td>
                      <td className="mono">{s.reg_no || "—"}</td>
                      <td>{fmtTime(s.login_at)}</td>
                      <td>{fmtTime(s.logout_at)}</td>
                      <td>{fmtTime(s.last_seen_at)}</td>
                      <td>{fmtDuration(s.duration_seconds)}</td>
                      <td>{s.end_reason}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
