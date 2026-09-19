"use client";

import { Fragment, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  api,
  ApiError,
  type Classroom,
  type Me,
  type SessionListItem,
  type SessionReport,
  type SessionReportStudent,
  type TranscriptMessage,
} from "@/lib/api";
import { AppNav } from "./AppNav";

function fmtTime(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, {
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

function fmtMarks(m: SessionReportStudent["marks"]): string {
  if (!m) return "—";
  const part = (v: number | null, max: number) => (v === null ? "—" : `${v}/${max}`);
  return `pre ${part(m.pre, m.pre_max)} · post ${part(m.post, m.post_max)}`;
}

export function SessionsWorkspace({ me }: { me: Me }) {
  const searchParams = useSearchParams();
  const [classrooms, setClassrooms] = useState<Classroom[]>([]);
  const [classroomId, setClassroomId] = useState(searchParams.get("classroom") || "");
  const [sessions, setSessions] = useState<SessionListItem[]>([]);
  const [sessionId, setSessionId] = useState("");
  const [report, setReport] = useState<SessionReport | null>(null);
  const [openStudent, setOpenStudent] = useState("");
  const [transcripts, setTranscripts] = useState<Record<string, TranscriptMessage[] | "loading">>({});
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [loading, setLoading] = useState(false);

  const fail = (e: unknown) => setError(e instanceof ApiError ? e.message : String(e));

  const loadClassrooms = async () => {
    try {
      const path =
        me.role === "admin"
          ? "/api/classrooms?include_archived=true"
          : "/api/classrooms/mine?include_archived=true";
      const res = await api.get<{ classrooms: Classroom[] }>(path);
      setClassrooms(res.classrooms);
      if (!classroomId && res.classrooms.length > 0) setClassroomId(res.classrooms[0].id);
    } catch (e) {
      fail(e);
    }
  };

  useEffect(() => {
    loadClassrooms();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!classroomId) return;
    (async () => {
      setError("");
      setReport(null);
      setSessionId("");
      setOpenStudent("");
      setTranscripts({});
      try {
        const res = await api.get<{ sessions: SessionListItem[] }>(
          `/api/classrooms/${classroomId}/sessions`,
        );
        setSessions(res.sessions);
        const wanted = searchParams.get("session");
        const first = res.sessions.find((s) => s.id === wanted) ?? res.sessions[0];
        if (first) setSessionId(first.id);
      } catch (e) {
        setSessions([]);
        fail(e);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [classroomId]);

  useEffect(() => {
    if (!classroomId || !sessionId) return;
    (async () => {
      setLoading(true);
      setError("");
      setOpenStudent("");
      setTranscripts({});
      try {
        setReport(
          await api.get<SessionReport>(`/api/classrooms/${classroomId}/sessions/${sessionId}/report`),
        );
      } catch (e) {
        setReport(null);
        fail(e);
      } finally {
        setLoading(false);
      }
    })();
  }, [classroomId, sessionId]);

  const toggleStudent = async (studentId: string) => {
    if (openStudent === studentId) {
      setOpenStudent("");
      return;
    }
    setOpenStudent(studentId);
    if (transcripts[studentId]) return;
    setTranscripts((t) => ({ ...t, [studentId]: "loading" }));
    try {
      const res = await api.get<{ messages: TranscriptMessage[] }>(
        `/api/classrooms/${classroomId}/sessions/${sessionId}/students/${studentId}/transcript`,
      );
      setTranscripts((t) => ({ ...t, [studentId]: res.messages }));
    } catch (e) {
      setTranscripts((t) => {
        const next = { ...t };
        delete next[studentId];
        return next;
      });
      fail(e);
    }
  };

  const restore = async () => {
    setError("");
    setMsg("");
    try {
      await api.post(`/api/classrooms/${classroomId}/restore`);
      setMsg("Class restored. It appears in your class list again.");
      await loadClassrooms();
    } catch (e) {
      fail(e);
    }
  };

  const classroom = classrooms.find((c) => c.id === classroomId);
  const t = report?.totals;

  return (
    <>
      <AppNav me={me} current="/faculty/sessions" />
      <div className="page">
        <h1 className="page-title">Session reports</h1>
        <p className="muted" style={{ marginTop: 0 }}>
          Every past lab session for a class: who took part, what they asked, how the tutor
          answered, attempts, diagnoses and marks. Nothing here is deleted when a session ends or a
          class is archived.
        </p>

        {error && <div className="error">{error}</div>}
        {msg && <div className="notice">{msg}</div>}

        <div className="toolbar">
          <div className="field">
            <label className="muted">Classroom</label>
            <select value={classroomId} onChange={(e) => setClassroomId(e.target.value)}>
              {classrooms.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                  {c.archived ? " (archived)" : ""}
                </option>
              ))}
            </select>
          </div>
          {classroom?.archived && (
            <div className="field">
              <label className="muted">&nbsp;</label>
              <button className="btn btn-secondary" onClick={restore}>
                Restore this class
              </button>
            </div>
          )}
        </div>

        {classroom?.archived && (
          <div className="notice">
            This class is archived. Its data is intact and readable here; students cannot join or
            chat until you restore it.
          </div>
        )}

        <h2 style={{ fontSize: "1rem", margin: "16px 0 8px" }}>Sessions ({sessions.length})</h2>
        {sessions.length === 0 ? (
          <p className="muted">No sessions have been run for this class yet.</p>
        ) : (
          <div className="card table-scroll" style={{ padding: 0 }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Started</th>
                  <th>Experiment</th>
                  <th>Status</th>
                  <th>Students</th>
                  <th>Prompts</th>
                  <th>Duration</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {sessions.map((s) => (
                  <tr key={s.id} style={s.id === sessionId ? { background: "var(--accent-weak)" } : undefined}>
                    <td>{fmtTime(s.started_at)}</td>
                    <td>
                      <strong>{s.experiment_id.toUpperCase()}</strong>{" "}
                      <span className="muted">{s.experiment_title}</span>
                    </td>
                    <td>
                      <span className={s.status === "active" ? "pill pill-pass" : "pill pill-p1"}>
                        {s.status}
                      </span>
                    </td>
                    <td>{s.students}</td>
                    <td>{s.prompts}</td>
                    <td>{s.duration_minutes === null ? "—" : `${s.duration_minutes} min`}</td>
                    <td>
                      <button
                        className="btn btn-sm btn-secondary"
                        onClick={() => setSessionId(s.id)}
                        disabled={s.id === sessionId}
                      >
                        {s.id === sessionId ? "Viewing" : "View report"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {loading && <p className="muted">Loading report…</p>}

        {report && t && (
          <>
            <h2 style={{ fontSize: "1rem", margin: "20px 0 8px" }}>
              {report.session.experiment_id.toUpperCase()} · {fmtTime(report.session.started_at)}
            </h2>
            <div className="stat-grid">
              <div className="card stat"><span className="muted">Students</span><strong>{t.students}</strong></div>
              <div className="card stat"><span className="muted">Prompts</span><strong>{t.prompts}</strong></div>
              <div className="card stat"><span className="muted">Attempts</span><strong>{t.attempts}</strong></div>
              <div className="card stat"><span className="muted">Diagnoses</span><strong>{t.diagnoses}</strong></div>
              <div className="card stat">
                <span className="muted">Fallback replies</span>
                <strong>{t.fallback_replies}</strong>
              </div>
            </div>

            {report.students.length === 0 ? (
              <p className="muted">No student took part in this session.</p>
            ) : (
              <div className="card table-scroll" style={{ padding: 0 }}>
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Student</th>
                      <th>Prompts</th>
                      <th>Avg reply</th>
                      <th>Attempts</th>
                      <th>Diagnoses</th>
                      <th>Marks</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {report.students.map((s) => (
                      <Fragment key={s.student_id}>
                        <tr>
                          <td>
                            <strong>{s.name || s.email}</strong>
                            <br />
                            <span className="muted">{s.reg_no || s.email}</span>
                          </td>
                          <td>{s.prompts}</td>
                          <td>{fmtMs(s.avg_latency_ms)}</td>
                          <td>
                            {s.attempts_passed}/{s.attempts}
                          </td>
                          <td>{s.diagnoses.length}</td>
                          <td>{fmtMarks(s.marks)}</td>
                          <td>
                            <button
                              className="btn btn-sm btn-secondary"
                              aria-expanded={openStudent === s.student_id}
                              onClick={() => toggleStudent(s.student_id)}
                            >
                              {openStudent === s.student_id ? "Hide" : "Details"}
                            </button>
                          </td>
                        </tr>
                        {openStudent === s.student_id && (
                          <tr>
                            <td colSpan={7} style={{ whiteSpace: "normal", background: "var(--surface-hover)" }}>
                              <StudentDetail
                                student={s}
                                transcript={transcripts[s.student_id]}
                              />
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </div>
    </>
  );
}

function StudentDetail({
  student,
  transcript,
}: {
  student: SessionReportStudent;
  transcript: TranscriptMessage[] | "loading" | undefined;
}) {
  return (
    <div style={{ maxWidth: "100%" }}>
      <p className="muted" style={{ margin: "0 0 8px" }}>
        {student.email} · first prompt {fmtTime(student.first_at)} · last {fmtTime(student.last_at)} ·{" "}
        {student.tutor_replies} tutor replies
        {student.fallback_replies > 0 ? ` (${student.fallback_replies} fallback)` : ""}
      </p>

      {student.summary && (
        <div className="card" style={{ margin: "0 0 10px", padding: "10px 12px" }}>
          <strong style={{ fontSize: "0.85rem" }}>
            Session summary {student.summary_flagged && <span className="pill pill-warn">flagged</span>}
          </strong>
          <p style={{ margin: "4px 0 0", fontSize: "0.85rem", whiteSpace: "pre-wrap" }}>{student.summary}</p>
        </div>
      )}

      {student.diagnoses.length > 0 && (
        <div style={{ margin: "0 0 10px" }}>
          <strong style={{ fontSize: "0.85rem" }}>Diagnoses</strong>
          <ul style={{ margin: "4px 0 0", paddingLeft: "1.2em", fontSize: "0.85rem" }}>
            {student.diagnoses.map((d, i) => (
              <li key={i}>
                <span className={`pill pill-${d.status}`}>{d.status}</span> tier {d.tier}
                {d.signature_code ? ` · ${d.signature_code}` : ""} · {d.action.replace(/_/g, " ")}
                {d.low_confidence ? " · low confidence" : ""}
              </li>
            ))}
          </ul>
        </div>
      )}

      <strong style={{ fontSize: "0.85rem" }}>Conversation</strong>
      {transcript === undefined || transcript === "loading" ? (
        <p className="muted">Loading conversation…</p>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: "8px", marginTop: "6px" }}>
          {transcript.map((m) => (
            <div
              key={m.id}
              style={{
                alignSelf: m.author === "student" ? "flex-end" : "flex-start",
                maxWidth: "min(100%, 640px)",
                padding: "8px 12px",
                borderRadius: "10px",
                background: m.author === "student" ? "var(--accent-weak)" : "var(--surface)",
                border: `1px solid ${m.author === "student" ? "var(--accent-border)" : "var(--border)"}`,
                fontSize: "0.85rem",
                lineHeight: 1.5,
                wordBreak: "break-word",
              }}
            >
              <div className="muted" style={{ fontSize: "0.7rem", marginBottom: "2px" }}>
                {m.author === "student" ? "Student" : "Tutor"} · {fmtTime(m.created_at)}
                {m.author === "tutor" && typeof m.meta.llm_latency_ms === "number"
                  ? ` · ${fmtMs(m.meta.llm_latency_ms)}`
                  : ""}
                {m.author === "tutor" && m.meta.fallback_used ? " · fallback" : ""}
              </div>
              {m.author === "tutor" ? (
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.content}</ReactMarkdown>
              ) : (
                <span style={{ whiteSpace: "pre-wrap" }}>{m.content}</span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
