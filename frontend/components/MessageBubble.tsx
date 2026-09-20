"use client";

import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { UnifiedChatMessage } from "@/lib/api";
import { BookIcon, CheckIcon, WarningIcon } from "@/components/Icons";

const markdownComponents = {
  p: (props: React.ComponentProps<"p">) => <p style={{ margin: "0 0 0.75em" }} {...props} />,
  ul: (props: React.ComponentProps<"ul">) => <ul style={{ margin: "0 0 0.75em", paddingLeft: "1.3em" }} {...props} />,
  ol: (props: React.ComponentProps<"ol">) => <ol style={{ margin: "0 0 0.75em", paddingLeft: "1.5em" }} {...props} />,
  li: (props: React.ComponentProps<"li">) => <li style={{ margin: "3px 0" }} {...props} />,
  h1: (props: React.ComponentProps<"h1">) => <h3 style={{ margin: "0.9em 0 0.4em", fontSize: "1.05rem" }} {...props} />,
  h2: (props: React.ComponentProps<"h2">) => <h3 style={{ margin: "0.9em 0 0.4em", fontSize: "1.05rem" }} {...props} />,
  h3: (props: React.ComponentProps<"h3">) => <h4 style={{ margin: "0.8em 0 0.3em", fontSize: "0.98rem" }} {...props} />,
  code: (props: React.ComponentProps<"code">) => (
    <code
      style={{
        backgroundColor: "rgba(128, 128, 128, 0.15)",
        padding: "2px 5px",
        borderRadius: "4px",
        fontFamily: "monospace",
        fontSize: "0.9em",
      }}
      {...props}
    />
  ),
  pre: (props: React.ComponentProps<"pre">) => (
    <pre style={{ margin: "0 0 0.75em", overflowX: "auto", padding: "8px 10px", borderRadius: "6px", backgroundColor: "rgba(128, 128, 128, 0.15)" }} {...props} />
  ),
  a: (props: React.ComponentProps<"a">) => <a target="_blank" rel="noopener noreferrer" {...props} />,
};

// react-markdown passes its parser `node` to every custom component; spreading
// it onto a DOM element renders a bogus `node="[object Object]"` attribute.
const cleanMarkdownComponents = Object.fromEntries(
  Object.entries(markdownComponents).map(([tag, Component]) => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const Clean = ({ node: _node, ...rest }: any) => <Component {...rest} />;
    return [tag, Clean];
  }),
);

function renderFormattedContent(content: string) {
  if (!content) return null;
  // react-markdown does not render raw HTML by default, so model output
  // cannot inject markup.
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={cleanMarkdownComponents}>
      {content}
    </ReactMarkdown>
  );
}

export function MessageBubble({
  message,
  showStepHeader = true,
  onQuickReply,
}: {
  message: UnifiedChatMessage;
  /** Show "Step N of M: <prompt>" as the first paragraph. The caller turns it off
   * when the previous tutor reply was already on the same step. */
  showStepHeader?: boolean;
  /** Send text as though the student typed it -- wired to option buttons,
   * quick-reply chips and quiz answers on a walkthrough turn. Only passed
   * for the most recent message, so old option buttons render inert. */
  onQuickReply?: (text: string) => void;
}) {

  const isStudent = message.author === "student";
  const meta = message.metadata || {};
  const ui = meta.ui;
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

        {/* Walkthrough progress rail */}
        {meta.type === "walkthrough" && ui?.progress && (
          <div
            style={{
              display: "flex", alignItems: "center", gap: "8px", marginBottom: "8px",
              fontSize: "0.75rem", color: "var(--muted)",
            }}
          >
            <div
              aria-hidden
              style={{
                flex: 1, height: "4px", borderRadius: "2px", background: "var(--border)", position: "relative", overflow: "hidden",
              }}
            >
              <div
                style={{
                  position: "absolute", inset: 0, width: `${Math.min(100, (ui.progress.index / Math.max(1, ui.progress.total)) * 100)}%`,
                  background: "var(--accent)", borderRadius: "2px",
                }}
              />
            </div>
            <span>{ui.progress.label}</span>
          </div>
        )}

        {/* Message Content */}
        <div style={{ wordBreak: "break-word", lineHeight: 1.55 }}>
          {renderFormattedContent(
            showStepHeader && meta.type === "socratic" && meta.prompt
              ? `**Step ${meta.current_step !== undefined ? meta.current_step + 1 : 1} of ${meta.total_steps || "?"}:** ${meta.prompt}\n\n${message.content}`
              : message.content
          )}
        </div>

        {/* Walkthrough option buttons (MCQ / checkpoint) */}
        {meta.type === "walkthrough" && ui?.options && ui.options.length > 0 && (
          <div role="group" aria-label="Answer options" style={{ display: "flex", flexDirection: "column", gap: "6px", marginTop: "10px" }}>
            {ui.options.map((opt) => (
              <button
                key={opt.key}
                type="button"
                className="btn btn-secondary btn-sm"
                disabled={!onQuickReply}
                onClick={() => onQuickReply?.(`${opt.key.toUpperCase()}. ${opt.text}`)}
                style={{ textAlign: "left", justifyContent: "flex-start", whiteSpace: "normal" }}
              >
                <strong style={{ marginRight: "6px" }}>{opt.key.toUpperCase()}.</strong> {opt.text}
              </button>
            ))}
          </div>
        )}

        {/* Checkpoint quiz: two questions, each with its own option group */}
        {meta.type === "walkthrough" && ui?.quiz && ui.quiz.length > 0 && (
          <div style={{ display: "flex", flexDirection: "column", gap: "10px", marginTop: "10px" }}>
            {ui.quiz.map((item) => (
              <div key={item.n} role="group" aria-label={`Question ${item.n}`} style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                {item.options.map((opt) => (
                  <button
                    key={opt.key}
                    type="button"
                    className="btn btn-secondary btn-sm"
                    disabled={!onQuickReply}
                    onClick={() => onQuickReply?.(`${item.n}${opt.key}`)}
                    style={{ textAlign: "left", justifyContent: "flex-start", whiteSpace: "normal" }}
                  >
                    <strong style={{ marginRight: "6px" }}>{item.n}{opt.key}.</strong> {opt.text}
                  </button>
                ))}
              </div>
            ))}
          </div>
        )}

        {/* Quick-reply chips (Give me a hint, Why do this step?, ...) */}
        {meta.type === "walkthrough" && ui?.chips && ui.chips.length > 0 && (
          <div style={{ display: "flex", flexWrap: "wrap", gap: "6px", marginTop: "10px" }}>
            {ui.chips.map((chip) => (
              <button
                key={chip}
                type="button"
                className="btn btn-secondary btn-sm"
                disabled={!onQuickReply}
                onClick={() => onQuickReply?.(chip)}
                style={{ borderRadius: "999px", fontSize: "0.75rem", padding: "4px 12px" }}
              >
                {chip}
              </button>
            ))}
          </div>
        )}


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
              {showCitations ? "▼ Hide sources" : `▶ View ${meta.citations.length} source${meta.citations.length === 1 ? "" : "s"}`}
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
                      <span className="pill" style={{ fontSize: "0.7rem" }}>
                        {c.tier === "A" ? "Manual" : c.tier === "B" ? "Course material" : c.tier === "C" ? "Background" : c.tier}
                      </span>
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
