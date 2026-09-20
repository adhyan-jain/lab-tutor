"use client";

import { Suspense } from "react";
import { useMe } from "@/components/MeContext";
import { SessionsWorkspace } from "@/components/SessionsWorkspace";

export default function SessionsSettingsPage() {
  const me = useMe();
  return (
    <Suspense fallback={null}>
      <SessionsWorkspace me={me} />
    </Suspense>
  );
}
