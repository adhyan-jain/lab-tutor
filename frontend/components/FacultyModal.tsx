"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  api,
  ApiError,
  type Classroom,
  type ClassSessionInfo,
  type DashboardSubmission,
  type Escalation,
  type Experiment,
  type RosterFaculty,
  type RosterStudent,
  type StudentSummary,
} from "@/lib/api";
import { CloseIcon } from "@/components/Icons";

export function FacultyModal({
  classroom,
  experiments,
  onClose,
  onClassroomUpdated,
}: {
  classroom: Classroom;
  experiments: Experiment[];
  onClose: () => void;
  onClassroomUpdated: () => void;
}) {
  const router = useRouter();
  const [tab, setTab] = useState<"roster" | "session" | "settings" | "activity" | "summaries">("roster");
  const [students, setStudents] = useState<RosterStudent[]>([]);
  const [faculty, setFaculty] = useState<RosterFaculty[]>([]);
  const [summaries, setSummaries] = useState<StudentSummary[]>([]);
  const [sessions, setSessions] = useState<ClassSessionInfo[]>([]);
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [submissions, setSubmissions] = useState<DashboardSubmission[]>([]);
  const [escalations, setEscalations] = useState<Escalation[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");

  const [selectedExp, setSelectedExp] = useState(classroom.active_experiment_id || experiments[0]?.id || "exp01");
  const [joinOpen, setJoinOpen] = useState(classroom.join_open ?? true);

  const loadRoster = async () => {
    setLoading(true);
    setError("");
    try {
      const [sRes, fRes] = await Promise.all([
        api.get<{ students: RosterStudent[] }>(`/api/classrooms/${classroom.id}/roster`),
        api.get<{ faculty: RosterFaculty[] }>(`/api/classrooms/${classroom.id}/faculty`),
      ]);
      setStudents(sRes.students);
      setFaculty(fRes.faculty);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  const loadSessionSummaries = async (sessionId: string) => {
    setLoading(true);
    setError("");
    try {
      const res = await api.get<{ summaries: StudentSummary[] }>(
        `/api/dashboard/classrooms/${classroom.id}/sessions/${sessionId}/summaries`
      );
      setSummaries(res.summaries);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  const loadSummaries = async () => {
    setLoading(true);
    setError("");
    try {
      const res = await api.get<{ sessions: ClassSessionInfo[] }>(
        `/api/dashboard/classrooms/${classroom.id}/sessions`
      );
      setSessions(res.sessions);
      const defaultId = classroom.active_session_id || res.sessions[0]?.id || null;
      setSelectedSessionId(defaultId);
      if (defaultId) await loadSessionSummaries(defaultId);
      else setSummaries([]);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  const loadActivity = async () => {
    setLoading(true);
    setError("");
    try {
      const [subRes, escRes] = await Promise.all([
        api.get<{ submissions: DashboardSubmission[] }>(
          `/api/dashboard/classrooms/${classroom.id}/submissions`,
        ),
        api.get<{ escalations: Escalation[] }>(
          `/api/dashboard/classrooms/${classroom.id}/escalations?unresolved_only=false`,
        ),
      ]);
      setSubmissions(subRes.submissions);
      setEscalations(escRes.escalations);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  const handleResolveEscalation = async (id: string) => {
    setError("");
    try {
      await api.post(`/api/dashboard/escalations/${id}/resolve`, {});
      loadActivity();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  };

  useEffect(() => {
    if (tab === "roster") loadRoster();
    if (tab === "summaries") loadSummaries();
    if (tab === "activity") loadActivity();
  }, [tab]);

  const handlePromote = async (studentId: string) => {
    setError("");
    setMsg("");
    try {
      await api.post(`/api/classrooms/${classroom.id}/promote`, { student_user_id: studentId });
      setMsg("Student promoted to classroom co-faculty successfully!");
      loadRoster();
      onClassroomUpdated();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  };

  const handleDemote = async (userId: string) => {
    setError("");
    setMsg("");
    try {
      await api.post(`/api/classrooms/${classroom.id}/demote`, { user_id: userId });
      setMsg("Co-faculty demoted to student successfully!");
      loadRoster();
      onClassroomUpdated();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  };

  const handleStartSession = async () => {
    setError("");
    setMsg("");
    try {
      await api.post(`/api/classrooms/${classroom.id}/sessions/start`, { experiment_id: selectedExp });
      setMsg(`Class session started for ${selectedExp}!`);
      onClassroomUpdated();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  };

  const handleEndSession = async () => {
    if (!classroom.active_session_id) return;
    setError("");
    setMsg("");
    try {
      await api.post(`/api/classrooms/${classroom.id}/sessions/${classroom.active_session_id}/end`);
      setMsg("Class session ended. Post-session summaries are being generated.");
      onClassroomUpdated();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  };

  const handleToggleJoin = async () => {
    setError("");
    try {
      const updated = await api.patch<{ join_open: boolean }>(`/api/classrooms/${classroom.id}/join-open`, {
        join_open: !joinOpen,
      });
      setJoinOpen(updated.join_open);
      onClassroomUpdated();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  };

  const handleRegenCode = async (which: "student" | "faculty") => {
    setError("");
    try {
      await api.post(`/api/classrooms/${classroom.id}/regenerate-code`, { which });
      setMsg(`Regenerated ${which} join code!`);
      onClassroomUpdated();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div>
            <h2 style={{ margin: 0, fontSize: "1.1rem" }}>Classroom Management</h2>
            <p className="muted" style={{ margin: 0 }}>{classroom.name}</p>
          </div>
          <div style={{ display: "flex", gap: "8px" }}>
            <button
              className="btn btn-secondary btn-sm"
              onClick={() => router.push(`/faculty/marks?classroom=${classroom.id}`)}
            >
              Marks &amp; Analytics
            </button>
            <button className="btn btn-secondary btn-sm" onClick={onClose} style={{ display: "flex", alignItems: "center", gap: "6px" }}>
              <CloseIcon size={14} /> Close
            </button>
          </div>
        </div>

        <div style={{ display: "flex", borderBottom: "1px solid var(--border)", background: "var(--surface-hover)" }}>
          {(["roster", "session", "settings", "activity", "summaries"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              style={{
                flex: 1,
                padding: "10px",
                border: "none",
                background: tab === t ? "var(--surface)" : "transparent",
                borderBottom: tab === t ? "2px solid var(--accent)" : "none",
                color: tab === t ? "var(--accent)" : "var(--muted)",
                fontWeight: tab === t ? 600 : 400,
                cursor: "pointer",
                fontSize: "0.85rem",
                textTransform: "capitalize",
              }}
            >
              {t}
            </button>
          ))}
        </div>

        <div className="modal-body">
          {error && <div className="error">{error}</div>}
          {msg && <div className="notice" style={{ background: "var(--success-weak)", color: "var(--success)" }}>{msg}</div>}

          {/* Roster Tab */}
          {tab === "roster" && (
            <div>
              <h3 style={{ fontSize: "0.95rem", margin: "0 0 8px" }}>Classroom Faculty / Co-Faculty</h3>
              {faculty.length === 0 ? (
                <p className="muted">No faculty rows.</p>
              ) : (
                <table style={{ marginBottom: "20px" }}>
                  <thead>
                    <tr>
                      <th>Name / Email</th>
                      <th>Type</th>
                      <th>Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {faculty.map((f) => (
                      <tr key={f.id}>
                        <td>
                          <strong>{f.name || "No name"}</strong>
                          <br />
                          <span className="muted">{f.email}</span>
                        </td>
                        <td>
                          <span className={f.promoted ? "pill pill-warn" : "pill pill-pass"}>
                            {f.promoted ? "Promoted Co-Faculty" : "Platform Faculty"}
                          </span>
                        </td>
                        <td>
                          {f.promoted && (
                            <button
                              className="btn btn-sm btn-secondary"
                              onClick={() => handleDemote(f.id)}
                            >
                              Demote to Student
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}

              <h3 style={{ fontSize: "0.95rem", margin: "16px 0 8px" }}>Enrolled Students ({students.length})</h3>
              {students.length === 0 ? (
                <p className="muted">No students enrolled yet.</p>
              ) : (
                <table>
                  <thead>
                    <tr>
                      <th>Name / Email</th>
                      <th>Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {students.map((s) => (
                      <tr key={s.id}>
                        <td>
                          <strong>{s.name || "No name"}</strong>
                          <br />
                          <span className="muted">{s.email}</span>
                        </td>
                        <td>
                          <button
                            className="btn btn-sm btn-primary"
                            onClick={() => handlePromote(s.id)}
                          >
                            Promote to Co-Faculty
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}

          {/* Session Tab */}
          {tab === "session" && (
            <div>
              <div className="card">
                <h3 style={{ margin: "0 0 6px", fontSize: "0.95rem" }}>Class Session Status</h3>
                {classroom.active_session_id ? (
                  <div>
                    <span className="pill pill-pass">ACTIVE SESSION</span>
                    <p style={{ margin: "8px 0" }}>
                      Active experiment: <strong>{classroom.active_experiment_id}</strong>
                    </p>
                    <button className="btn btn-danger btn-sm" onClick={handleEndSession}>
                      End Class Session
                    </button>
                  </div>
                ) : (
                  <div>
                    <span className="pill pill-warn">NO ACTIVE SESSION</span>
                    <p className="muted" style={{ margin: "8px 0 12px" }}>
                      Select an experiment to start a lab meeting for your students:
                    </p>
                    <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
                      <select
                        value={selectedExp}
                        onChange={(e) => setSelectedExp(e.target.value)}
                        style={{ flex: 1 }}
                      >
                        {experiments.map((exp) => (
                          <option key={exp.id} value={exp.id}>
                            {exp.id.toUpperCase()}: {exp.title} ({exp.priority})
                          </option>
                        ))}
                      </select>
                      <button className="btn btn-primary btn-sm" onClick={handleStartSession}>
                        Start Session
                      </button>
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Settings Tab */}
          {tab === "settings" && (
            <div>
              <div className="card">
                <h3 style={{ margin: "0 0 6px", fontSize: "0.95rem" }}>Join Settings</h3>
                <p className="muted">Control student enrollment for this classroom section.</p>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <span>Student Joining is: <strong>{joinOpen ? "OPEN" : "CLOSED"}</strong></span>
                  <button className="btn btn-secondary btn-sm" onClick={handleToggleJoin}>
                    {joinOpen ? "Close Joining" : "Open Joining"}
                  </button>
                </div>
              </div>

              <div className="card">
                <h3 style={{ margin: "0 0 6px", fontSize: "0.95rem" }}>Join Codes</h3>
                <div style={{ marginBottom: "12px" }}>
                  <span className="muted">Student Code: </span>
                  <strong className="mono">{classroom.student_join_code || "N/A"}</strong>
                  <button
                    className="btn btn-secondary btn-sm"
                    style={{ marginLeft: "10px" }}
                    onClick={() => handleRegenCode("student")}
                  >
                    Regenerate
                  </button>
                </div>
                <div>
                  <span className="muted">Faculty Code: </span>
                  <strong className="mono">{classroom.faculty_join_code || "N/A"}</strong>
                  <button
                    className="btn btn-secondary btn-sm"
                    style={{ marginLeft: "10px" }}
                    onClick={() => handleRegenCode("faculty")}
                  >
                    Regenerate
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* Activity Tab: submissions + escalations */}
          {tab === "activity" && (
            <div>
              <h3 style={{ fontSize: "0.95rem", margin: "0 0 8px" }}>
                Review queue {escalations.filter((e) => !e.resolved).length > 0 && (
                  <span className="pill pill-warn">
                    {escalations.filter((e) => !e.resolved).length} unresolved
                  </span>
                )}
              </h3>
              {escalations.length === 0 ? (
                <p className="muted">Nothing has needed human review yet.</p>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: "8px", marginBottom: "20px" }}>
                  {escalations.map((e) => (
                    <div key={e.id} className="card" style={{ padding: "10px", margin: 0 }}>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                        <strong>{e.student_email}</strong>
                        <span className={e.resolved ? "pill pill-pass" : "pill pill-warn"}>
                          {e.resolved ? "resolved" : "needs review"}
                        </span>
                      </div>
                      <p style={{ margin: "4px 0" }}>{e.reason}</p>
                      <p className="muted" style={{ margin: "0 0 6px", fontSize: "0.8rem" }}>
                        Reported {e.reported_value ?? "—"} · Expected {e.expected_value ?? "—"}
                      </p>
                      {!e.resolved && (
                        <button
                          className="btn btn-sm btn-secondary"
                          onClick={() => handleResolveEscalation(e.id)}
                        >
                          Mark resolved
                        </button>
                      )}
                    </div>
                  ))}
                </div>
              )}

              <h3 style={{ fontSize: "0.95rem", margin: "16px 0 8px" }}>
                All submissions ({submissions.length})
              </h3>
              {submissions.length === 0 ? (
                <p className="muted">No submissions yet.</p>
              ) : (
                <table>
                  <thead>
                    <tr>
                      <th>Student</th>
                      <th>Experiment</th>
                      <th>Status</th>
                      <th>Reported</th>
                    </tr>
                  </thead>
                  <tbody>
                    {submissions.map((s) => (
                      <tr key={s.submission_id}>
                        <td>{s.student_email}</td>
                        <td className="mono">{s.experiment_id}</td>
                        <td>
                          <span className={`pill pill-${s.status}`}>{s.status}</span>
                        </td>
                        <td>{s.reported_value ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}

          {/* Summaries Tab */}
          {tab === "summaries" && (
            <div>
              <h3 style={{ fontSize: "0.95rem", margin: "0 0 8px" }}>Post-Session Student Activity Summaries</h3>
              {sessions.length > 0 && (
                <div style={{ marginBottom: "12px" }}>
                  <label className="muted" style={{ fontSize: "0.8rem", display: "block", marginBottom: "4px" }}>
                    Class session
                  </label>
                  <select
                    value={selectedSessionId ?? ""}
                    onChange={(e) => {
                      setSelectedSessionId(e.target.value);
                      loadSessionSummaries(e.target.value);
                    }}
                  >
                    {sessions.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.experiment_id} · {new Date(s.started_at).toLocaleString()}
                        {s.status === "active" ? " (active)" : " (ended)"}
                      </option>
                    ))}
                  </select>
                </div>
              )}
              {summaries.length === 0 ? (
                <p className="muted">No summaries generated yet for this session.</p>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
                  {summaries.map((s, idx) => (
                    <div key={idx} className="card" style={{ padding: "12px", margin: 0 }}>
                      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "4px" }}>
                        <strong>{s.student_email}</strong>
                        {s.flagged && <span className="pill pill-warn">FLAGGED ({s.flag_reason})</span>}
                      </div>
                      <p style={{ margin: 0, fontSize: "0.85rem", whiteSpace: "pre-wrap" }}>{s.text}</p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
