"use client";

import { Suspense } from "react";
import { Shell } from "@/components/Shell";
import { SessionsWorkspace } from "@/components/SessionsWorkspace";

export default function SessionsPage() {
  return (
    <Shell requireRole={["faculty", "admin"]}>
      {(me) => (
        <Suspense fallback={null}>
          <SessionsWorkspace me={me} />
        </Suspense>
      )}
    </Shell>
  );
}
