"use client";

import { useEffect, useState } from "react";
import { api, ApiError, type PracticalProgress } from "@/lib/api";
import { CheckIcon } from "./Icons";

/**
 * Practical progress for one chat thread: done / now / next, from the backend.
 *
 * It never advances on its own. "I've completed this step" asks the backend
 * to record it (self-report experiments) or, where the engine verifies
 * results, sends the message through the normal chat so the tutor asks for
 * them; the strip only ever shows what the server returns. "Explain this
 * step" and "I'm stuck" are ordinary chat messages and change nothing here.
 */
export function PracticalTracker({
  threadId,
  refreshKey,
  disabled,
  onSend,
}: {
  threadId: string | null;
  /** Bumped after every reply, so verified progress made in the chat shows up. */
  refreshKey: number;
  disabled: boolean;
  onSend: (text: string) => void;
}) {
  const [data, setData] = useState<PracticalProgress | null>(null);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");

  useEffect(() => {
    setNote("");
    if (!threadId) {
      setData(null);
      return;
    }
    let cancelled = false;
    api
      .get<PracticalProgress>(`/api/chat/threads/${threadId}/practical`)
      .then((d) => !cancelled && setData(d))
      .catch(() => !cancelled && setData(null));
    return () => {
      cancelled = true;
    };
  }, [threadId, refreshKey]);

  if (!data || !data.available) return null;
  const current = data.current !== null ? data.steps[data.current] : null;

  const complete = async () => {
    if (!current || !threadId) return;
    if (data.kind === "verified") {
      onSend("I've completed this step");
      return;
    }
    setBusy(true);
    setNote("");
    try {
      setData(
        await api.post<PracticalProgress>(`/api/chat/threads/${threadId}/practical/complete`, {
          step_index: current.index,
        })
      );
    } catch (e) {
      setNote(e instanceof ApiError ? e.message : "Could not save that. Please try again.");
    } finally {
      setBusy(false);
    }
  };

  const summary = current
    ? `Step ${current.index + 1} of ${data.total}`
    : `All ${data.total} steps done`;

  return (
    <section className="practical" aria-label="Practical progress">
      <button
        type="button"
        className="practical-summary"
        aria-expanded={open}
        aria-controls="practical-steps"
        onClick={() => setOpen(!open)}
      >
        <span className="practical-label">Practical</span>
        <span className="practical-count">{summary}</span>
        {current && <span className="practical-now">{current.title}</span>}
        <span className="practical-chevron" aria-hidden="true">▾</span>
      </button>
      {open && (
        <div id="practical-steps" className="practical-body">
          <ol className="practical-steps">
            {data.steps.map((s) => (
              <li key={s.index} className={`practical-step is-${s.status}`} aria-current={s.status === "current" ? "step" : undefined}>
                <span className="practical-mark" aria-hidden="true">
                  {s.status === "completed" ? <CheckIcon size={12} /> : s.index + 1}
                </span>
                <span className="practical-text">
                  <span className="practical-title">{s.title}</span>
                  <span className="practical-state">
                    {s.status === "completed" ? "Done" : s.status === "current" ? "Now" : "Next"}
                  </span>
                  {s.status === "current" && <span className="practical-detail">{s.detail}</span>}
                </span>
              </li>
            ))}
          </ol>
          {current && (
            <div className="practical-actions">
              <button type="button" className="btn btn-primary btn-sm" disabled={disabled || busy} onClick={complete}>
                {busy ? "Saving…" : "I've completed this step"}
              </button>
              <button type="button" className="btn btn-secondary btn-sm" disabled={disabled} onClick={() => onSend(`Explain this step: ${current.title}`)}>
                Explain this step
              </button>
              <button type="button" className="btn btn-secondary btn-sm" disabled={disabled} onClick={() => onSend(`I'm stuck on this step: ${current.title}`)}>
                I&apos;m stuck
              </button>
            </div>
          )}
          {note && (
            <p className="practical-note" role="status">
              {note}
            </p>
          )}
        </div>
      )}
    </section>
  );
}
