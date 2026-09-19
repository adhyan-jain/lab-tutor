"use client";

import { useEffect, useState } from "react";
import { api, ApiError, type Me } from "@/lib/api";
import { ThemeToggle } from "./ThemeToggle";

/**
 * Loads the signed-in identity and renders the page for it.
 *
 * The role shown here is presentation only. Every role-gated endpoint
 * re-checks the caller's role server-side on that request, so hiding a
 * button is a convenience, never the access control.
 */
export function Shell({
  requireRole,
  children,
}: {
  requireRole?: Me["role"] | Me["role"][];
  children: (me: Me) => React.ReactNode;
}) {
  const allowedRoles = requireRole
    ? Array.isArray(requireRole)
      ? requireRole
      : [requireRole]
    : null;
  const [me, setMe] = useState<Me | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "anonymous">("loading");

  useEffect(() => {
    let cancelled = false;
    api
      .get<Me>("/api/auth/me")
      .then((identity) => {
        if (cancelled) return;
        setMe(identity);
        setState("ready");
      })
      .catch((error) => {
        if (cancelled) return;
        if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
          setState("anonymous");
        } else {
          setState("anonymous");
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (state === "loading") {
    return (
      <AuthCard busy>
        <p className="auth-wordmark">LabTutor</p>
        <p className="auth-tagline">Checking your session…</p>
      </AuthCard>
    );
  }

  if (state === "anonymous" || !me) {
    return (
      <AuthCard>
        <p className="auth-wordmark">LabTutor</p>
        <p className="auth-tagline">Applied Chemistry Lab, VIT</p>
        <hr className="auth-divider" />
        <p className="auth-body">Sign in with your institutional Google account to continue.</p>
        <a className="btn btn-primary" href="/api/auth/login">
          Sign in with Google
        </a>
        <p className="auth-fineprint">
          Access is limited to your VIT student or staff email. Your role
          follows automatically from that address.
        </p>
      </AuthCard>
    );
  }

  if (allowedRoles && !allowedRoles.includes(me.role)) {
    return (
      <AuthCard>
        <p className="auth-wordmark">LabTutor</p>
        <p className="auth-tagline">This page isn't available to you</p>
        <hr className="auth-divider" />
        <p className="auth-body">
          This page is for {allowedRoles.join(" or ")}. You're signed in as{" "}
          {me.email} ({me.role}).
        </p>
        <a className="btn btn-secondary" href="/">
          Go back
        </a>
      </AuthCard>
    );
  }

  if (!me.profile_complete) {
    return (
      <AuthCard>
        <p className="auth-wordmark">LabTutor</p>
        <p className="auth-tagline">One last step</p>
        <hr className="auth-divider" />
        <ProfileCompletionForm me={me} onDone={setMe} />
      </AuthCard>
    );
  }

  return (
    <>
      <header className="bar">
        <strong>LabTutor</strong>
        <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
          <span className="muted">
            {me.email} · {me.role}
          </span>
          <ThemeToggle />
        </div>
      </header>
      <main>{children(me)}</main>
    </>
  );
}

/** The shared shell for every pre-app screen (signed out, checking the
 * session, wrong role for this page, finishing onboarding): a burette
 * reading -- graduated marks read top-to-bottom the way a real one is,
 * a tinted fill standing in for the liquid level. `busy` animates the
 * fill (a titration in progress) while the session check is in flight;
 * everywhere else it sits at a fixed level. */
function AuthCard({ busy = false, children }: { busy?: boolean; children: React.ReactNode }) {
  const marks = [0, 5, 10, 15, 20, 25];
  return (
    <div className="auth-shell" data-busy={busy}>
      <div className="auth-topbar">
        <ThemeToggle />
      </div>
      <div className="auth-center">
        <div className="auth-card">
          <div className="auth-scale" aria-hidden="true">
            <div className="auth-scale-fill" />
            <div className="auth-scale-marks">
              {marks.map((m) => (
                <div className="auth-scale-mark" key={m}>
                  <span>{m}</span>
                </div>
              ))}
            </div>
          </div>
          <div className="auth-content">{children}</div>
        </div>
      </div>
    </div>
  );
}

function ProfileCompletionForm({
  me,
  onDone,
}: {
  me: Me;
  onDone: (me: Me) => void;
}) {
  const [name, setName] = useState(me.name ?? "");
  const [regNo, setRegNo] = useState(me.reg_no ?? "");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  // Required for students (enforced server-side too), never asked of
  // faculty/admin.
  const showRegNo = me.role === "student";

  return (
    <div>
      {error && <div className="error">{error}</div>}
      <p className="auth-body">
        Signed in as {me.email}. What should we call you?
      </p>
      <label>
        <span>Full name</span>
        <input value={name} onChange={(e) => setName(e.target.value)} />
      </label>
      {showRegNo && (
        <label>
          <span>Registration number</span>
          <input
            value={regNo}
            onChange={(e) => setRegNo(e.target.value)}
            className="mono"
            placeholder="e.g. 21BCE1234"
            autoCapitalize="characters"
            required
          />
        </label>
      )}
      <button
        className="btn btn-primary"
        disabled={saving || !name.trim() || (showRegNo && !regNo.trim())}
        onClick={async () => {
          setSaving(true);
          setError("");
          try {
            const updated = await api.post<Me>("/api/auth/complete-profile", {
              name: name.trim(),
              reg_no: showRegNo ? regNo.trim() || null : null,
            });
            onDone(updated);
          } catch (e) {
            setError(e instanceof ApiError ? e.message : String(e));
          } finally {
            setSaving(false);
          }
        }}
      >
        {saving ? "Saving…" : "Continue"}
      </button>
    </div>
  );
}
