"use client";

import { Shell } from "@/components/Shell";
import { MarksWorkspace } from "@/components/MarksWorkspace";

export default function MarksPage() {
  return (
    <Shell requireRole={["faculty", "admin"]}>
      {(me) => <MarksWorkspace me={me} />}
    </Shell>
  );
}
