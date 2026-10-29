"use client";

import { useEffect, useState } from "react";
import {
  api,
  ApiError,
  type Classroom,
  type DashboardSubmission,
  type Escalation,
  type Experiment,
  type RosterFaculty,
  type RosterStudent,
} from "@/lib/api";

export function ClassroomPanel({
  classroom,
  experiments,
  onClassroomUpdated,
  onArchived,
}: {
  classroom: Classroom;
  experiments: Experiment[];
  onClassroomUpdated: () => void;
  /** Called after the class is archived ("deleted") so the caller can leave it. */
  onArchived: () => void;
}) {
  const [tab, setTab] = useState<"roster" | "session" | "settings" | "review">("roster");
  const [students, setStudents] = useState<RosterStudent[]>([]);
  const [faculty, setFaculty] = useState<RosterFaculty[]>([]);
  const [submissions, setSubmissions] = useState<DashboardSubmission[]>([]);
  const [escalations, setEscalations] = useState<Escalation[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");

  const [selectedExps, setSelectedExps] = useState<string[]>([
    classroom.active_experiment_id || experiments[0]?.id || "exp01",
  ]);
  const [joinOpen, setJoinOpen] = useState(classroom.join_open ?? true);
  const [newName, setNewName] = useState(classroom.name);
  const [confirmArchive, setConfirmArchive] = useState(false);

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
    if (tab === "review") loadActivity();
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
      await api.post(`/api/classrooms/${classroom.id}/sessions/start`, { experiment_ids: selectedExps });
      setMsg(`Class session started for ${selectedExps.join(", ")}!`);
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

  const handleRename = async () => {
    setError("");
    setMsg("");
    try {
      await api.patch(`/api/classrooms/${classroom.id}`, { name: newName.trim() });
      setMsg("Class renamed.");
      onClassroomUpdated();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  };

  const handleArchive = async () => {
    setError("");
    try {
      await api.del(`/api/classrooms/${classroom.id}`);
      onClassroomUpdated();
      onArchived();
    } catch (e) {
      setConfirmArchive(false);
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
    <div className="classroom-panel">
        <div className="modal-tabs" role="tablist">
          {(
            [
              ["roster", "Roster"],
              ["session", "Session"],
              ["settings", "Class settings"],
              ["review", "Review queue"],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              role="tab"
              aria-selected={tab === key}
              className={`modal-tab ${tab === key ? "active" : ""}`}
              onClick={() => setTab(key)}
            >
              {label}
            </button>
          ))}
        </div>

        <div className="panel-body">
          {error && <div className="error">{error}</div>}
          {msg && <div className="notice notice-ok">{msg}</div>}

          {/* Roster Tab */}
          {tab === "roster" && (
            <div>
              <h3 className="panel-h">Classroom faculty and co-faculty</h3>
              {faculty.length === 0 ? (
                <p className="muted">No faculty rows.</p>
              ) : (
                <div className="panel-table">
                <table>
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
                </div>
              )}

              <h3 className="panel-h">Enrolled students ({students.length})</h3>
              {students.length === 0 ? (
                <p className="muted">No students enrolled yet.</p>
              ) : (
                <div className="panel-table">
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
                </div>
              )}
            </div>
          )}

          {/* Session Tab */}
          {tab === "session" && (
            <div>
              <div className="card">
                <h3 className="panel-h">Class Session Status</h3>
                {classroom.active_session_id ? (
                  <div>
                    <span className="pill pill-pass">Session active</span>
                    <p className="panel-p">
                      Active experiments:{" "}
                      <strong>
                        {(classroom.active_experiment_ids?.length
                          ? classroom.active_experiment_ids
                          : [classroom.active_experiment_id]
                        ).join(", ")}
                      </strong>
                    </p>
                    <button className="btn btn-danger btn-sm" onClick={handleEndSession}>
                      End Class Session
                    </button>
                  </div>
                ) : (
                  <div>
                    <span className="pill pill-warn">No active session</span>
                    <p className="muted panel-p">
                      Select one or more experiments for this lab meeting. Students can open any of them:
                    </p>
                    <div role="group" aria-label="Experiments" className="exp-checks">
                      {[...experiments].sort((a, b) => a.id.localeCompare(b.id)).map((exp) => (
                        <label key={exp.id} className={`exp-check${selectedExps.includes(exp.id) ? " is-on" : ""}`}>
                          <input
                            type="checkbox"
                            checked={selectedExps.includes(exp.id)}
                            onChange={(e) =>
                              setSelectedExps((cur) =>
                                e.target.checked ? [...cur, exp.id] : cur.filter((id) => id !== exp.id)
                              )
                            }
                          />
                          {exp.id.toUpperCase()}: {exp.title} ({exp.priority})
                        </label>
                      ))}
                    </div>
                    <button
                      className="btn btn-primary btn-sm"
                      onClick={handleStartSession}
                      disabled={selectedExps.length === 0}
                    >
                      Start Session
                    </button>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Settings Tab */}
          {tab === "settings" && (
            <div>
              <div className="card">
                <h3 className="panel-h">Class name</h3>
                <div className="inline-form">
                  <input
                    value={newName}
                    maxLength={200}
                    onChange={(e) => setNewName(e.target.value)}
                    aria-label="Class name"
                  />
                  <button
                    className="btn btn-primary btn-sm"
                    onClick={handleRename}
                    disabled={!newName.trim() || newName.trim() === classroom.name}
                  >
                    Rename
                  </button>
                </div>
              </div>

              <div className="card">
                <h3 className="panel-h">Join Settings</h3>
                <p className="muted">Control student enrollment for this classroom section.</p>
                <div className="row-between">
                  <span>Student joining is <strong>{joinOpen ? "open" : "closed"}</strong></span>
                  <button className="btn btn-secondary btn-sm" onClick={handleToggleJoin}>
                    {joinOpen ? "Close Joining" : "Open Joining"}
                  </button>
                </div>
              </div>

              <div className="card">
                <h3 className="panel-h">Join Codes</h3>
                <div className="join-code panel-p">
                  <span className="muted">Student code</span>
                  <strong className="mono">{classroom.student_join_code || "N/A"}</strong>
                  <button className="btn btn-secondary btn-sm" onClick={() => handleRegenCode("student")}>
                    Regenerate
                  </button>
                </div>
                <div className="join-code">
                  <span className="muted">Faculty code</span>
                  <strong className="mono">{classroom.faculty_join_code || "N/A"}</strong>
                  <button className="btn btn-secondary btn-sm" onClick={() => handleRegenCode("faculty")}>
                    Regenerate
                  </button>
                </div>
              </div>

              <div className="card card-danger">
                <h3 className="panel-h">Delete this class</h3>
                <p className="muted">
                  The class is hidden and students can no longer join or chat in it. Any live session
                  is ended. <strong>Nothing is erased</strong>: every session, prompt, mark and
                  summary stays, stays in exports, and can be opened under Session reports. You can
                  restore the class there at any time.
                </p>
                {confirmArchive ? (
                  <div className="inline-form">
                    <button className="btn btn-danger btn-sm" onClick={handleArchive}>
                      Yes, delete &ldquo;{classroom.name}&rdquo;
                    </button>
                    <button className="btn btn-secondary btn-sm" onClick={() => setConfirmArchive(false)}>
                      Cancel
                    </button>
                  </div>
                ) : (
                  <button className="btn btn-danger btn-sm" onClick={() => setConfirmArchive(true)}>
                    Delete class
                  </button>
                )}
              </div>
            </div>
          )}

          {/* Activity Tab: submissions + escalations */}
          {tab === "review" && (
            <div>
              <h3 className="panel-h">
                Review queue {escalations.filter((e) => !e.resolved).length > 0 && (
                  <span className="pill pill-warn">
                    {escalations.filter((e) => !e.resolved).length} unresolved
                  </span>
                )}
              </h3>
              {escalations.length === 0 ? (
                <p className="muted">Nothing has needed human review yet.</p>
              ) : (
                <div className="review-list">
                  {escalations.map((e) => (
                    <div key={e.id} className="card review-item">
                      <div className="row-between">
                        <strong>{e.student_email}</strong>
                        <span className={e.resolved ? "pill pill-pass" : "pill pill-warn"}>
                          {e.resolved ? "resolved" : "needs review"}
                        </span>
                      </div>
                      <p className="panel-p">{e.reason}</p>
                      <p className="muted review-values">
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

              <h3 className="panel-h">
                All submissions ({submissions.length})
              </h3>
              {submissions.length === 0 ? (
                <p className="muted">No submissions yet.</p>
              ) : (
                <div className="panel-table">
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
                </div>
              )}
            </div>
          )}

        </div>
    </div>
  );
}
