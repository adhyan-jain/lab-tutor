"use client";

import { Suspense } from "react";
import { ActivityWorkspace } from "@/components/ActivityWorkspace";
import { useMe } from "@/components/MeContext";

export default function ActivitySettingsPage() {
  const me = useMe();
  return (
    <Suspense fallback={null}>
      <ActivityWorkspace me={me} />
    </Suspense>
  );
}
