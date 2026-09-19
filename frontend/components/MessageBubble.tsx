"use client";

import { useState } from "react";
import type { UnifiedChatMessage } from "@/lib/api";
import { BookIcon, CheckIcon, WarningIcon } from "@/components/Icons";

function renderFormattedContent(content: string) {
  if (!content) return null;
  const lines = content.split("\n");
  return lines.map((line, lineIdx) => {
    const isBullet = /^\s*[-*•]\s+(.*)/.exec(line);
    const isNumbered = /^\s*(\d+)\.\s+(.*)/.exec(line);

    const parseInline = (text: string) => {
      const parts: (string | React.ReactNode)[] = [];
      const regex = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*]+\*)/g;
      let lastIndex = 0;
      let match;
      let key = 0;
      while ((match = regex.exec(text)) !== null) {
        if (match.index > lastIndex) {
          parts.push(text.substring(lastIndex, match.index));
        }
        const m = match[0];
        if (m.startsWith("**") && m.endsWith("**")) {
          parts.push(<strong key={key++}>{m.slice(2, -2)}</strong>);
        } else if (m.startsWith("`") && m.endsWith("`")) {
          parts.push(
            <code
              key={key++}
              style={{
                backgroundColor: "rgba(128, 128, 128, 0.15)",
                padding: "2px 5px",
                borderRadius: "4px",
                fontFamily: "monospace",
                fontSize: "0.9em",
              }}
            >
              {m.slice(1, -1)}
            </code>
          );
        } else if (m.startsWith("*") && m.endsWith("*")) {
          parts.push(<em key={key++}>{m.slice(1, -1)}</em>);
        }
        lastIndex = regex.lastIndex;
      }
      if (lastIndex < text.length) {
        parts.push(text.substring(lastIndex));
      }
      return parts.length > 0 ? parts : text;
    };

    if (isBullet) {
      return (
        <div key={lineIdx} style={{ display: "flex", gap: "8px", marginLeft: "6px", margin: "3px 0" }}>
          <span style={{ color: "var(--accent)" }}>•</span>
          <div>{parseInline(isBullet[1])}</div>
        </div>
      );
    }
    if (isNumbered) {
      return (
        <div key={lineIdx} style={{ display: "flex", gap: "8px", marginLeft: "6px", margin: "3px 0" }}>
          <span style={{ fontWeight: 600, color: "var(--accent)" }}>{isNumbered[1]}.</span>
          <div>{parseInline(isNumbered[2])}</div>
        </div>
      );
    }
    return (
      <div key={lineIdx} style={{ minHeight: line.trim() ? "auto" : "0.5em" }}>
        {parseInline(line)}
      </div>
    );
  });
}

