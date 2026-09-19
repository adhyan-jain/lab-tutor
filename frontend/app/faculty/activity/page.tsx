"use client";

import { Suspense } from "react";
import { Shell } from "@/components/Shell";
import { ActivityWorkspace } from "@/components/ActivityWorkspace";

export default function ActivityPage() {
  return (
    <Shell requireRole={["faculty", "admin"]}>
      {(me) => (
        <Suspense fallback={null}>
          <ActivityWorkspace me={me} />
        </Suspense>
      )}
    </Shell>
  );
}
