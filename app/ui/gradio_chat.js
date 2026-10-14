() => {
  const previous = window.__sanaebiCleanup;
  if (previous) previous();
  document.documentElement.lang = "ko";
  document.documentElement.classList.remove("dark");
  const listeners = new AbortController();
  const $ = selector => document.querySelector(selector);
  let locked = false, composing = false, timer, draft = "", submitted = false;
  let lastMarker = "", turns = 0, nearBottom = true, scrollBox, oldCount = 0;
  const touch = () => matchMedia("(hover: none) and (pointer: coarse)").matches;
  const input = () => $("#question textarea");
  const status = () => $("#chat-status span");
  function size() {
    const field = input();
    if (!field) return;
    field.style.height = "auto";
    field.style.height = Math.min(200, Math.max(60, field.scrollHeight)) + "px";
    field.style.overflowY = field.scrollHeight > 200 ? "auto" : "hidden";
    field.setAttribute("aria-describedby", "input-help question-error connection-error");
    field.setAttribute("aria-invalid", status()?.dataset.error === "true" ? "true" : "false");
    field.readOnly = locked;
  }
  function unlock() {
    locked = false;
    clearTimeout(timer);
    const send = $("#send-question");
    if (send) send.disabled = false;
    size();
  }
  function restore() {
    const field = input();
    if (field) {
      const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set;
      setter.call(field, draft);
      field.dispatchEvent(new Event("input", { bubbles: true }));
    }
  }
  function start(event, retry = false) {
    if (locked) { event.preventDefault(); event.stopImmediatePropagation(); return; }
    draft = input()?.value || "";
    if (!retry && !draft.trim()) {
      event.preventDefault(); event.stopImmediatePropagation();
      $("#question-error").textContent = "질문을 입력해주세요";
      input()?.setAttribute("aria-invalid", "true");
      input()?.focus();
      return;
    }
    locked = true; submitted = true;
    $("#connection-error").hidden = true;
    size();
    // Leave the current click available to Gradio; disable only afterwards.
    setTimeout(() => { if (locked && $("#send-question")) $("#send-question").disabled = true; }, 0);
    timer = setTimeout(() => {
      unlock(); restore();
      const error = $("#connection-error");
      if (error) {
        error.textContent = "응답 시간이 초과되었거나 서버에 연결할 수 없습니다. 질문을 확인하고 다시 시도해주세요.";
        error.hidden = false;
      }
      $("#expire-question")?.click();
      input()?.focus();
    }, 35000);
  }
  document.addEventListener("compositionstart", e => { if (e.target === input()) composing = true; }, { capture: true, signal: listeners.signal });
  document.addEventListener("compositionend", e => { if (e.target === input()) composing = false; }, { capture: true, signal: listeners.signal });
  document.addEventListener("keydown", e => {
    if (e.target !== input() || e.key !== "Enter") return;
    if (composing || e.isComposing || e.keyCode === 229 || e.repeat || locked) {
      e.stopImmediatePropagation();
      if (e.repeat || locked) e.preventDefault();
      return;
    }
    // Own the policy, including mobile; do not allow a second native submit.
    e.stopImmediatePropagation();
    if (e.shiftKey || touch()) {
      e.preventDefault();
      const field = input();
      field.setRangeText("\n", field.selectionStart, field.selectionEnd, "end");
      field.dispatchEvent(new Event("input", { bubbles: true }));
      size();
      return;
    }
    e.preventDefault();
    $("#send-question")?.click();
  }, { capture: true, signal: listeners.signal });
  document.addEventListener("input", e => { if (e.target === input()) size(); }, { signal: listeners.signal });
  document.addEventListener("click", e => {
    if (e.target.closest("#send-question")) start(e);
    if (e.target.closest("#retry-question")) start(e, true);
    if (e.target.closest("#new-chat")) {
      unlock(); draft = ""; submitted = false;
      const field = input();
      if (field) { field.value = ""; field.dispatchEvent(new Event("input", { bubbles: true })); field.focus(); }
      if ($("#connection-error")) $("#connection-error").hidden = true;
    }
    if (e.target.closest("#examples button")) {
      if (locked) { e.preventDefault(); e.stopImmediatePropagation(); return; }
      setTimeout(() => { size(); input()?.focus(); }, 100);
    }
    if (e.target.closest("#latest-message") && scrollBox) {
      scrollBox.scrollTop = scrollBox.scrollHeight;
      nearBottom = true; $("#latest-message").hidden = true;
    }
  }, { capture: true, signal: listeners.signal });
  function update() {
    size();
    const marker = status();
    if (marker) {
      const key = marker.outerHTML;
      if (key !== lastMarker) {
        lastMarker = key;
        if (marker.dataset.busy === "false" && submitted) {
          unlock(); submitted = false;
          if (!touch()) input()?.focus();
        }
        const count = Number(marker.dataset.turns);
        if (count > turns) nearBottom = true;
        turns = count;
      }
    }
    const container = $("#conversation");
    if (!container) return;
    const candidate = Array.from(container.querySelectorAll("div")).find(el => {
      const css = getComputedStyle(el);
      return ["auto", "scroll"].includes(css.overflowY) && el.clientHeight > 50;
    }) || container;
    if (candidate !== scrollBox) {
      scrollBox = candidate;
      scrollBox.addEventListener("scroll", () => {
        nearBottom = scrollBox.scrollHeight - scrollBox.scrollTop - scrollBox.clientHeight <= 80;
        if (nearBottom && $("#latest-message")) $("#latest-message").hidden = true;
      }, { signal: listeners.signal });
    }
    const messages = container.querySelectorAll(".message-row");
    if (messages.length !== oldCount) {
      oldCount = messages.length;
      const last = messages[messages.length - 1];
      if (last && nearBottom) {
        const offset = last.getBoundingClientRect().top - scrollBox.getBoundingClientRect().top + scrollBox.scrollTop;
        scrollBox.scrollTop = last.clientHeight > scrollBox.clientHeight ? offset : scrollBox.scrollHeight;
      } else if (last && $("#latest-message")) $("#latest-message").hidden = false;
    }
  }
  // Observe child/text changes, not the style mutations performed by size().
  const observer = new MutationObserver(() => requestAnimationFrame(update));
  observer.observe(document.body, { childList: true, subtree: true, characterData: true });
  update();
  window.__sanaebiCleanup = () => { clearTimeout(timer); listeners.abort(); observer.disconnect(); };
}
