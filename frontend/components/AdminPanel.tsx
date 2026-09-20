"use client";

import { useEffect, useState } from "react";
import { api, ApiError, type AdminUser } from "@/lib/api";

export function AdminPanel() {
  const [query, setQuery] = useState("");
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");

  const searchUsers = async (q: string) => {

    setLoading(true);
    setError("");
    try {
      const res = await api.get<{ users: AdminUser[] }>(`/api/admin/users?q=${encodeURIComponent(q)}`);
      setUsers(res.users);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    searchUsers("");
  }, []);

  const handleSetRole = async (userId: string, role: "admin" | "faculty" | "student") => {
    setError("");
    setMsg("");
    try {
      const res = await api.patch<{ moved_to_student_in?: string[] }>(
        `/api/admin/users/${userId}/role`,
        { role },
      );
      const moved = res.moved_to_student_in?.length ?? 0;
      setMsg(
        moved > 0
          ? `Role updated. Their faculty access in ${moved} class${moved === 1 ? "" : "es"} was changed to student.`
          : "Role updated.",
      );
      searchUsers(query);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  };

  const handleClearOverride = async (userId: string) => {
    setError("");
    setMsg("");
    try {
      await api.del(`/api/admin/users/${userId}/role-override`);
      setMsg("Role override cleared. User reverted to domain-derived role.");
      searchUsers(query);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  };

  return (
    <div className="page">
      <h2 className="page-title">Platform admin</h2>
      <p className="muted" style={{ marginTop: 0 }}>
        Change anyone's platform role. Setting a role to student also moves any classes where they
        were faculty to student.
      </p>
        <div>
          {error && <div className="error">{error}</div>}
          {msg && <div className="notice" style={{ background: "var(--success-weak)", color: "var(--success)" }}>{msg}</div>}

          <div style={{ marginBottom: "16px", display: "flex", gap: "8px" }}>
            <input
              type="text"
              placeholder="Search user by email or name..."
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                searchUsers(e.target.value);
              }}
            />
          </div>

          <h3 style={{ fontSize: "0.95rem", margin: "0 0 8px" }}>User Platform Roles</h3>
          {users.length === 0 ? (
            <p className="muted">No users found.</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>User</th>
                  <th>Effective Role</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.id}>
                    <td>
                      <strong>{u.name || "No name"}</strong>
                      <br />
                      <span className="muted">{u.email}</span>
                    </td>
                    <td>
                      <span
                        className={
                          u.role === "admin"
                            ? "pill pill-escalated"
                            : u.role === "faculty"
                            ? "pill pill-pass"
                            : "pill pill-p1"
                        }
                      >
                        {u.role.toUpperCase()}
                      </span>
                      {u.role_override && (
                        <div style={{ fontSize: "0.7rem", color: "var(--warn)", marginTop: "2px" }}>
                          (Overridden)
                        </div>
                      )}
                    </td>
                    <td>
                      <div style={{ display: "flex", gap: "4px", flexWrap: "wrap" }}>
                        {u.role !== "admin" && (
                          <button
                            className="btn btn-sm btn-secondary"
                            onClick={() => handleSetRole(u.id, "admin")}
                          >
                            Make Admin
                          </button>
                        )}
                        {u.role !== "faculty" && (
                          <button
                            className="btn btn-sm btn-secondary"
                            onClick={() => handleSetRole(u.id, "faculty")}
                          >
                            Make Faculty
                          </button>
                        )}
                        {u.role !== "student" && (
                          <button
                            className="btn btn-sm btn-secondary"
                            onClick={() => handleSetRole(u.id, "student")}
                          >
                            Make Student
                          </button>
                        )}
                        {u.role_override && (
                          <button
                            className="btn btn-sm btn-danger"
                            onClick={() => handleClearOverride(u.id)}
                          >
                            Reset
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
    </div>
  );
}
