"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  api,
  ApiError,
  type Classroom,
  type Experiment,
  type ExperimentMarksRow,
  type MarksAnalyticsRow,
  type Me,
} from "@/lib/api";

export function MarksWorkspace({ me }: { me: Me }) {
  const router = useRouter();
  const searchParams = useSearchParams();

  const [classrooms, setClassrooms] = useState<Classroom[]>([]);
  const [classroomId, setClassroomId] = useState<string>(searchParams.get("classroom") || "");
  const [experiments, setExperiments] = useState<Experiment[]>([]);
  const [experimentId, setExperimentId] = useState<string>("exp01");

  const [rows, setRows] = useState<ExperimentMarksRow[]>([]);
  const [analytics, setAnalytics] = useState<MarksAnalyticsRow[]>([]);

  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");

  useEffect(() => {
    const loadClassrooms = async () => {
      try {
        const path = me.role === "admin" ? "/api/classrooms" : "/api/classrooms/mine";
        const res = await api.get<{ classrooms: Classroom[] }>(path);
        setClassrooms(res.classrooms);
        if (!classroomId && res.classrooms.length > 0) {
          setClassroomId(res.classrooms[0].id);
        }
      } catch (e) {
        setError(e instanceof ApiError ? e.message : String(e));
      }
    };
    const loadExperiments = async () => {
      try {
        const res = await api.get<{ experiments: Experiment[] }>("/api/classrooms/experiments");
        setExperiments(res.experiments);
      } catch {
        // Non-fatal: the experiment dropdown just stays on its default.
      }
    };
    loadClassrooms();
    loadExperiments();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!classroomId) return;
    const url = new URL(window.location.href);
    url.searchParams.set("classroom", classroomId);
    router.replace(url.pathname + url.search);
    loadMarks();
    loadAnalytics();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [classroomId, experimentId]);

  const loadMarks = async () => {
    if (!classroomId) return;
    setLoading(true);
    setError("");
    try {
      const res = await api.get<{ students: ExperimentMarksRow[] }>(
        `/api/marks/classrooms/${classroomId}/experiments/${experimentId}`
      );
      setRows(res.students);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  const loadAnalytics = async () => {
    if (!classroomId) return;
    try {
      const res = await api.get<{ experiments: MarksAnalyticsRow[] }>(
        `/api/marks/classrooms/${classroomId}/analytics`
      );
      setAnalytics(res.experiments);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  };

  const updateRow = (studentId: string, field: keyof ExperimentMarksRow, value: string) => {
    setRows((prev) =>
      prev.map((r) =>
        r.student_id === studentId
          ? { ...r, [field]: value === "" ? null : Number(value) }
          : r
      )
    );
  };

  const handleSaveAll = async () => {
    if (!classroomId) return;
    setSaving(true);
    setError("");
    setMsg("");
    try {
      await api.post(`/api/marks/classrooms/${classroomId}/experiments/${experimentId}`, {
        entries: rows.map((r) => ({
          student_id: r.student_id,
          pre_test_marks: r.pre_test_marks,
          pre_test_max: r.pre_test_max,
          post_test_marks: r.post_test_marks,
          post_test_max: r.post_test_max,
        })),
      });
      setMsg("Marks saved.");
      loadAnalytics();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const handleExport = async () => {
    if (!classroomId) return;
    setError("");
    try {
      const classroomName = classrooms.find((c) => c.id === classroomId)?.name || "classroom";
      await api.download(
        `/api/marks/classrooms/${classroomId}/export.xlsx`,
        `labtutor_marks_${classroomName.replace(/\s+/g, "_")}.xlsx`
      );
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  };

  return (
    <div style={{ maxWidth: "1000px", margin: "0 auto", padding: "24px 16px" }}>
      <h1 style={{ fontSize: "1.3rem", marginBottom: "4px" }}>Pre/Post-Test Marks &amp; Analytics</h1>
      <p className="muted" style={{ marginTop: 0 }}>
        Enter each student's pre- and post-test scores for an experiment, export the raw data,
        and see how much they improved.
      </p>

      {error && <div className="error">{error}</div>}
      {msg && (
        <div className="notice" style={{ background: "var(--success-weak)", color: "var(--success)" }}>
          {msg}
        </div>
      )}

      <div style={{ display: "flex", gap: "12px", flexWrap: "wrap", margin: "16px 0" }}>
        <div>
          <label className="muted" style={{ fontSize: "0.8rem", display: "block", marginBottom: "4px" }}>
            Classroom
          </label>
          <select value={classroomId} onChange={(e) => setClassroomId(e.target.value)}>
            {classrooms.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="muted" style={{ fontSize: "0.8rem", display: "block", marginBottom: "4px" }}>
            Experiment
          </label>
          <select value={experimentId} onChange={(e) => setExperimentId(e.target.value)}>
            {experiments.map((exp) => (
              <option key={exp.id} value={exp.id}>
                {exp.id.toUpperCase()}: {exp.title}
              </option>
            ))}
          </select>
        </div>
        <div style={{ display: "flex", alignItems: "flex-end", gap: "8px" }}>
          <button className="btn btn-primary btn-sm" onClick={handleSaveAll} disabled={saving || loading}>
            {saving ? "Saving..." : "Save all"}
          </button>
          <button className="btn btn-secondary btn-sm" onClick={handleExport} disabled={!classroomId}>
            Export to Excel
          </button>
        </div>
      </div>

      <div className="card">
        <h3 style={{ margin: "0 0 8px", fontSize: "0.95rem" }}>Roster ({rows.length})</h3>
        {loading ? (
          <p className="muted">Loading...</p>
        ) : rows.length === 0 ? (
          <p className="muted">No students enrolled in this classroom yet.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Student</th>
                <th>Pre-test</th>
                <th>/ max</th>
                <th>Post-test</th>
                <th>/ max</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.student_id}>
                  <td>
                    <strong>{r.student_name || "No name"}</strong>
                    <br />
                    <span className="muted">{r.student_email}</span>
                  </td>
                  <td>
                    <input
                      type="number"
                      style={{ width: "70px" }}
                      value={r.pre_test_marks ?? ""}
                      onChange={(e) => updateRow(r.student_id, "pre_test_marks", e.target.value)}
                    />
                  </td>
                  <td>
                    <input
                      type="number"
                      style={{ width: "60px" }}
                      value={r.pre_test_max}
                      onChange={(e) => updateRow(r.student_id, "pre_test_max", e.target.value)}
                    />
                  </td>
                  <td>
                    <input
                      type="number"
                      style={{ width: "70px" }}
                      value={r.post_test_marks ?? ""}
                      onChange={(e) => updateRow(r.student_id, "post_test_marks", e.target.value)}
                    />
                  </td>
                  <td>
                    <input
                      type="number"
                      style={{ width: "60px" }}
                      value={r.post_test_max}
                      onChange={(e) => updateRow(r.student_id, "post_test_max", e.target.value)}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="card">
        <h3 style={{ margin: "0 0 8px", fontSize: "0.95rem" }}>Analytics</h3>
        {analytics.length === 0 ? (
          <p className="muted">No graded pre/post pairs yet.</p>
        ) : (
          <div style={{ display: "flex", flexWrap: "wrap", gap: "12px" }}>
            {analytics.map((a) => (
              <div key={a.experiment_id} className="card" style={{ margin: 0, minWidth: "220px" }}>
                <strong className="mono">{a.experiment_id}</strong>
                {a.n === 0 ? (
                  <p className="muted" style={{ margin: "6px 0 0" }}>No graded pairs yet.</p>
                ) : (
                  <ul style={{ margin: "6px 0 0", paddingLeft: "18px", fontSize: "0.85rem" }}>
                    <li>n = {a.n}</li>
                    <li>Mean pre: {a.mean_pre?.toFixed(1)}%</li>
                    <li>Mean post: {a.mean_post?.toFixed(1)}%</li>
                    <li>Mean gain: {a.mean_gain?.toFixed(1)} pts</li>
                    <li>% improved: {a.percent_improved?.toFixed(0)}%</li>
                  </ul>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
