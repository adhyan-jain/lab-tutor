"use client";

import { AdminPanel } from "@/components/AdminPanel";
import { useMe } from "@/components/MeContext";

export default function AdminSettingsPage() {
  const me = useMe();
  if (!me.capabilities?.admin) {
    return (
      <div className="page">
        <p className="notice">Platform admin is only available to administrators.</p>
      </div>
    );
  }
  return <AdminPanel />;
}
