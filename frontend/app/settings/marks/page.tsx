"use client";

import { Suspense } from "react";
import { MarksWorkspace } from "@/components/MarksWorkspace";
import { useMe } from "@/components/MeContext";

export default function MarksSettingsPage() {
  const me = useMe();
  return (
    <Suspense fallback={null}>
      <MarksWorkspace me={me} />
    </Suspense>
  );
}
