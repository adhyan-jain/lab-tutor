"use client";

import { useState } from "react";
import type { Me } from "@/lib/api";
import { api } from "@/lib/api";

const LINKS = [
  { href: "/", label: "Chat" },
  { href: "/faculty/activity", label: "Activity & Data" },
  { href: "/faculty/marks", label: "Pre/Post Marks" },
];

/** Top bar for the faculty/admin pages that live outside the student chat
 * (Activity & Data, Marks). Collapses to a menu button on narrow screens. */
export function AppNav({ me, current }: { me: Me; current: string }) {
  const [open, setOpen] = useState(false);

  const signOut = async () => {
    try {
      await api.post("/api/auth/logout");
    } finally {
      window.location.href = "/";
    }
  };

  return (
    <nav className="appnav">
      <div className="appnav-row">
        <strong className="appnav-brand">LabTutor</strong>
        <button
          className="appnav-toggle btn btn-secondary btn-sm"
          aria-expanded={open}
          aria-label="Toggle navigation"
          onClick={() => setOpen((v) => !v)}
        >
          {open ? "Close" : "Menu"}
        </button>
      </div>
      <div className={`appnav-links ${open ? "open" : ""}`}>
        {LINKS.map((l) => (
          <a
            key={l.href}
            href={l.href}
            className={`appnav-link ${l.href === current ? "active" : ""}`}
          >
            {l.label}
          </a>
        ))}
        <span className="appnav-user muted">{me.name || me.email}</span>
        <button className="btn btn-secondary btn-sm" onClick={signOut}>
          Sign out
        </button>
      </div>
    </nav>
  );
}
