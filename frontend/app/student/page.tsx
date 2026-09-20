"use client";

import { Shell } from "@/components/Shell";
import { ChatWorkspace } from "@/components/ChatWorkspace";

export default function StudentPage() {
  return (
    <Shell requireRole="student" chrome={false}>
      {(me) => <ChatWorkspace me={me} />}
    </Shell>
  );
}
