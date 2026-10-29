"use client";

import { useState } from "react";
import ReactMarkdown from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import type { UnifiedChatMessage } from "@/lib/api";
import {
  BookIcon,
  CheckIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  LightbulbIcon,
  WarningIcon,
} from "@/components/Icons";

// Spacing and colours for these live in globals.css (.msg-body ...), so they
// follow the theme; only the element mapping is decided here.
const markdownComponents = {
  h1: (props: React.ComponentProps<"h1">) => <h3 {...props} />,
  h2: (props: React.ComponentProps<"h2">) => <h3 {...props} />,
  h3: (props: React.ComponentProps<"h3">) => <h4 {...props} />,
  code: (props: React.ComponentProps<"code">) => <code className="md-code" {...props} />,
  pre: (props: React.ComponentProps<"pre">) => <pre className="md-pre" {...props} />,
  // Wide tables scroll inside the bubble instead of stretching the page.
  table: (props: React.ComponentProps<"table">) => (
    <div className="md-table-wrap">
      <table {...props} />
    </div>
  ),
  img: (props: React.ComponentProps<"img">) => (
    // eslint-disable-next-line @next/next/no-img-element, jsx-a11y/alt-text
    <img {...props} />
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

// Models write formulas as \[ ... \], \( ... \) or a bare "[ \Delta E ... ]"
// (the backslash before the bracket gets lost). Normalise all three to the
// $ / $$ form remark-math understands.
function normalizeMath(text: string): string {
  return text
    .replace(/\\\[([\s\S]+?)\\\]/g, (_m, body: string) => `\n\n$$${body.trim()}$$\n\n`)
    .replace(/\\\(([\s\S]+?)\\\)/g, (_m, body: string) => `$${body.trim()}$`)
    .replace(/\[\s+(\\[A-Za-z][^\]\n]*?)\s+\]/g, (_m, body: string) => `$$${body.trim()}$$`);
}

/** Markdown merges single line breaks into spaces, which runs a multiple-choice
 * question's options together ("a) ... b) ... c) ..."). Keep each option, and the
 * "Reply with" line, on its own line with a markdown hard break. */
function keepOptionLines(content: string): string {
  return content.replace(/\n(?=(?:[a-d]\) |Reply with a, b, c or d))/g, "  \n");
}

function renderFormattedContent(content: string) {
  if (!content) return null;
  // react-markdown does not render raw HTML by default, so model output
  // cannot inject markup.
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm, remarkMath]}
      rehypePlugins={[[rehypeKatex, { throwOnError: false, strict: false }]]}
      components={cleanMarkdownComponents}
    >
      {normalizeMath(keepOptionLines(content))}
    </ReactMarkdown>
  );
}

