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
import { ChatIcon, CloseIcon, EditIcon, LightbulbIcon, MenuIcon, PlusIcon, SendIcon, TrashIcon } from "./Icons";
import { ThemeToggle } from "./ThemeToggle";

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
  // Which threads have a reply in flight. "Sending" is per thread, so starting a
  // new chat while another is still streaming leaves the new chat usable.
  const [sendingKeys, setSendingKeys] = useState<Record<string, boolean>>({});
  // The thread currently on screen, readable synchronously from async callbacks.
  // A stale closure of `activeThreadId` is exactly how a reply from chat A used
  // to be appended into chat B, so every async result checks this ref first.
  const activeThreadRef = useRef<string | null>(null);
  const loadSeq = useRef(0);
  const sending = Boolean(sendingKeys[activeThreadId ?? "__new__"]);
  const [loadingMessages, setLoadingMessages] = useState(false);

  const [error, setError] = useState("");
  const [showJoinModal, setShowJoinModal] = useState(false);
  const [showCreateModal, setShowCreateModal] = useState(false);

  const [joinCode, setJoinCode] = useState("");
  const [newClassroomName, setNewClassroomName] = useState("");
  const [renameThreadId, setRenameThreadId] = useState<string | null>(null);
  const [renameTitle, setRenameTitle] = useState("");

  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  // Follow new text only while the student is already at the bottom, so
  // scrolling up to re-read an answer is never yanked away by streaming.
  const pinnedToBottom = useRef(true);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const narrow = useNarrow();

  // On narrow screens the sidebar is a drawer; close it once the student
  // has picked a chat or classroom so they land on the conversation.
  useEffect(() => {
    setSidebarOpen(false);
  }, [activeThreadId, activeClassroom]);

  // Drawer: Escape closes it, and the page behind it does not scroll.
  useEffect(() => {
    if (!sidebarOpen) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setSidebarOpen(false);
    window.addEventListener("keydown", onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [sidebarOpen]);

  // iOS Safari does not resize the layout viewport for the keyboard, so the
  // app height follows the visual viewport to keep the composer in view.
  useEffect(() => {
    const vv = window.visualViewport;
    if (!vv) return;
    const root = document.documentElement;
    const sync = () => {
      if (Math.abs(vv.scale - 1) > 0.01) return; // pinch-zoom: leave the layout alone
      root.style.setProperty("--app-h", `${Math.round(vv.height)}px`);
      if (pinnedToBottom.current) scrollRef.current?.scrollIntoView({ block: "end" });
    };
    sync();
    vv.addEventListener("resize", sync);
    return () => {
      vv.removeEventListener("resize", sync);
      root.style.removeProperty("--app-h");
    };
  }, []);

  // Auto-scroll to bottom of messages
  useEffect(() => {
    if (pinnedToBottom.current) {
      scrollRef.current?.scrollIntoView({ behavior: sending ? "auto" : "smooth", block: "end" });
    }
  }, [messages, sending]);

  // Composer grows with its text up to a cap, then scrolls inside itself.
  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, [input]);

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

  // The one way to change the active thread: update the ref immediately and
  // clear the visible messages so nothing from the previous thread lingers
  // while the new thread's history loads.
  const activateThread = (id: string | null) => {
    pinnedToBottom.current = true;
    if (activeThreadRef.current !== id) {
      activeThreadRef.current = id;
      setMessages([]);
    }
    setActiveThreadId(id);
  };

  // Refresh the sidebar list only; never changes which thread is open.
  const refreshThreadList = async () => {
    if (!activeClassroom || !selectedExpId) return;
    try {
      const res = await api.get<{ threads: ChatThread[] }>(
        `/api/chat/threads?classroom_id=${activeClassroom.id}&experiment_id=${selectedExpId}`
      );
      setThreads(res.threads);
    } catch (e) {
      console.error("Failed to refresh chat threads", e);
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
        activateThread(res.threads[0].id);
      } else {
        activateThread(null);
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
    const seq = ++loadSeq.current;
    setLoadingMessages(true);
    try {
      const res = await api.get<{ messages: UnifiedChatMessage[] }>(
        `/api/chat/threads/${threadId}/messages`
      );
      // A slow response for a thread the student has already left must never
      // overwrite the thread they are looking at now (A -> B -> A switching).
      if (seq !== loadSeq.current || activeThreadRef.current !== threadId) return;
      setMessages(res.messages);
    } catch (e) {
      console.error("Failed to load messages", e);
    } finally {
      if (seq === loadSeq.current) setLoadingMessages(false);
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
      // A brand-new, empty conversation: new id, no messages, no leftover input.
      activeThreadRef.current = null; // force the clear even if ids were equal
      activateThread(fresh.id);
      setMessages([]);
      setInput("");
      setError("");
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
        activateThread(remaining.length > 0 ? remaining[0].id : null);
      }
    } catch (err) {
      console.error("Failed to delete thread", err);
    }
  };

  // Send Message handler — streams tokens via SSE so the reply appears
  // character-by-character while the LLM generates it.
  const handleSend = async (override?: string) => {
    const text = (override ?? input).trim();
    if (!text || !activeClassroom || sending) return;

    // The thread this message belongs to. Everything that comes back from the
    // server is applied only while this is still the thread on screen.
    const originThread = activeThreadRef.current;
    const originKey = originThread ?? "__new__";
    const isCurrent = () => activeThreadRef.current === originThread;

    setError("");
    setSendingKeys((prev) => ({ ...prev, [originKey]: true }));
    setInput("");
    pinnedToBottom.current = true; // a new question always shows its answer

    // Optimistic user message
    const tempUserMsg: UnifiedChatMessage = {
      id: `temp-${Date.now()}`,
      author: "student",
      content: text,
      kind: "qa",
      created_at: new Date().toISOString(),
    };
    // Streaming placeholder for the tutor reply — content grows with each chunk
    const tempTutorId = `temp-stream-${Date.now()}`;
    const tempTutorMsg: UnifiedChatMessage = {
      id: tempTutorId,
      author: "tutor",
      content: "",
      kind: "qa",
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, tempUserMsg, tempTutorMsg]);

    try {
      let finalResult: {
        thread_id: string;
        thread_title: string;
        message: UnifiedChatMessage;
      } | null = null;

      for await (const event of api.streamMessage({
        classroom_id: activeClassroom.id,
        experiment_id: selectedExpId,
        message: text,
        thread_id: originThread,
      })) {
        if (event.type === "chunk") {
          if (!isCurrent()) continue; // the student moved to another chat
          setMessages((prev) =>
            prev.map((m) =>
              m.id === tempTutorId ? { ...m, content: m.content + event.text } : m
            )
          );
        } else if (event.type === "done") {
          finalResult = {
            thread_id: event.thread_id,
            thread_title: event.thread_title,
            message: event.message as UnifiedChatMessage,
          };
        } else if (event.type === "error") {
          throw new ApiError(event.status, event.detail);
        }
      }

      if (!finalResult) throw new Error("Stream ended without a done event");

      const res = finalResult;
      if (!isCurrent()) {
        // The student opened another chat while this reply was generating. The
        // reply is saved server-side under its own thread; do not touch the
        // chat on screen, just refresh the sidebar (titles, new thread).
        await refreshThreadList();
      } else if (originThread === null || originThread !== res.thread_id) {
        // A message sent from a not-yet-created chat: switch onto the thread
        // the server just created. The activeThreadId effect below then calls
        // loadMessages(), which replaces `messages` from the server.
        activateThread(res.thread_id);
        await refreshThreadList();
      } else {
        setThreads((prev) =>
          prev.map((t) => (t.id === res.thread_id ? { ...t, title: res.thread_title } : t))
        );
        // Give the settled student message a permanent id: a `temp-` id
        // would be swept away by the next send's cleanup, making every
        // earlier prompt vanish from the thread.
        const settledUserMsg = { ...tempUserMsg, id: `local-${res.message.id}` };
        setMessages((prev) => [
          ...prev.filter((m) => m.id !== tempUserMsg.id && m.id !== tempTutorId),
          settledUserMsg,
          res.message,
        ]);
      }
    } catch (e) {
      if (isCurrent()) {
        setError(e instanceof ApiError ? e.message : String(e));
        setMessages((prev) =>
          prev.filter((m) => m.id !== tempUserMsg.id && m.id !== tempTutorId)
        );
        setInput(text);
      }
    } finally {
      setSendingKeys((prev) => {
        const next = { ...prev };
        delete next[originKey];
        return next;
      });
    }
  };

  // One Settings entry replaces the four staff buttons. Presentation only:
  // every staff route re-checks access on the server.
  const canOpenSettings = Boolean(me.capabilities?.settings) || Boolean(activeClassroom?.co_faculty);
  const settingsHref = activeClassroom
    ? `/settings/classroom?classroom=${encodeURIComponent(activeClassroom.id)}`
    : "/settings/classroom";
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
      {/* --- Sidebar (desktop) / drawer (phone) --- */}
      <aside
        id="chat-drawer"
        className={`app-sidebar ${sidebarOpen ? "open" : ""}`}
        aria-label="Chats and settings"
        inert={narrow && !sidebarOpen ? true : undefined}
      >
        {/* Brand + identity */}
        <div className="sb-section sb-head">
          <div className="sb-brand-row">
            <strong className="sb-brand">LabTutor</strong>
            <span
              className={`pill ${
                me.role === "admin" ? "pill-escalated" : me.role === "faculty" ? "pill-pass" : "pill-p1"
              }`}
            >
              {me.role.toUpperCase()}
            </span>
            <button
              type="button"
              className="icon-btn sb-close"
              aria-label="Close menu"
              onClick={() => setSidebarOpen(false)}
            >
              <CloseIcon size={18} />
            </button>
          </div>
          <div className="sb-identity">{me.name || me.email}</div>
        </div>

        {/* Classroom Selector */}
        <div className="sb-section">
          <div className="sb-label-row">
            <span className="sb-label">Classroom</span>
            <button type="button" className="sb-link" onClick={() => setShowJoinModal(true)}>
              + Join code
            </button>
          </div>
          {classrooms.length > 0 ? (
            <select
              className="sb-select"
              aria-label="Classroom"
              value={activeClassroom?.id || ""}
              onChange={(e) => {
                const c = classrooms.find((x) => x.id === e.target.value);
                if (c) setActiveClassroom(c);
                setError("");
              }}
            >
              {classrooms.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name} {c.co_faculty ? "(Co-Faculty)" : ""}
                </option>
              ))}
            </select>
          ) : (
            <p className="sb-empty">Not in any classroom yet.</p>
          )}

          {(me.role === "faculty" || me.role === "admin") && (
            <button
              className="btn btn-sm btn-secondary sb-wide-btn"
              onClick={() => setShowCreateModal(true)}
            >
              + Create Classroom Section
            </button>
          )}
        </div>

        {/* Experiment Selector */}
        <div className="sb-section">
          <span className="sb-label">IACHY102 experiment</span>
          {me.role === "student" ? (
            sessionInfo.active && sessionInfo.experiment_id ? (
              <div className="sb-exp is-active">
                <span className="exp-code">{sessionInfo.experiment_id.toUpperCase()}</span>
                <span>{experiments.find((e) => e.id === sessionInfo.experiment_id)?.title || "Experiment"}</span>
              </div>
            ) : (
              <div className="sb-exp is-muted">No active session. Ask your instructor to start one.</div>
            )
          ) : (
            <select
              className="sb-select"
              aria-label="Experiment"
              value={selectedExpId}
              onChange={(e) => {
                setSelectedExpId(e.target.value);
                setError("");
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

        {/* Chat threads */}
        <div className="sb-threads-head">
          <span className="sb-label">Chats</span>
          <button onClick={handleNewChat} disabled={!activeClassroom} className="btn btn-primary sb-new-chat">
            <PlusIcon size={14} /> New chat
          </button>
        </div>

        <nav className="sb-threads" aria-label="Chat threads">
          {threads.length === 0 ? (
            <p className="sb-empty sb-empty-center">No chats for this experiment yet. Tap “New chat” to start.</p>
          ) : (
            threads.map((t) => {
              const isActive = t.id === activeThreadId;
              return (
                <div key={t.id} className={`thread-item ${isActive ? "active" : ""}`}>
                  <button
                    type="button"
                    className="thread-main"
                    aria-current={isActive ? "page" : undefined}
                    onClick={() => activateThread(t.id)}
                  >
                    <ChatIcon size={14} />
                    <span className="thread-title">{t.title}</span>
                  </button>
                  <button
                    type="button"
                    className="icon-btn thread-action"
                    aria-label={`Rename chat “${t.title}”`}
                    onClick={(e) => {
                      e.stopPropagation();
                      setRenameThreadId(t.id);
                      setRenameTitle(t.title);
                    }}
                  >
                    <EditIcon size={14} />
                  </button>
                  <button
                    type="button"
                    className="icon-btn thread-action"
                    aria-label={`Delete chat “${t.title}”`}
                    onClick={(e) => handleDeleteThread(t.id, e)}
                  >
                    <TrashIcon size={14} />
                  </button>
                </div>
              );
            })
          )}
        </nav>

        {/* Footer */}
        <div className="sb-footer">
          {canOpenSettings && (
            <a className="btn btn-secondary btn-sm settings-link-drawer" href={settingsHref}>
              Settings
            </a>
          )}
          <div className="sb-footer-row">
            <span className="sb-theme">
              <ThemeToggle />
            </span>
            <button
              type="button"
              className="sb-signout"
              onClick={async () => {
                try {
                  await api.post("/api/auth/logout");
                } finally {
                  window.location.href = "/";
                }
              }}
            >
              Sign out
            </button>
          </div>
        </div>
      </aside>

      {/* --- Main Chat Surface --- */}
      <main className="app-main">
        <header className="bar chat-header">
          <button
            type="button"
            className="icon-btn menu-btn"
            aria-label="Open menu"
            aria-expanded={sidebarOpen}
            aria-controls="chat-drawer"
            onClick={() => setSidebarOpen(true)}
          >
            <MenuIcon />
          </button>
          <div className="chat-heading">
            <div className="chat-heading-row">
              <span className="exp-code">{selectedExpId.toUpperCase()}</span>
              <h1 className="chat-title" title={selectedExp?.title}>
                <span className="title-full">{selectedExp?.title || "Experiment"}</span>
                <span className="title-short">{shortTitle(selectedExp?.title)}</span>
              </h1>
              {selectedExp && (
                <span className={`pill hide-narrow pill-${selectedExp.priority.toLowerCase().replace("+", "plus")}`}>
                  {selectedExp.priority}
                </span>
              )}
            </div>
            <p className="muted chat-classroom hide-narrow">
              Classroom: <strong>{activeClassroom?.name || "None selected"}</strong>
            </p>
          </div>

          <div className="bar-right">
            <span className={`session-status ${sessionInfo.active ? "on" : "off"}`}>
              <span className="session-dot" aria-hidden="true" />
              {sessionInfo.active ? (
                <>
                  <span className="hide-narrow">Session&nbsp;</span>Active
                </>
              ) : (
                <>
                  No<span className="hide-narrow">&nbsp;active</span>&nbsp;session
                </>
              )}
            </span>

            {canOpenSettings && (
              <a className="btn btn-sm btn-secondary settings-link-top" href={settingsHref}>
                Settings
              </a>
            )}
            <span className="hide-narrow">
              <ThemeToggle />
            </span>
          </div>
        </header>

        {/* Error Banner */}
        {error && (
          <div className="error chat-error" role="alert">
            {error}
          </div>
        )}

        {/* Messages Container */}
        <div
          className="chat-scroll"
          onScroll={(e) => {
            const el = e.currentTarget;
            pinnedToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 120;
          }}
        >
          {!activeClassroom ? (
            <div className="card empty-state">
              <h2>Welcome to LabTutor</h2>
              <p className="muted">You are not in a classroom section yet.</p>
              <button className="btn btn-primary" onClick={() => setShowJoinModal(true)}>
                Enter Join Code
              </button>
            </div>
          ) : messages.length === 0 ? (
            // A fresh chat always starts here: no workflow, no step, no
            // history. The student picks a path; the server keeps this
            // thread in "initial" mode until they do (or ask something).
            <div className="card empty-state">
              <h2>Hi! What would you like to do today?</h2>
              <p className="muted">
                We&apos;re on <strong>{selectedExp?.title}</strong>. Study the theory behind it, or {selectedExpId === "exp07" ? "reason through its key ideas, one short question at a time." : "work through the experiment one step at a time."}
              </p>
              <div className="empty-actions">
                <button className="btn btn-primary" disabled={sending || chatBlockedForStudent} onClick={() => handleSend("Theory / Study")}>
                  Theory / Study
                </button>
                <button className="btn btn-secondary" disabled={sending || chatBlockedForStudent} onClick={() => handleSend("Practical / Experiment")}>
                  Practical / Experiment
                </button>
              </div>
              <p className="muted empty-hint">
                <LightbulbIcon size={14} /> <em>Or just ask a question, or paste your readings (e.g. ecell=1.1) for a check.</em>
              </p>
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
              const isLast = i === messages.length - 1;
              const prev = messages[i - 1];
              return (
                <MessageBubble
                  key={m.id}
                  message={m}
                  streaming={m.id.startsWith("temp-stream-")}
                  showStepHeader={showStepHeader}
                  onQuickReply={isLast && !sending ? (text) => handleSend(text) : undefined}
                  triggerText={m.author === "tutor" && prev?.author === "student" ? prev.content : undefined}
                />
              );
            })
          )}
          <div ref={scrollRef} />
        </div>

        {/* Composer */}
        <div className="composer">
          {activeClassroom && chatBlockedForStudent && (
            <p className="composer-note">No active session. Chat opens when your instructor starts one.</p>
          )}
          <form
            className="composer-form"
            onSubmit={(e) => {
              e.preventDefault();
              handleSend();
            }}
          >
            <textarea
              ref={inputRef}
              className="composer-input"
              rows={1}
              enterKeyHint="send"
              aria-label="Message"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                // On a touch device Enter is a newline (the Send button sends);
                // on desktop Enter sends and Shift+Enter is a newline.
                const touch = typeof window !== "undefined" && window.matchMedia("(pointer: coarse)").matches;
                if (e.key === "Enter" && !e.shiftKey && !touch) {
                  e.preventDefault();
                  handleSend();
                }
              }}
              placeholder={
                !activeClassroom
                  ? "Join a classroom to ask questions…"
                  : chatBlockedForStudent
                  ? "Waiting for a session…"
                  : narrow
                  ? "Ask a question…"
                  : "Ask about theory, procedure, calculation, or enter readings…"
              }
              disabled={!activeClassroom || chatBlockedForStudent || sending}
            />
            <button
              type="submit"
              className="composer-send"
              aria-label={sending ? "Waiting for the reply" : "Send message"}
              disabled={!input.trim() || !activeClassroom || chatBlockedForStudent || sending}
            >
              {sending ? <span className="spinner" aria-hidden="true" /> : <SendIcon />}
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

    </div>
  );
}

/** "Build atoms and molecules; orbital contributions (Gabedit/...)" ->
 * "Build atoms and molecules": the phone header shows the first clause and
 * the drawer keeps the full title. */
function shortTitle(title?: string): string {
  if (!title) return "Experiment";
  return title.split(/[;(]/)[0].trim() || title;
}

/** True on phone-sized screens, where the sidebar is an off-canvas drawer. */
function useNarrow(): boolean {
  const [narrow, setNarrow] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(max-width: 768px)");
    const sync = () => setNarrow(mq.matches);
    sync();
    mq.addEventListener("change", sync);
    return () => mq.removeEventListener("change", sync);
  }, []);
  return narrow;
}
