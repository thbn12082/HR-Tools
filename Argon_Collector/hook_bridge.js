// hook_bridge.js — Isolated World Bridge cho Argon_Collector
// Chuyển tiếp gói tin từ hook_main.js (MAIN world) về background.js và nhận lệnh điều phối xuống các iframe
(function () {
  "use strict";

  const EVENT_FROM_MAIN = "__argon_collector_to_bridge__";
  const EVENT_TO_MAIN = "__argon_bridge_to_main__";

  // 1. Nghe sự kiện từ hook_main.js trong cùng frame (capture phase)
  window.addEventListener(
    EVENT_FROM_MAIN,
    (event) => {
      try {
        if (!event || !event.detail || typeof event.detail !== "object") return;
        const { type, payload } = event.detail;
        if (!type) return;

        event.stopImmediatePropagation();
        event.stopPropagation();

        chrome.runtime
          .sendMessage({
            command: "ARGON_FRAME_EVENT",
            eventType: type,
            frameUrl: window.location.href,
            payload: payload || {},
          })
          .catch(() => {});
      } catch (_) {}
    },
    true
  );

  // 2. Nhận lệnh điều phối từ background.js (ví dụ: kích hoạt Email / kích hoạt SĐT tầng 1-2-3 / bấm SignalHire)
  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    try {
      if (!msg || typeof msg !== "object") return;
      if (msg.command === "ARGON_DISPATCH_TO_MAIN") {
        const evt = new CustomEvent(EVENT_TO_MAIN, {
          bubbles: false,
          cancelable: false,
          detail: msg.payload || {},
        });
        window.dispatchEvent(evt);
        sendResponse({ ok: true });
        return true;
      }
    } catch (_) {}
  });
})();