export function MessageBubble({
  message,
  streaming = false,
  showStepHeader = true,
  onQuickReply,
  triggerText,
}: {
  message: UnifiedChatMessage;
  /** The reply is still arriving (its final, saved text replaces it when done). */
  streaming?: boolean;
  /** Show "Step N of M: <prompt>" as the first paragraph. The caller turns it off
   * when the previous tutor reply was already on the same step. */
  showStepHeader?: boolean;
  /** Send text as though the student typed it -- wired to option buttons,
   * quick-reply chips and quiz answers on a walkthrough turn. Only passed
   * for the most recent message, so old option buttons render inert. */
  onQuickReply?: (text: string) => void;
  /** The student message this reply answers. A chip that would just send
   * the same text again is never shown (the server already filters these;
   * this is the renderer's own guard against a recursive action). */
  triggerText?: string;
}) {

  const isStudent = message.author === "student";
  const meta = message.metadata || {};
  const ui = meta.ui;
  // The concept card is rendered as its own block, so drop its paragraph from
  // the body (the stored message keeps it for transcripts and exports).
  const conceptCard = meta.type === "walkthrough" ? ui?.concept_card : undefined;
  const bodyText = conceptCard
    ? message.content.replace(`**Concept worth knowing: ${conceptCard.name}.** ${conceptCard.text}\n\n`, "")
    : message.content;
  const trigger = (triggerText || "").trim().toLowerCase();
  const chips = Array.from(new Set(ui?.chips || [])).filter(
    (chip) => chip.trim().toLowerCase() !== trigger
  );
  const [copied, setCopied] = useState(false);
  const [showCitations, setShowCitations] = useState(false);

  const handleCopy = () => {
    navigator.clipboard.writeText(message.content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className={`msg-row ${isStudent ? "from-student" : "from-tutor"}`}>
      <div className={`msg-bubble ${isStudent ? "is-student" : "is-tutor"}`}>
        {/* Diagnostic Metadata Badge Card */}
        {meta.type === "diagnostic" && meta.status && (
          <div className={`diag-card is-${meta.status}`}>
            <div className="diag-head">
              <span className={`pill pill-${meta.status}`}>
                {meta.status.charAt(0).toUpperCase() + meta.status.slice(1)} · Tier {meta.tier}
              </span>
              {meta.action && meta.action !== "none" && (
                <span className="muted diag-remedy">Remedy: {meta.action.replace(/_/g, " ")}</span>
              )}
            </div>
            {meta.low_confidence && (
              <p className="muted diag-note">
                <WarningIcon size={12} /> Low-confidence qualitative check — human review requested.
              </p>
            )}
          </div>
        )}

        {/* Walkthrough progress: where you are, with back / next one tap away.
            The buttons send the same words a student would type, so they go
            through the server's deterministic navigation like anything else. */}
        {meta.type === "walkthrough" && ui?.progress && (
          <div className="wt-progress">
            <div className="wt-progress-bar" aria-hidden>
              <div
                className="wt-progress-fill"
                style={{ width: `${Math.min(100, ((ui.progress.index + 1) / Math.max(1, ui.progress.total)) * 100)}%` }}
              />
            </div>
            <span className="wt-progress-label">{ui.progress.label}</span>
            {onQuickReply && ui.kind !== "done" && (
              <span className="wt-nav">
                <button
                  type="button"
                  className="icon-btn wt-nav-btn"
                  aria-label="Previous step"
                  title="Previous step"
                  disabled={ui.progress.index <= 0 && ui.kind !== "assessment"}
                  onClick={() => onQuickReply("Previous step")}
                >
                  <ChevronLeftIcon size={16} />
                </button>
                <button
                  type="button"
                  className="icon-btn wt-nav-btn"
                  aria-label="Next step"
                  title="Next step"
                  onClick={() => onQuickReply("Next step")}
                >
                  <ChevronRightIcon size={16} />
                </button>
              </span>
            )}
          </div>
        )}

        {/* Concept card: inline, shown only when a core concept is raised */}
        {conceptCard && (
          <div role="note" aria-label={`Concept: ${conceptCard.name}`} className="concept-card">
            <div className="concept-card-label">Concept worth knowing</div>
            <strong>{conceptCard.name}.</strong> {conceptCard.text}
          </div>
        )}

        {/* Message Content */}
        {streaming && !message.content && (
          <div className="typing" role="status" aria-label="Tutor is thinking">
            <span /><span /><span />
          </div>
        )}
        <div className="msg-body" aria-busy={streaming || undefined}>
          {renderFormattedContent(
            showStepHeader && meta.type === "socratic" && meta.prompt
              ? `**Step ${meta.current_step !== undefined ? meta.current_step + 1 : 1} of ${meta.total_steps || "?"}:** ${meta.prompt}\n\n${bodyText}`
              : bodyText
          )}
        </div>

        {/* Walkthrough option buttons (MCQ / checkpoint) */}
        {meta.type === "walkthrough" && ui?.options && ui.options.length > 0 && (
          <div role="group" aria-label="Answer options" className="reply-stack">
            {ui.options.map((opt) => (
              <button
                key={opt.key}
                type="button"
                className="btn btn-secondary btn-sm touch-btn opt-btn"
                disabled={!onQuickReply}
                onClick={() => onQuickReply?.(`${opt.key.toUpperCase()}. ${opt.text}`)}
              >
                <strong className="opt-key">{opt.key.toUpperCase()}.</strong> {opt.text}
              </button>
            ))}
          </div>
        )}

        {/* Checkpoint quiz: two questions, each with its own option group */}
        {meta.type === "walkthrough" && ui?.quiz && ui.quiz.length > 0 && (
          <div className="quiz-stack">
            {ui.quiz.map((item) => (
              <div key={item.n} role="group" aria-label={`Question ${item.n}`} className="reply-stack">
                {item.options.map((opt) => (
                  <button
                    key={opt.key}
                    type="button"
                    className="btn btn-secondary btn-sm touch-btn opt-btn"
                    disabled={!onQuickReply}
                    onClick={() => onQuickReply?.(`${item.n}${opt.key}`)}
                  >
                    <strong className="opt-key">{item.n}{opt.key}.</strong> {opt.text}
                  </button>
                ))}
              </div>
            ))}
          </div>
        )}

        {/* Quick-reply chips (Give me a hint, Theory / Study, ...) on any
            reply that carries them: walkthrough, greeting/mode, theory. */}
        {chips.length > 0 && (
          <div className="chip-row">
            {chips.map((chip) => (
              <button
                key={chip}
                type="button"
                className="btn btn-secondary btn-sm touch-btn chip-btn"
                disabled={!onQuickReply}
                onClick={() => onQuickReply?.(chip)}
              >
                {chip}
              </button>
            ))}
          </div>
        )}


        {/* Diagnostic Citation */}
        {meta.type === "diagnostic" && meta.citation && (
          <div className="diag-citation">
            <BookIcon size={13} className="muted" />
            <span><strong>Manual reference:</strong> {meta.citation}</span>
          </div>
        )}

        {meta.general_knowledge && !streaming && (
          <p className="gk-note">
            <LightbulbIcon size={13} /> Includes general chemistry knowledge, not from the lab manual.
          </p>
        )}

        {/* Q&A Citations Accordion */}
        {meta.citations && meta.citations.length > 0 && (
          <div className="msg-sources">
            <button
              type="button"
              className="src-toggle"
              aria-expanded={showCitations}
              onClick={() => setShowCitations(!showCitations)}
            >
              <span className="src-chevron" aria-hidden="true">▶</span>
              {showCitations ? "Hide sources" : `View ${meta.citations.length} source${meta.citations.length === 1 ? "" : "s"}`}
            </button>
            {showCitations && (
              <div className="src-list">
                {meta.citations.map((c, i) => (
                  <div key={i} className="src-card">
                    <div className="src-card-head">
                      <span>Page {c.page}</span>
                      <span className="pill src-tier">
                        {c.tier === "A" ? "Manual" : c.tier === "B" ? "Course material" : c.tier === "C" ? "Background" : c.tier}
                      </span>
                    </div>
                    <p className="src-text">
                      "{c.text}"
                    </p>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Footer controls */}
        {!isStudent && !streaming && (
          <div className="msg-actions">
            <button
              type="button"
              onClick={handleCopy}
              className="msg-action"
              aria-label={copied ? "Copied to clipboard" : "Copy reply"}
            >
              {copied ? (
                <span className="copied">
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
