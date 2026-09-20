"use client";

import { createContext, useContext } from "react";
import type { Me } from "@/lib/api";

/** The signed-in user, provided once by a layout so nested pages need not
 * each wrap themselves in `Shell` just to learn who is signed in. */
const MeContext = createContext<Me | null>(null);

export const MeProvider = MeContext.Provider;

export function useMe(): Me {
  const me = useContext(MeContext);
  if (!me) throw new Error("useMe() used outside a MeProvider");
  return me;
}
