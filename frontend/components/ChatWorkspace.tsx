"use client";

import { useEffect, useRef, useState } from "react";
import {
  api,
  ApiError,
  newIdempotencyKey,
  type ActiveSessionInfo,
  type ChatThread,
  type Classroom,
  type Experiment,
  type Me,
  type UnifiedChatMessage,
} from "@/lib/api";
import { MessageBubble } from "./MessageBubble";
import { FacultyModal } from "./FacultyModal";
import { AdminModal } from "./AdminModal";
import {
  BoltIcon,
  ChatIcon,
  CloseIcon,
  EditIcon,
  GraduationCapIcon,
  LightbulbIcon,
  TrashIcon,
} from "./Icons";

const STORAGE_KEY_CLASSROOM = "labtutor:active-classroom-id";
const STORAGE_KEY_EXP = "labtutor:active-experiment-id";

export function ChatWorkspace({ me }: { me: Me }) {
  // State
  const [classrooms, setClassrooms] = useState<Classroom[]>([]);
  const [activeClassroom, setActiveClassroom] = useState<Classroom | null>(null);
  const [experiments, setExperiments] = useState<Experiment[]>([]);
  const [selectedExpId, setSelectedExpId] = useState<string>("exp01");
  const [sessionInfo, setSessionInfo] = useState<ActiveSessionInfo>({ active: false });

  const [threads, setThreads] = useState<ChatThread[]>([]);
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null);
  const [messages, setMessages] = useState<UnifiedChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [loadingMessages, setLoadingMessages] = useState(false);

  const [error, setError] = useState("");
  const [showJoinModal, setShowJoinModal] = useState(false);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [showFacultyModal, setShowFacultyModal] = useState(false);
  const [showAdminModal, setShowAdminModal] = useState(false);

  const [joinCode, setJoinCode] = useState("");
  const [newClassroomName, setNewClassroomName] = useState("");
  const [renameThreadId, setRenameThreadId] = useState<string | null>(null);
  const [renameTitle, setRenameTitle] = useState("");

  const scrollRef = useRef<HTMLDivElement>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);

  // On narrow screens the sidebar is a drawer; close it once the student
  // has picked a chat or classroom so they land on the conversation.
  useEffect(() => {
    setSidebarOpen(false);
  }, [activeThreadId, activeClassroom]);

  // Auto-scroll to bottom of messages
  useEffect(() => {
    scrollRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, sending]);

  // Load classrooms on mount
  const loadClassrooms = async () => {
    setError("");
    try {
      let list: Classroom[] = [];
      if (me.role === "admin") {
        const res = await api.get<{ classrooms: Classroom[] }>("/api/classrooms");
        list = res.classrooms;
      } else if (me.role === "faculty") {
        const res = await api.get<{ classrooms: Classroom[] }>("/api/classrooms/mine");
        list = res.classrooms;
      } else {
        const res = await api.get<{ classrooms: Classroom[] }>("/api/classrooms/enrolled");
        list = res.classrooms;
      }
      setClassrooms(list);

      if (list.length > 0) {
        let savedId: string | null = null;
        try {
          savedId = localStorage.getItem(STORAGE_KEY_CLASSROOM);
        } catch {}
        const match = list.find((c) => c.id === savedId);
        setActiveClassroom(match || list[0]);
      } else {
        setActiveClassroom(null);
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  };

  // Load experiments list
  const loadExperiments = async () => {
    try {
      const res = await api.get<{ experiments: Experiment[] }>("/api/classrooms/experiments");
      setExperiments(res.experiments);
    } catch (e) {
      console.error("Failed to load experiments", e);
    }
  };

  useEffect(() => {
    loadClassrooms();
    loadExperiments();
  }, [me]);

  // Save active classroom to local storage
  useEffect(() => {
    if (activeClassroom) {
      try {
        localStorage.setItem(STORAGE_KEY_CLASSROOM, activeClassroom.id);
      } catch {}
      checkSessionStatus(activeClassroom.id);
    }
  }, [activeClassroom]);

  // Check active session for current classroom
  const checkSessionStatus = async (classroomId: string) => {
    try {
      const info = await api.get<ActiveSessionInfo>(`/api/classrooms/${classroomId}/active-session`);
      setSessionInfo(info);
      if (info.active && info.experiment_id) {
        setSelectedExpId(info.experiment_id);
      }
    } catch (e) {
      setSessionInfo({ active: false });
    }
  };

  // Load threads when classroom or experiment changes
  const loadThreads = async () => {
    if (!activeClassroom || !selectedExpId) return;
    try {
      const res = await api.get<{ threads: ChatThread[] }>(
        `/api/chat/threads?classroom_id=${activeClassroom.id}&experiment_id=${selectedExpId}`
      );
      setThreads(res.threads);
      if (res.threads.length > 0) {
        setActiveThreadId(res.threads[0].id);
      } else {
        setActiveThreadId(null);
        setMessages([]);
      }
    } catch (e) {
      console.error("Failed to load chat threads", e);
    }
  };

  useEffect(() => {
    loadThreads();
  }, [activeClassroom, selectedExpId]);

  // Load messages for active thread
  const loadMessages = async (threadId: string) => {
    setLoadingMessages(true);
    try {
      const res = await api.get<{ messages: UnifiedChatMessage[] }>(
        `/api/chat/threads/${threadId}/messages`
      );
      setMessages(res.messages);
    } catch (e) {
      console.error("Failed to load messages", e);
    } finally {
      setLoadingMessages(false);
    }
  };

  useEffect(() => {
    if (activeThreadId) {
      loadMessages(activeThreadId);
    } else {
      setMessages([]);
    }
  }, [activeThreadId]);

  // Join Classroom handler
  const handleJoinClassroom = async () => {
    if (!joinCode.trim()) return;
    setError("");
    try {
      const joined = await api.post<Classroom>("/api/classrooms/join", {
        join_code: joinCode.trim(),
        idempotency_key: newIdempotencyKey(),
      });
      setShowJoinModal(false);
      setJoinCode("");
      await loadClassrooms();
      setActiveClassroom(joined);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  };

  // Create Classroom handler
  const handleCreateClassroom = async () => {
    if (!newClassroomName.trim()) return;
    setError("");
    try {
      const created = await api.post<Classroom>("/api/classrooms", {
        name: newClassroomName.trim(),
        idempotency_key: newIdempotencyKey(),
      });
      setShowCreateModal(false);
      setNewClassroomName("");
      await loadClassrooms();
      setActiveClassroom(created);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  };

  // Create New Chat Thread
  const handleNewChat = async () => {
    if (!activeClassroom || !selectedExpId) return;
    try {
      const fresh = await api.post<ChatThread>("/api/chat/threads", {
        classroom_id: activeClassroom.id,
        experiment_id: selectedExpId,
        title: "New chat",
      });
      setThreads((prev) => [fresh, ...prev]);
      setActiveThreadId(fresh.id);
      setMessages([]);
      setInput("");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  };

  // Rename Thread
  const handleRenameThread = async () => {
    if (!renameThreadId || !renameTitle.trim()) return;
    try {
      const res = await api.patch<{ title: string }>(`/api/chat/threads/${renameThreadId}`, {
        title: renameTitle.trim(),
      });
      setThreads((prev) =>
        prev.map((t) => (t.id === renameThreadId ? { ...t, title: res.title } : t))
      );
      setRenameThreadId(null);
      setRenameTitle("");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  };

  // Delete Thread
  const handleDeleteThread = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await api.del(`/api/chat/threads/${id}`);
      setThreads((prev) => prev.filter((t) => t.id !== id));
      if (activeThreadId === id) {
        const remaining = threads.filter((t) => t.id !== id);
        setActiveThreadId(remaining.length > 0 ? remaining[0].id : null);
      }
    } catch (err) {
      console.error("Failed to delete thread", err);
    }
  };

  // Send Message handler
  const handleSend = async () => {
    const text = input.trim();
    if (!text || !activeClassroom || sending) return;

    setError("");
    setSending(true);
    setInput("");

    // Optimistic user message
    const tempUserMsg: UnifiedChatMessage = {
      id: `temp-${Date.now()}`,
      author: "student",
      content: text,
      kind: "qa",
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, tempUserMsg]);

    try {
      const res = await api.post<{
        thread_id: string;
        thread_title: string;
        message: UnifiedChatMessage;
      }>("/api/chat/messages", {
        classroom_id: activeClassroom.id,
        experiment_id: selectedExpId,
        message: text,
        thread_id: activeThreadId,
      });

      if (!activeThreadId || activeThreadId !== res.thread_id) {
        // Switching onto a (possibly just-created) thread also fires the
        // activeThreadId effect below, which calls loadMessages() and
        // replaces `messages` wholesale from the server. Appending here
        // too raced with that fetch -- whichever resolved second won,
        // and when loadMessages won first, this append landed on top of
        // the already-loaded pair, rendering the question+reply twice.
        // The thread-switch effect is the sole source of truth for
        // `messages` in this branch; only the "still on the same
        // thread" branch below needs to append locally.
        setActiveThreadId(res.thread_id);
        await loadThreads();
      } else {
        setThreads((prev) =>
          prev.map((t) => (t.id === res.thread_id ? { ...t, title: res.thread_title } : t))
        );
        // Give the settled student message a permanent id: a `temp-` id
        // would be swept away by the next send's cleanup, making every
        // earlier prompt vanish from the thread.
        const settledUserMsg = { ...tempUserMsg, id: `local-${res.message.id}` };
        setMessages((prev) => [
          ...prev.filter((m) => m.id !== tempUserMsg.id),
          settledUserMsg,
          res.message,
        ]);
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
      setMessages((prev) => prev.filter((m) => m.id !== tempUserMsg.id));
      setInput(text);
    } finally {
      setSending(false);
    }
  };

  const isCoFaculty = activeClassroom?.co_faculty || me.role === "faculty" || me.role === "admin";
  const selectedExp = experiments.find((e) => e.id === selectedExpId);
  // Faculty/admin test traffic is intentionally allowed without a live
  // session (backend/api/chat_routes.py resolves it as actor_type
  // FACULTY_TEST/ADMIN_TEST, not tied to a class session) -- only
  // students are blocked here.
  const chatBlockedForStudent = me.role === "student" && !sessionInfo.active;

  return (
    <div className="app-root">
      <div
        className={`app-backdrop ${sidebarOpen ? "open" : ""}`}
        onClick={() => setSidebarOpen(false)}
        aria-hidden="true"
      />
      {/* --- Sidebar --- */}
      <aside className={`app-sidebar ${sidebarOpen ? "open" : ""}`}>
        {/* User Header */}
        <div style={{ padding: "16px", borderBottom: "1px solid var(--sidebar-border)" }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <strong style={{ fontSize: "1rem" }}>LabTutor</strong>
            <span
              className={`pill ${
                me.role === "admin" ? "pill-escalated" : me.role === "faculty" ? "pill-pass" : "pill-p1"
              }`}
            >
              {me.role.toUpperCase()}
            </span>
          </div>
          <div style={{ fontSize: "0.8rem", color: "var(--sidebar-muted)", marginTop: "4px" }}>
            {me.name || me.email}
          </div>
        </div>

        {/* Classroom Selector */}
        <div style={{ padding: "12px 16px", borderBottom: "1px solid var(--sidebar-border)" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "6px" }}>
            <span style={{ fontSize: "0.75rem", color: "var(--sidebar-muted)", fontWeight: 600 }}>CLASSROOM</span>
            <button
              onClick={() => setShowJoinModal(true)}
              style={{ background: "none", border: "none", color: "var(--accent)", cursor: "pointer", fontSize: "0.75rem" }}
            >
              + Join Code
            </button>
          </div>
          {classrooms.length > 0 ? (
            <select
              value={activeClassroom?.id || ""}
              onChange={(e) => {
                const c = classrooms.find((x) => x.id === e.target.value);
                if (c) setActiveClassroom(c);
                setError("");
              }}
              style={{
                backgroundColor: "var(--sidebar-surface)",
                borderColor: "var(--sidebar-border)",
                color: "var(--sidebar-text)",
                fontSize: "0.85rem",
              }}
            >
              {classrooms.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name} {c.co_faculty ? "(Co-Faculty)" : ""}
                </option>
              ))}
            </select>
          ) : (
            <p style={{ fontSize: "0.8rem", color: "var(--sidebar-muted)", margin: 0 }}>
              Not in any classroom yet.
            </p>
          )}

          {(me.role === "faculty" || me.role === "admin") && (
            <button
              className="btn btn-sm btn-secondary"
              style={{ width: "100%", marginTop: "8px", fontSize: "0.775rem" }}
              onClick={() => setShowCreateModal(true)}
            >
              + Create Classroom Section
            </button>
          )}
        </div>

        {/* Experiment Selector */}
        <div style={{ padding: "12px 16px", borderBottom: "1px solid var(--sidebar-border)" }}>
          <span style={{ display: "block", fontSize: "0.75rem", color: "var(--sidebar-muted)", fontWeight: 600, marginBottom: "6px" }}>
            IACHY102 EXPERIMENT
          </span>
          {me.role === "student" ? (
            sessionInfo.active && sessionInfo.experiment_id ? (
              <div
                style={{
                  padding: "8px 10px",
                  borderRadius: "6px",
                  background: "var(--sidebar-surface)",
                  border: "1px solid var(--sidebar-border)",
                  color: "var(--sidebar-text)",
                  fontSize: "0.85rem",
                }}
              >
                {sessionInfo.experiment_id.toUpperCase()}:{" "}
                {experiments.find((e) => e.id === sessionInfo.experiment_id)?.title || "Experiment"}
              </div>
            ) : (
              <div
                style={{
                  padding: "8px 10px",
                  borderRadius: "6px",
                  background: "var(--sidebar-surface)",
                  border: "1px solid var(--sidebar-border)",
                  color: "var(--sidebar-muted)",
                  fontSize: "0.8rem",
                }}
              >
                No active session. Ask your instructor to start one.
              </div>
            )
          ) : (
            <select
              value={selectedExpId}
              onChange={(e) => {
                setSelectedExpId(e.target.value);
                setError("");
              }}
              style={{
                backgroundColor: "var(--sidebar-surface)",
                borderColor: "var(--sidebar-border)",
                color: "var(--sidebar-text)",
                fontSize: "0.85rem",
              }}
            >
              {[...experiments].sort((a, b) => a.id.localeCompare(b.id)).map((exp) => (
                <option key={exp.id} value={exp.id}>
                  {exp.id.toUpperCase()}: {exp.title}
                </option>
              ))}
            </select>
          )}
        </div>

        {/* Chat Threads Header & New Chat */}
        <div style={{ padding: "12px 16px 6px", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span style={{ fontSize: "0.75rem", color: "var(--sidebar-muted)", fontWeight: 600 }}>CHAT THREADS</span>
          <button
            onClick={handleNewChat}
            disabled={!activeClassroom}
            className="btn btn-sm btn-primary"
            style={{ padding: "2px 8px", fontSize: "0.75rem" }}
          >
            + New Chat
          </button>
        </div>

        {/* Chat Threads List */}
        <div style={{ flex: 1, overflowY: "auto", padding: "0 8px 12px" }}>
          {threads.length === 0 ? (
            <p style={{ fontSize: "0.8rem", color: "var(--sidebar-muted)", padding: "12px", textAlign: "center" }}>
              No chats for this experiment yet. Click "+ New Chat" to start.
            </p>
          ) : (
            threads.map((t) => {
              const isActive = t.id === activeThreadId;
              return (
                <div
                  key={t.id}
                  onClick={() => setActiveThreadId(t.id)}
                  style={{
                    padding: "8px 10px",
                    borderRadius: "6px",
                    marginBottom: "4px",
                    cursor: "pointer",
                    backgroundColor: isActive ? "var(--sidebar-surface)" : "transparent",
                    color: isActive ? "#ffffff" : "var(--sidebar-muted)",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    fontSize: "0.85rem",
                  }}
                >
                  <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1, display: "flex", alignItems: "center", gap: "6px" }}>
                    <ChatIcon size={14} /> {t.title}
                  </span>
                  <div style={{ display: "flex", gap: "6px" }}>
                    <button
                      aria-label="Rename chat"
                      onClick={(e) => {
                        e.stopPropagation();
                        setRenameThreadId(t.id);
                        setRenameTitle(t.title);
                      }}
                      style={{ background: "none", border: "none", color: "var(--sidebar-muted)", cursor: "pointer", padding: 0, display: "flex" }}
                    >
                      <EditIcon size={13} />
                    </button>
                    <button
                      aria-label="Delete chat"
                      onClick={(e) => handleDeleteThread(t.id, e)}
                      style={{ background: "none", border: "none", color: "var(--sidebar-muted)", cursor: "pointer", padding: 0, display: "flex" }}
                    >
                      <TrashIcon size={13} />
                    </button>
                  </div>
                </div>
              );
            })
          )}
        </div>

        {/* Footer Admin/Faculty Buttons */}
        <div style={{ padding: "12px", borderTop: "1px solid var(--sidebar-border)", display: "flex", flexDirection: "column", gap: "6px" }}>
          {isCoFaculty && activeClassroom && (
            <button
              className="btn btn-secondary btn-sm"
              onClick={() => setShowFacultyModal(true)}
              style={{ width: "100%", display: "flex", alignItems: "center", justifyContent: "center", gap: "6px" }}
            >
              <GraduationCapIcon size={14} /> Classroom Management
            </button>
          )}
          {(me.role === "faculty" || me.role === "admin" || isCoFaculty) && (
            <>
              <a
                className="btn btn-secondary btn-sm"
                href={`/faculty/activity${activeClassroom ? `?classroom=${activeClassroom.id}` : ""}`}
                style={{ width: "100%" }}
              >
                Activity &amp; Data
              </a>
              <a
                className="btn btn-secondary btn-sm"
                href={`/faculty/marks${activeClassroom ? `?classroom=${activeClassroom.id}` : ""}`}
                style={{ width: "100%" }}
              >
                Pre/Post Marks
              </a>
            </>
          )}
          {me.role === "admin" && (
            <button
              className="btn btn-secondary btn-sm"
              onClick={() => setShowAdminModal(true)}
              style={{ width: "100%", display: "flex", alignItems: "center", justifyContent: "center", gap: "6px" }}
            >
              <BoltIcon size={14} /> Platform Admin
            </button>
          )}
          <button
            onClick={async () => {
              try {
                await api.post("/api/auth/logout");
              } finally {
                window.location.href = "/";
              }
            }}
            style={{ fontSize: "0.775rem", color: "var(--sidebar-muted)", textAlign: "center", background: "none", border: "none", padding: 0, marginTop: "4px", cursor: "pointer" }}
          >
            Sign out
          </button>
        </div>
      </aside>

      {/* --- Main Chat Surface --- */}
      <main className="app-main">
        {/* Top Header */}
        <header className="bar">
          <button
            className="btn btn-secondary btn-sm menu-btn"
            aria-label="Open menu"
            onClick={() => setSidebarOpen(true)}
          >
            ☰
          </button>
          <div style={{ minWidth: 0, flex: 1 }}>
            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <h1 style={{ fontSize: "1.1rem", margin: 0 }}>
                {selectedExpId.toUpperCase()}: {selectedExp?.title || "Experiment"}
              </h1>
              {selectedExp && (
                <span className={`pill pill-${selectedExp.priority.toLowerCase().replace("+", "plus")}`}>
                  {selectedExp.priority}
                </span>
              )}
            </div>
            <p className="muted" style={{ margin: "2px 0 0", fontSize: "0.8rem" }}>
              Classroom: <strong>{activeClassroom?.name || "None selected"}</strong>
            </p>
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
            {/* Session Indicator */}
            {sessionInfo.active ? (
              <span className="pill pill-pass">● Session Active</span>
            ) : (
              <span className="pill pill-p1">○ No Session Active</span>
            )}

            {isCoFaculty && activeClassroom && (
              <button className="btn btn-sm btn-secondary" onClick={() => setShowFacultyModal(true)}>
                Faculty Tools
              </button>
            )}
          </div>
        </header>

        {/* Error Banner */}
        {error && (
          <div className="error" style={{ margin: "12px 20px 0" }}>
            {error}
          </div>
        )}

        {/* Messages Container */}
        <div style={{ flex: 1, overflowY: "auto", padding: "20px", display: "flex", flexDirection: "column" }}>
          {!activeClassroom ? (
            <div className="card" style={{ maxWidth: "540px", margin: "40px auto", textAlign: "center" }}>
              <h2>Welcome to LabTutor</h2>
              <p className="muted">You are not in a classroom section yet.</p>
              <button className="btn btn-primary" onClick={() => setShowJoinModal(true)}>
                Enter Join Code
              </button>
            </div>
          ) : messages.length === 0 ? (
            <div className="card" style={{ maxWidth: "620px", margin: "40px auto", textAlign: "center" }}>
              <h2 style={{ marginTop: 0 }}>Grounded AI Chemistry Lab Assistant</h2>
              <p className="muted">
                Ask questions about <strong>{selectedExp?.title}</strong>, work through procedure and theory, get Socratic hints, or paste your numerical data to run a diagnostic check.
              </p>
              <p className="muted" style={{ fontSize: "0.8rem", marginTop: "12px", display: "flex", alignItems: "center", gap: "6px" }}>
                <LightbulbIcon size={14} /> <em>Example prompts to try:</em>
              </p>
              <div style={{ display: "flex", flexDirection: "column", gap: "6px", marginTop: "10px" }}>
                <button
                  className="btn btn-secondary btn-sm"
                  onClick={() => setInput("What is the principle and formula for this experiment?")}
                >
                  "What is the principle and formula for this experiment?"
                </button>
                <button
                  className="btn btn-secondary btn-sm"
                  onClick={() => setInput("Can you guide me through step 1 calculation?")}
                >
                  "Can you guide me through step 1 calculation?"
                </button>
                <button
                  className="btn btn-secondary btn-sm"
                  onClick={() => setInput("Here are my readings: ecell=1.1, reported_value=-212.3")}
                >
                  "Here are my readings: ecell=1.1, reported_value=-212.3"
                </button>
              </div>
            </div>
          ) : (
            messages.map((m, i) => {
              // The step header is only worth showing when the step
              // changes; repeating the same prompt above every reply is noise.
              let prevStep: number | undefined;
              for (let j = i - 1; j >= 0; j--) {
                const pm = messages[j];
                if (pm.author === "tutor" && pm.metadata?.type === "socratic" && pm.metadata?.prompt) {
                  prevStep = pm.metadata.current_step;
                  break;
                }
              }
              const showStepHeader = prevStep === undefined || prevStep !== m.metadata?.current_step;
              return <MessageBubble key={m.id} message={m} showStepHeader={showStepHeader} />;
            })
          )}
          <div ref={scrollRef} />
        </div>

        {/* Composer Input Area */}
        <div style={{ padding: "16px 20px", borderTop: "1px solid var(--border)", background: "var(--surface)" }}>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              handleSend();
            }}
            style={{ display: "flex", gap: "10px", alignItems: "flex-end" }}
          >
            <textarea
              rows={2}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  handleSend();
                }
              }}
              placeholder={
                !activeClassroom
                  ? "Join a classroom to ask questions..."
                  : chatBlockedForStudent
                  ? "No active session -- ask your instructor to start one before you can chat."
                  : "Ask about theory, procedure, calculation, or enter readings..."
              }
              disabled={!activeClassroom || chatBlockedForStudent || sending}
              style={{ flex: 1, resize: "none" }}
            />
            <button
              type="submit"
              className="btn btn-primary"
              disabled={!input.trim() || !activeClassroom || chatBlockedForStudent || sending}
              style={{ height: "48px", padding: "0 20px" }}
            >
              {sending ? "Thinking…" : "Send"}
            </button>
          </form>
        </div>
      </main>

      {/* --- Modals --- */}
      {/* Join Code Modal */}
      {showJoinModal && (
        <div className="modal-backdrop" onClick={() => setShowJoinModal(false)}>
          <div className="modal-content" style={{ maxWidth: "400px" }} onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2 style={{ margin: 0, fontSize: "1rem" }}>Join Classroom</h2>
              <button className="btn btn-secondary btn-sm" onClick={() => setShowJoinModal(false)} aria-label="Close" style={{ display: "flex" }}><CloseIcon size={14} /></button>
            </div>
            <div className="modal-body">
              {error && <div className="error">{error}</div>}
              <label>
                <span>Enter Classroom Join Code</span>
                <input
                  type="text"
                  placeholder="e.g. 54321"
                  value={joinCode}
                  onChange={(e) => setJoinCode(e.target.value)}
                  className="mono"
                />

              </label>
              <button className="btn btn-primary" style={{ width: "100%" }} onClick={handleJoinClassroom}>
                Join Classroom
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Create Classroom Modal */}
      {showCreateModal && (
        <div className="modal-backdrop" onClick={() => setShowCreateModal(false)}>
          <div className="modal-content" style={{ maxWidth: "400px" }} onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2 style={{ margin: 0, fontSize: "1rem" }}>Create Section</h2>
              <button className="btn btn-secondary btn-sm" onClick={() => setShowCreateModal(false)} aria-label="Close" style={{ display: "flex" }}><CloseIcon size={14} /></button>
            </div>
            <div className="modal-body">
              {error && <div className="error">{error}</div>}
              <label>
                <span>Classroom Section Name</span>
                <input
                  type="text"
                  placeholder="e.g. BACHY105 - Slot L1+L2"
                  value={newClassroomName}
                  onChange={(e) => setNewClassroomName(e.target.value)}
                />
              </label>
              <button className="btn btn-primary" style={{ width: "100%" }} onClick={handleCreateClassroom}>
                Create Section
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Rename Thread Modal */}
      {renameThreadId && (
        <div className="modal-backdrop" onClick={() => setRenameThreadId(null)}>
          <div className="modal-content" style={{ maxWidth: "400px" }} onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2 style={{ margin: 0, fontSize: "1rem" }}>Rename Chat Thread</h2>
              <button className="btn btn-secondary btn-sm" onClick={() => setRenameThreadId(null)} aria-label="Close" style={{ display: "flex" }}><CloseIcon size={14} /></button>
            </div>
            <div className="modal-body">
              <label>
                <span>Thread Title</span>
                <input
                  type="text"
                  value={renameTitle}
                  onChange={(e) => setRenameTitle(e.target.value)}
                />
              </label>
              <button className="btn btn-primary" style={{ width: "100%" }} onClick={handleRenameThread}>
                Save Title
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Faculty Modal */}
      {showFacultyModal && activeClassroom && (
        <FacultyModal
          classroom={activeClassroom}
          experiments={experiments}
          onClose={() => setShowFacultyModal(false)}
          onClassroomUpdated={() => {
            loadClassrooms();
            if (activeClassroom) checkSessionStatus(activeClassroom.id);
          }}
        />
      )}

      {/* Admin Modal */}
      {showAdminModal && (
        <AdminModal onClose={() => setShowAdminModal(false)} />
      )}
    </div>
  );
}
