"use client";

import { Shell } from "@/components/Shell";
import { ChatWorkspace } from "@/components/ChatWorkspace";

export default function AdminPage() {
  return (
    <Shell requireRole="admin" chrome={false}>
      {(me) => <ChatWorkspace me={me} />}
    </Shell>
  );
}
