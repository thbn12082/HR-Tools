// background.js — Service Worker điều phối trung tâm của Argon_Collector
// Kết nối 2 chiều với máy chủ local 127.0.0.1:8765 và phát lệnh xuống toàn bộ iframe của 6 Extension

const SERVER_BASE = "http://127.0.0.1:8765";
let isPollingNextUrl = false;
let currentManagedTabId = null;

async function postToServer(path, payload) {
  try {
    const res = await fetch(`${SERVER_BASE}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload || {}),
    });
    if (!res.ok) return { ok: false, status: res.status };
    return await res.json();
  } catch (err) {
    return { ok: false, error: String(err) };
  }
}

async function getFromServer(path) {
  try {
    const res = await fetch(`${SERVER_BASE}${path}`, {
      method: "GET",
      headers: { Accept: "application/json" },
    });
    if (!res.ok) return null;
    return await res.json();
  } catch (_) {
    return null;
  }
}

// Tìm hoặc mở tab LinkedIn chính để điều hướng tuần tự
async function navigateToLinkedInUrl(targetUrl) {
  if (!targetUrl) return;
  try {
    const tabs = await chrome.tabs.query({});
    let liTab = tabs.find(
      (t) =>
        t.id === currentManagedTabId ||
        (t.url &&
          (t.url.includes("linkedin.com/in/") ||
            t.url.includes("linkedin.com/pub/") ||
            t.url.includes("linkedin.com/feed")))
    );

    if (!liTab) {
      liTab = tabs.find(
        (t) =>
          t.url &&
          !t.url.startsWith("chrome://") &&
          !t.url.startsWith("chrome-extension://") &&
          !t.url.includes("127.0.0.1:8765")
      );
    }

    if (liTab && liTab.id) {
      currentManagedTabId = liTab.id;
      await chrome.tabs.update(liTab.id, { url: targetUrl, active: true });
    } else {
      const created = await chrome.tabs.create({ url: targetUrl, active: true });
      if (created && created.id) currentManagedTabId = created.id;
    }
  } catch (_) {}
}

// Vòng lặp hỏi 127.0.0.1:8765/next_url?engine=multi mỗi 2.2s
async function pollNextUrlLoop() {
  if (isPollingNextUrl) return;
  isPollingNextUrl = true;
  try {
    const data = await getFromServer("/next_url?engine=multi");
    if (data && data.url) {
      await navigateToLinkedInUrl(data.url);
    }
  } catch (_) {
  } finally {
    isPollingNextUrl = false;
  }
}

setInterval(pollNextUrlLoop, 2200);

// Xử lý thông điệp từ hook_bridge.js (trong mọi iframe) và linkedin_orchestrator.js (trang chính)
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (!msg || typeof msg !== "object") return;

  const tabId = sender && sender.tab ? sender.tab.id : currentManagedTabId;

  // 1. Sự kiện từ bất kỳ frame nào (hook_main.js -> hook_bridge.js -> background.js)
  if (msg.command === "ARGON_FRAME_EVENT") {
    const { eventType, payload, frameUrl } = msg;

    if (eventType === "credit_sync") {
      postToServer("/account_status", {
        ...payload,
        frameUrl,
      });
      if (tabId) {
        chrome.tabs
          .sendMessage(tabId, {
            command: "ARGON_ORCHESTRATOR_EVENT",
            eventType: "credit_sync",
            payload,
          })
          .catch(() => {});
      }
      sendResponse({ ok: true });
      return true;
    }

    if (eventType === "source_partial" || eventType === "source_result") {
      // Báo ngay cho linkedin_orchestrator.js trên tab đó để điều phối thác nước SĐT
      if (tabId) {
        chrome.tabs
          .sendMessage(tabId, {
            command: "ARGON_ORCHESTRATOR_EVENT",
            eventType,
            payload,
          })
          .catch(() => {});
      }
      // Nếu là kết quả hoàn chỉnh hoặc từ bấm tay SignalHire, đẩy thẳng về Server để merge ngay
      if (eventType === "source_result" || (payload && payload.immediateSave)) {
        postToServer("/result", payload);
      }
      sendResponse({ ok: true });
      return true;
    }

    if (eventType === "authwall") {
      postToServer("/authwall", payload);
      sendResponse({ ok: true });
      return true;
    }

    sendResponse({ ok: true });
    return true;
  }

  // 2. linkedin_orchestrator.js xin kế hoạch chạy (Task Plan) cho URL hiện tại
  if (msg.command === "ARGON_GET_TASK_PLAN") {
    const liUrl = encodeURIComponent(msg.liUrl || "");
    getFromServer(`/task_plan?liUrl=${liUrl}`).then((plan) => {
      sendResponse(
        plan || {
          ok: true,
          emailExtensions: ["contactout", "kendo", "snov", "apollo", "lusha"],
          phoneWaterfall: ["contactout", "lusha", "apollo"],
          alreadyHasPhone: false,
          credits: {},
        }
      );
    });
    return true;
  }

  // 3. linkedin_orchestrator.js phát lệnh xuống TẤT CẢ các frame trong tab hiện tại
  if (msg.command === "ARGON_BROADCAST_TO_FRAMES") {
    if (tabId) {
      chrome.tabs
        .sendMessage(tabId, {
          command: "ARGON_DISPATCH_TO_MAIN",
          payload: msg.payload || {},
        })
        .catch(() => {});
    }
    sendResponse({ ok: true });
    return true;
  }

  // 4. linkedin_orchestrator.js gửi gói kết quả tổng hợp / từng phần về Server
  if (msg.command === "ARGON_SAVE_MERGED_RESULT") {
    postToServer("/result", msg.data || {}).then((res) => {
      sendResponse(res || { ok: true });
    });
    return true;
  }

  // 5. Tương thích ngược với ContactOut_Mod & Apollo_Mod nếu cùng nạp
  if (msg.command === "CO_MOD_SAVE_RESULT" || msg.command === "APOLLO_MOD_SAVE_RESULT") {
    postToServer("/result", msg.data || {}).then((res) => {
      sendResponse(res || { ok: true });
    });
    return true;
  }

  if (msg.command === "CO_MOD_SYNC_CREDITS") {
    postToServer("/account_status", msg.data || {}).then((res) => {
      sendResponse(res || { ok: true });
    });
    return true;
  }
});
