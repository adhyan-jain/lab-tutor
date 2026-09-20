"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { api, type Me } from "@/lib/api";
import { ThemeToggle } from "./ThemeToggle";

const TABS: { href: string; label: string; adminOnly?: boolean }[] = [
  { href: "/settings/classroom", label: "Classroom" },
  { href: "/settings/activity", label: "Activity & data" },
  { href: "/settings/sessions", label: "Session reports" },
  { href: "/settings/marks", label: "Pre/post marks" },
  { href: "/settings/admin", label: "Platform admin", adminOnly: true },
];

/** Tabs keep the selected classroom in the URL so switching sections does
 * not lose which class you were looking at. */
function SettingsTabs({ me }: { me: Me }) {
  const pathname = usePathname();
  const classroom = useSearchParams().get("classroom");
  const suffix = classroom ? `?classroom=${encodeURIComponent(classroom)}` : "";
  return (
    <nav className="settings-tabs" aria-label="Settings sections">
      {TABS.filter((t) => !t.adminOnly || me.capabilities?.admin).map((t) => (
        <Link
          key={t.href}
          href={`${t.href}${suffix}`}
          className={`settings-tab ${pathname === t.href ? "active" : ""}`}
          aria-current={pathname === t.href ? "page" : undefined}
        >
          {t.label}
        </Link>
      ))}
    </nav>
  );
}

/** The one frame every Settings screen shares: a single header (way back to
 * the chat, who you are, theme, sign out) and the section tabs. */
export function SettingsFrame({ me, children }: { me: Me; children: React.ReactNode }) {
  const signOut = async () => {
    try {
      await api.post("/api/auth/logout");
    } finally {
      window.location.href = "/";
    }
  };
  return (
    <div className="settings-frame">
      <header className="settings-header">
        <Link href="/" className="settings-back">
          Back to chat
        </Link>
        <h1 className="settings-title">Settings</h1>
        <div className="settings-user">
          <span className="muted settings-who">{me.name || me.email}</span>
          <ThemeToggle />
          <button className="btn btn-secondary btn-sm" onClick={signOut}>
            Sign out
          </button>
        </div>
      </header>
      <Suspense fallback={<nav className="settings-tabs" aria-hidden="true" />}>
        <SettingsTabs me={me} />
      </Suspense>
      <div className="settings-body">{children}</div>
    </div>
  );
}