export function MessageBubble({ message }: { message: UnifiedChatMessage }) {

  const isStudent = message.author === "student";
  const meta = message.metadata || {};
  const [copied, setCopied] = useState(false);
  const [showCitations, setShowCitations] = useState(false);

  const handleCopy = () => {
    navigator.clipboard.writeText(message.content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: isStudent ? "flex-end" : "flex-start",
        margin: "8px 0",
      }}
    >
      <div
        style={{
          maxWidth: "85%",
          padding: "12px 16px",
          borderRadius: "12px",
          borderTopRightRadius: isStudent ? "2px" : "12px",
          borderTopLeftRadius: isStudent ? "12px" : "2px",
          backgroundColor: isStudent ? "var(--accent-weak)" : "var(--surface)",
          border: isStudent ? "1px solid var(--accent-border)" : "1px solid var(--border)",
          color: "var(--text)",
          boxShadow: "0 1px 2px rgba(0,0,0,0.03)",
        }}
      >
        {/* Diagnostic Metadata Badge Card */}
        {meta.type === "diagnostic" && meta.status && (
          <div
            style={{
              padding: "8px 12px",
              marginBottom: "10px",
              borderRadius: "8px",
              fontSize: "0.85rem",
              backgroundColor:
                meta.status === "pass"
                  ? "var(--success-weak)"
                  : meta.status === "fail"
                  ? "var(--danger-weak)"
                  : meta.status === "escalated"
                  ? "var(--purple-weak)"
                  : "var(--warn-weak)",
              border: `1px solid ${
                meta.status === "pass"
                  ? "var(--success)"
                  : meta.status === "fail"
                  ? "var(--danger)"
                  : meta.status === "escalated"
                  ? "var(--purple)"
                  : "var(--warn)"
              }`,
            }}
          >
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "4px" }}>
              <span className={`pill pill-${meta.status}`}>
                {meta.status.toUpperCase()} (Tier {meta.tier})
              </span>
              {meta.action && meta.action !== "none" && (
                <span className="muted" style={{ fontSize: "0.75rem", textTransform: "capitalize" }}>
                  Remedy: {meta.action.replace(/_/g, " ")}
                </span>
              )}
            </div>
            {meta.low_confidence && (
              <p className="muted" style={{ fontSize: "0.75rem", margin: "2px 0 0", display: "flex", alignItems: "center", gap: "4px" }}>
                <WarningIcon size={12} /> Low-confidence qualitative check — human review requested.
              </p>
            )}
          </div>
        )}

        {/* Socratic Step Metadata Card */}
        {meta.type === "socratic" && meta.prompt && (
          <div
            style={{
              padding: "8px 12px",
              marginBottom: "10px",
              borderRadius: "8px",
              fontSize: "0.85rem",
              backgroundColor: "var(--accent-weak)",
              border: "1px solid var(--accent-border)",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "4px" }}>
              <span className="pill pill-pass">
                Step {meta.current_step !== undefined ? meta.current_step + 1 : 1} of {meta.total_steps || "?"}
              </span>
              {meta.complete && (
                <span className="pill pill-pass">All steps complete</span>
              )}
            </div>
            <p style={{ margin: "4px 0 0", fontSize: "0.85rem", fontWeight: 500 }}>
              {meta.prompt}
            </p>
          </div>
        )}

        {/* Message Content */}
        <div style={{ wordBreak: "break-word", lineHeight: 1.55 }}>
          {renderFormattedContent(message.content)}
        </div>


        {/* Diagnostic Citation */}
        {meta.type === "diagnostic" && meta.citation && (
          <div style={{ marginTop: "8px", fontSize: "0.8rem", color: "var(--muted)", display: "flex", alignItems: "flex-start", gap: "6px" }}>
            <BookIcon size={13} className="muted" />
            <span><strong>Manual reference:</strong> {meta.citation}</span>
          </div>
        )}

        {/* Q&A Citations Accordion */}
        {meta.citations && meta.citations.length > 0 && (
          <div style={{ marginTop: "10px", paddingTop: "8px", borderTop: "1px solid var(--border)" }}>
            <button
              onClick={() => setShowCitations(!showCitations)}
              style={{
                background: "none",
                border: "none",
                color: "var(--accent)",
                cursor: "pointer",
                padding: 0,
                fontSize: "0.8rem",
                fontWeight: 500,
                display: "flex",
                alignItems: "center",
                gap: "4px",
              }}
            >
              {showCitations ? "▼ Hide course manual citations" : `▶ View ${meta.citations.length} manual citation(s)`}
            </button>
            {showCitations && (
              <div style={{ marginTop: "6px", display: "flex", flexDirection: "column", gap: "6px" }}>
                {meta.citations.map((c, i) => (
                  <div
                    key={i}
                    style={{
                      fontSize: "0.775rem",
                      padding: "6px 8px",
                      borderRadius: "6px",
                      backgroundColor: "var(--surface)",
                      border: "1px solid var(--border)",
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", fontWeight: 600, color: "var(--text)", marginBottom: "2px" }}>
                      <span>Page {c.page}</span>
                      <span className="pill" style={{ fontSize: "0.7rem" }}>{c.tier}</span>
                    </div>
                    <p style={{ margin: 0, color: "var(--muted)", fontStyle: "italic" }}>
                      "{c.text}"
                    </p>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Footer controls */}
        {!isStudent && (
          <div style={{ marginTop: "6px", display: "flex", justifyContent: "flex-end" }}>
            <button
              onClick={handleCopy}
              className="btn btn-sm btn-secondary"
              style={{ padding: "2px 6px", fontSize: "0.7rem" }}
            >
              {copied ? (
                <span style={{ display: "flex", alignItems: "center", gap: "4px" }}>
                  <CheckIcon size={12} /> Copied
                </span>
              ) : (
                "Copy"
              )}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
