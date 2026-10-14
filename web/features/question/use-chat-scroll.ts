"use client";

import { useCallback, useLayoutEffect, useRef, useState } from "react";
import type { Turn } from "./chat-session";

export function useChatScroll(turns: Turn[]) {
  const viewportRef = useRef<HTMLElement>(null);
  const dockRef = useRef<HTMLDivElement>(null);
  const following = useRef(true);
  const previous = useRef<Turn[]>([]);
  const [showLatest, setShowLatest] = useState(false);

  const onScroll = useCallback(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    const distance = viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight;
    following.current = distance <= 80;
    setShowLatest(distance > 80);
  }, []);

  const toLatest = useCallback(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    viewport.scrollTop = viewport.scrollHeight;
    following.current = true;
    setShowLatest(false);
  }, []);

  useLayoutEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    const changed = turns.find(turn => !previous.current.some(old => old.id === turn.id && old.status === turn.status));
    previous.current = turns;
    if (!turns.length) { viewport.scrollTop = 0; following.current = true; return; }
    if (changed && (changed.status === "pending" || following.current)) {
      const row = viewport.querySelector(`[data-turn-id="${changed.id}"]`);
      const target = changed.status === "pending" ? row : row?.querySelector(".assistant-message");
      if (target) {
        const top = viewport.scrollTop + target.getBoundingClientRect().top - viewport.getBoundingClientRect().top - 16;
        viewport.scrollTop = Math.max(0, top);
      }
    }
    // Update the scroll affordance after DOM growth, without moving readers.
    const distance = viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight;
    setShowLatest(distance > 80);
  }, [turns]);

  useLayoutEffect(() => {
    const viewport = viewportRef.current;
    const dock = dockRef.current;
    if (!viewport || !dock) return;
    let height = viewport.clientHeight;
    const observer = new ResizeObserver(() => {
      if (viewport.clientHeight === height) return;
      height = viewport.clientHeight;
      if (following.current) viewport.scrollTop = viewport.scrollHeight;
      onScroll();
    });
    observer.observe(viewport);
    observer.observe(dock);
    return () => observer.disconnect();
  }, [onScroll]);

  return { viewportRef, dockRef, onScroll, showLatest: turns.length > 0 && showLatest, toLatest };
}
