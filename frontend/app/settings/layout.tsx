"use client";

import { MeProvider } from "@/components/MeContext";
import { SettingsFrame } from "@/components/SettingsFrame";
import { Shell } from "@/components/Shell";

/** Every Settings screen: sign-in and capability checks once, then one frame. */
export default function SettingsLayout({ children }: { children: React.ReactNode }) {
  return (
    <Shell requireCapability="settings" chrome={false}>
      {(me) => (
        <MeProvider value={me}>
          <SettingsFrame me={me}>{children}</SettingsFrame>
        </MeProvider>
      )}
    </Shell>
  );
}
