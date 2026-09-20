"use client";

import { Shell } from "@/components/Shell";
import { ChatWorkspace } from "@/components/ChatWorkspace";

export default function FacultyPage() {
  return (
    <Shell requireRole={["faculty", "admin"]} chrome={false}>
      {(me) => <ChatWorkspace me={me} />}
    </Shell>
  );
}
