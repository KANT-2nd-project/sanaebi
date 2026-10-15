"use client";

import { createContext, useContext, useState, type ReactNode } from "react";

type DraftStore = { read: () => string; write: (value: string) => void };
const DraftContext = createContext<DraftStore | null>(null);

/** One draft per mounted root layout; never persisted to browser storage. */
export function ChatDraftProvider({ children }: { children: ReactNode }) {
  const [store] = useState<DraftStore>(() => {
    let draft = "";
    return { read: () => draft, write: value => { draft = value; } };
  });
  return <DraftContext.Provider value={store}>{children}</DraftContext.Provider>;
}

export function useChatDraft() {
  const store = useContext(DraftContext);
  if (!store) throw new Error("ChatDraftProvider is required");
  return store;
}
