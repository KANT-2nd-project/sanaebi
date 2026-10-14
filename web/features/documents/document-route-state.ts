export type RouteTransition =
  | { kind: "same" }
  | { kind: "accepted" }
  | { kind: "blocked"; reason: "pending-write" | "unsaved-changes"; restoreUrl: string };

/** Decides whether a URL change may load or reset the active document editor. */
export class DocumentRouteState {
  private currentUrl: string;
  private approvedUrl: string | null = null;
  private blockedUrl: string | null = null;

  constructor(initialUrl: string) {
    this.currentUrl = initialUrl;
  }

  get acceptedUrl() {
    return this.currentUrl;
  }

  approve(url: string) {
    this.approvedUrl = url;
  }

  observe(
    url: string,
    state: { dirty: boolean; pendingWrite: boolean; confirmDiscard: () => boolean },
  ): RouteTransition {
    if (this.approvedUrl === url) {
      this.currentUrl = url;
      this.approvedUrl = null;
      this.blockedUrl = null;
      return { kind: "accepted" };
    }
    if (this.blockedUrl === url) {
      return { kind: "blocked", reason: state.pendingWrite ? "pending-write" : "unsaved-changes", restoreUrl: this.currentUrl };
    }
    if (url === this.currentUrl) {
      this.blockedUrl = null;
      return { kind: "same" };
    }
    if (state.pendingWrite) {
      this.blockedUrl = url;
      return { kind: "blocked", reason: "pending-write", restoreUrl: this.currentUrl };
    }
    if (state.dirty && !state.confirmDiscard()) {
      this.blockedUrl = url;
      return { kind: "blocked", reason: "unsaved-changes", restoreUrl: this.currentUrl };
    }
    this.currentUrl = url;
    this.blockedUrl = null;
    return { kind: "accepted" };
  }

  canLoad(url: string) {
    return url === this.currentUrl && url !== this.blockedUrl;
  }
}
