// linkedin_orchestrator.js — Bộ điều phối trung tâm trên trang hồ sơ LinkedIn
// Thực thi:
// - Luồng Email: Chạy tất cả 5 extension tự động (ContactOut, Kendo, Snov.io, Apollo 1-cr, Lusha) để gộp Mail Công Ty + Mail Cá Nhân
// - Luồng SĐT (Thác nước 4 tầng): ContactOut -> Lusha -> Apollo (8-cr) -> Đánh dấu chờ bấm tay SignalHire
(function () {
  "use strict";

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  let lastOrchestratedUrl = "";
  let isOrchestrating = false;
  let hudContainer = null;

  // Trạng thái gộp của ứng viên hiện tại trên trang
  let state = {
    liUrl: "",
    fullName: "",
    headline: "",
    company: "",
    personalEmails: new Set(),
    workEmails: new Set(),
    allEmails: new Set(),
    phones: new Map(),
    checkedSources: new Set(),
    exhaustedSources: new Set(),
    sourceCredits: {},
    phoneSource: "",
    sourceStatus: {
      contactout: "⏳ Chờ",
      kendo: "⏳ Chờ",
      snov: "⏳ Chờ",
      lusha: "⏳ Chờ",
      apollo: "⏳ Chờ",
      signalhire: "🖐️ Bấm tay",
    },
  };

  function getCleanProfileUrl(url) {
    if (!url) return "";
    try {
      const u = new URL(url);
      return (u.origin + u.pathname).replace(/\/+$/, "") + "/";
    } catch (_) {
      return url.split("?")[0].split("#")[0];
    }
  }

  function isLinkedInProfilePage(url) {
    if (!url) return false;
    const l = url.toLowerCase();
    return l.includes("linkedin.com/in/") || l.includes("linkedin.com/pub/");
  }

  function scrapeLinkedInMetadata() {
    let fullName = "";
    let headline = "";
    let company = "";

    try {
      const h1 =
        document.querySelector("main h1") ||
        document.querySelector("h1.text-heading-xlarge") ||
        document.querySelector(".pv-text-details__left-panel h1") ||
        document.querySelector("h1");
      if (h1 && h1.textContent) {
        fullName = h1.textContent.trim().replace(/\s+/g, " ");
      }
      if (!fullName || fullName.toLowerCase().includes("linkedin")) {
        const m = (document.title || "").match(/^(?:\(\d+\)\s*)?([^|-]+?)\s*(?:\||-)\s*LinkedIn/i);
        if (m && m[1]) fullName = m[1].trim();
      }

      const hlNode =
        document.querySelector(".text-body-medium.break-words") ||
        document.querySelector(".pv-text-details__left-panel .text-body-medium");
      if (hlNode && hlNode.textContent) {
        headline = hlNode.textContent.trim().replace(/\s+/g, " ");
      }

      const compBtn =
        document.querySelector('button[aria-label^="Current company:"]') ||
        document.querySelector(".pv-text-details__right-panel .inline-show-more-text");
      if (compBtn) {
        const aria = compBtn.getAttribute("aria-label") || "";
        if (aria.startsWith("Current company:")) {
          company = aria.replace(/^Current company:\s*/i, "").replace(/\.\s*Click to skip.*$/i, "").trim();
        } else if (compBtn.textContent) {
          company = compBtn.textContent.trim().replace(/\s+/g, " ");
        }
      }
    } catch (_) {}

    return {
      liUrl: getCleanProfileUrl(window.location.href),
      fullName,
      headline,
      company,
    };
  }

  function addPhoneToMerged(raw, sourceName) {
    if (!raw || typeof raw !== "string") return;
    const digits = raw.replace(/\D/g, "");
    if (digits.length >= 8 && digits.length <= 15 && !/^0+$/.test(digits)) {
      if (!state.phones.has(digits)) {
        state.phones.set(digits, raw.trim());
        if (!state.phoneSource && sourceName) {
          state.phoneSource = sourceName;
        }
      } else {
        const ex = state.phones.get(digits);
        if (!ex.startsWith("+") && raw.trim().startsWith("+")) {
          state.phones.set(digits, raw.trim());
        }
      }
    }
  }

  // Giao diện HUD nổi góc dưới bên trái trang LinkedIn
  function ensureHudMounted() {
    if (hudContainer && document.body.contains(hudContainer)) return;
    hudContainer = document.createElement("div");
    hudContainer.id = "argon-orchestrator-hud";
    hudContainer.style.cssText = [
      "position:fixed",
      "bottom:18px",
      "left:18px",
      "width:335px",
      "background:rgba(10,15,26,0.95)",
      "color:#eef2fa",
      "border:1px solid #263859",
      "border-radius:14px",
      "padding:13px 15px",
      "font-family:Inter,-apple-system,BlinkMacSystemFont,sans-serif",
      "font-size:12px",
      "z-index:2147483647",
      "box-shadow:0 16px 38px rgba(0,0,0,0.65)",
      "backdrop-filter:blur(12px)",
    ].join(";");

    hudContainer.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;border-bottom:1px solid #1e2d47;padding-bottom:6px;">
        <div style="font-weight:800;font-size:13px;color:#5b8cff;">⚡ Argon 6-Ext Orchestrator</div>
        <span id="argon-hud-step" style="font-size:11px;padding:2px 8px;border-radius:99px;background:rgba(25,212,162,0.16);color:#19d4a2;font-weight:700;">Đang quét</span>
      </div>
      <div id="argon-hud-candidate" style="font-weight:700;color:#fff;margin-bottom:8px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">Ứng viên: ...</div>
      <div id="argon-hud-grid" style="display:grid;grid-template-columns:1fr 1fr;gap:5px;margin-bottom:9px;font-size:11.5px;"></div>
      <div id="argon-hud-counts" style="background:#080d18;border:1px solid #1b2840;border-radius:9px;padding:7px 9px;margin-bottom:9px;font-size:11.5px;line-height:1.5;">
        📧 Mail Công ty: <b id="argon-cnt-work" style="color:#38bdf8;">0</b> • Mail Cá nhân: <b id="argon-cnt-pers" style="color:#19d4a2;">0</b><br/>
        📞 Số điện thoại: <b id="argon-cnt-phone" style="color:#c084fc;">0</b> <span id="argon-phone-src" style="color:#8795ad;font-size:10.5px;"></span>
      </div>
      <button id="argon-btn-signalhire" style="width:100%;padding:8px 10px;border-radius:9px;border:1px solid rgba(247,178,59,0.5);background:linear-gradient(135deg,#f59e0b,#d97706);color:#090d16;font-weight:800;font-size:12px;cursor:pointer;">
        🎯 Bấm lấy bằng SignalHire (10cr/tháng)
      </button>
    `;

    document.body.appendChild(hudContainer);

    const btnSh = hudContainer.querySelector("#argon-btn-signalhire");
    if (btnSh) {
      btnSh.addEventListener("click", async () => {
        btnSh.textContent = "⏳ Đang kích hoạt SignalHire...";
        state.sourceStatus.signalhire = "⚡ Đang lấy...";
        renderHud();
        await broadcastToFrames({
          action: "RUN_SERVICE",
          service: "signalhire",
          mode: "manual_signalhire",
          liUrl: state.liUrl,
        });
        setTimeout(() => {
          btnSh.textContent = "✅ Đã bấm SignalHire (Đang gộp KQ)";
          renderHud();
        }, 2800);
      });
    }
    renderHud();
  }

  function renderHud(stepLabel) {
    if (!hudContainer) return;
    if (stepLabel) {
      const stepEl = hudContainer.querySelector("#argon-hud-step");
      if (stepEl) stepEl.textContent = stepLabel;
    }
    const candEl = hudContainer.querySelector("#argon-hud-candidate");
    if (candEl) {
      candEl.textContent = state.fullName ? `👤 ${state.fullName}` : `🔗 ${state.liUrl}`;
    }
    const gridEl = hudContainer.querySelector("#argon-hud-grid");
    if (gridEl) {
      const labels = [
        ["contactout", "ContactOut"],
        ["kendo", "Kendo"],
        ["snov", "Snov.io"],
        ["lusha", "Lusha"],
        ["apollo", "Apollo"],
        ["signalhire", "SignalHire"],
      ];
      gridEl.innerHTML = labels
        .map(
          ([k, title]) => `
          <div style="background:#111a2e;border:1px solid #1e2d47;border-radius:7px;padding:4px 7px;display:flex;justify-content:space-between;align-items:center;">
            <span style="color:#94a3b8;font-weight:600;">${title}</span>
            <span style="font-weight:700;color:#e2e8f0;font-size:11px;">${state.sourceStatus[k] || "—"}</span>
          </div>`
        )
        .join("");
    }
    const wEl = hudContainer.querySelector("#argon-cnt-work");
    const pEl = hudContainer.querySelector("#argon-cnt-pers");
    const phEl = hudContainer.querySelector("#argon-cnt-phone");
    const srcEl = hudContainer.querySelector("#argon-phone-src");
    if (wEl) wEl.textContent = String(state.workEmails.size);
    if (pEl) pEl.textContent = String(state.personalEmails.size);
    if (phEl) phEl.textContent = String(state.phones.size);
    if (srcEl) {
      srcEl.textContent = state.phoneSource ? `(từ ${state.phoneSource})` : "(chưa có)";
    }
  }

  function broadcastToFrames(payload) {
    return chrome.runtime
      .sendMessage({
        command: "ARGON_BROADCAST_TO_FRAMES",
        payload,
      })
      .catch(() => {});
  }

  // Nhận dữ liệu trả về từ bất kỳ frame nào của 6 extension
  chrome.runtime.onMessage.addListener((msg) => {
    if (!msg || msg.command !== "ARGON_ORCHESTRATOR_EVENT") return;
    const { eventType, payload } = msg;
    if (!payload || typeof payload !== "object") return;

    if (eventType === "credit_sync") {
      const svc = payload.service || "";
      if (svc && typeof payload.emailCredit === "number") {
        state.sourceCredits[svc] = payload.emailCredit;
        if (payload.emailCredit <= 0 || payload.outOfCredits) {
          state.exhaustedSources.add(svc);
          state.sourceStatus[svc] = "🔴 0 cr";
        }
        renderHud();
      }
      return;
    }

    if (eventType === "source_partial" || eventType === "source_result") {
      const src = payload.source || "";
      if (src) state.checkedSources.add(src);
      if (src && typeof payload.remainingCredit === "number") {
        state.sourceCredits[src] = payload.remainingCredit;
      }
      if (payload.outOfCredits && src) {
        state.exhaustedSources.add(src);
        state.sourceCredits[src] = 0;
        state.sourceStatus[src] = "🔴 0 cr";
      } else if (src) {
        const eCount = (payload.emails || []).length;
        const pCount = (payload.phones || []).length;
        const crSuffix = typeof state.sourceCredits[src] === "number" ? ` (${state.sourceCredits[src]}cr)` : "";
        state.sourceStatus[src] = (eCount > 0 || pCount > 0 ? `✅ ${eCount}E/${pCount}P` : "⚪ 0 KQ") + crSuffix;
      }

      for (const pe of payload.personalEmails || []) state.personalEmails.add(pe);
      for (const we of payload.workEmails || []) state.workEmails.add(we);
      for (const ae of payload.emails || []) state.allEmails.add(ae);
      for (const ph of payload.phones || []) addPhoneToMerged(ph, src);

      renderHud();
    }
  });

  // Cuộn trang nhẹ nhàng để kích hoạt các section của LinkedIn & các sidebar extension
  async function gentleHumanScroll() {
    try {
      window.scrollTo({ top: 320, behavior: "smooth" });
      await sleep(900);
      window.scrollTo({ top: 640, behavior: "smooth" });
      await sleep(900);
      window.scrollTo({ top: 180, behavior: "smooth" });
    } catch (_) {}
  }

  async function orchestrateCurrentProfile() {
    const cleanUrl = getCleanProfileUrl(window.location.href);
    if (!isLinkedInProfilePage(cleanUrl)) return;
    if (isOrchestrating || cleanUrl === lastOrchestratedUrl) return;

    isOrchestrating = true;
    lastOrchestratedUrl = cleanUrl;

    try {
      await sleep(1500);
      const meta = scrapeLinkedInMetadata();
      state = {
        liUrl: meta.liUrl,
        fullName: meta.fullName,
        headline: meta.headline,
        company: meta.company,
        personalEmails: new Set(),
        workEmails: new Set(),
        allEmails: new Set(),
        phones: new Map(),
        checkedSources: new Set(),
        exhaustedSources: new Set(),
        sourceCredits: {},
        phoneSource: "",
        sourceStatus: {
          contactout: "⏳ Chờ",
          kendo: "⏳ Chờ",
          snov: "⏳ Chờ",
          lusha: "⏳ Chờ",
          apollo: "⏳ Chờ",
          signalhire: "🖐️ Bấm tay",
        },
      };

      ensureHudMounted();
      renderHud("Khởi tạo...");

      await broadcastToFrames({ action: "RESET_FOR_URL", liUrl: state.liUrl });
      await gentleHumanScroll();

      // Cào lại tên ứng viên nếu lúc đầu LinkedIn chưa render xong h1
      const refreshedMeta = scrapeLinkedInMetadata();
      if (refreshedMeta.fullName) state.fullName = refreshedMeta.fullName;
      if (refreshedMeta.headline) state.headline = refreshedMeta.headline;
      if (refreshedMeta.company) state.company = refreshedMeta.company;
      renderHud("Xin Task Plan...");

      // 1. Xin Task Plan động từ Server 127.0.0.1:8765
      let plan = null;
      try {
        plan = await chrome.runtime.sendMessage({
          command: "ARGON_GET_TASK_PLAN",
          liUrl: state.liUrl,
        });
      } catch (_) {}

      const emailExts =
        plan && Array.isArray(plan.emailExtensions)
          ? plan.emailExtensions
          : ["contactout", "kendo", "snov", "apollo", "lusha"];
      const phoneWaterfall =
        plan && Array.isArray(plan.phoneWaterfall)
          ? plan.phoneWaterfall
          : ["contactout", "lusha", "apollo"];
      const alreadyHasPhone = Boolean(plan && plan.alreadyHasPhone);

      // Đánh dấu các extension bị bỏ qua (do đã lấy ở profile trước hoặc đã hết credit)
      for (const k of ["contactout", "kendo", "snov", "lusha", "apollo"]) {
        if (!emailExts.includes(k) && !phoneWaterfall.includes(k)) {
          state.sourceStatus[k] = "⏭️ Đã có/Bỏ qua";
        }
      }
      renderHud("Quét Email (5 nguồn)...");

      // ====================================================================
      // LUỒNG 1: QUÉT EMAIL ĐA NGUỒN (Gộp cả Email Công Ty + Email Cá Nhân)
      // ====================================================================
      for (const svc of emailExts) {
        if (svc === "signalhire") continue; // SignalHire chỉ bấm tay
        state.sourceStatus[svc] = "⚡ Tìm Email...";
        renderHud();
        await broadcastToFrames({
          action: "RUN_SERVICE",
          service: svc,
          mode: "email",
          liUrl: state.liUrl,
        });
        await sleep(750);
      }

      // Đợi các request API Email trả về
      await sleep(3200);
      await broadcastToFrames({ action: "SCAN_DOM_ALL", liUrl: state.liUrl });
      await sleep(900);

      // ====================================================================
      // LUỒNG 2: THÁC NƯỚC SỐ ĐIỆN THOẠI (ContactOut -> Lusha -> Apollo -> SignalHire)
      // ====================================================================
      if (!alreadyHasPhone && state.phones.size === 0) {
        // TẦNG 1: CONTACTOUT
        if (phoneWaterfall.includes("contactout") && !state.exhaustedSources.has("contactout")) {
          renderHud("SĐT B1: ContactOut...");
          state.sourceStatus.contactout = "📞 Tìm SĐT...";
          renderHud();
          await broadcastToFrames({
            action: "RUN_SERVICE",
            service: "contactout",
            mode: "phone",
            liUrl: state.liUrl,
          });
          await sleep(3800);
        }

        // TẦNG 2: LUSHA (Chỉ kích hoạt nếu ContactOut KHÔNG tìm ra SĐT)
        if (state.phones.size === 0 && phoneWaterfall.includes("lusha") && !state.exhaustedSources.has("lusha")) {
          renderHud("SĐT B2: Lusha...");
          state.sourceStatus.lusha = "📞 Tìm SĐT...";
          renderHud();
          await broadcastToFrames({
            action: "RUN_SERVICE",
            service: "lusha",
            mode: "phone",
            liUrl: state.liUrl,
          });
          await sleep(3800);
        } else if (state.phones.size > 0) {
          // Đã có SĐT từ ContactOut -> tiết kiệm Lusha & Apollo
          renderHud("✅ Đã có SĐT (Tầng 1)");
        }

        // TẦNG 3: APOLLO 8-CREDIT (Chỉ kích hoạt nếu cả ContactOut VÀ Lusha đều KHÔNG có SĐT)
        if (state.phones.size === 0 && phoneWaterfall.includes("apollo") && !state.exhaustedSources.has("apollo")) {
          renderHud("SĐT B3: Apollo (8cr)...");
          state.sourceStatus.apollo = "📞 Tìm SĐT (8cr)...";
          renderHud();
          await broadcastToFrames({
            action: "RUN_SERVICE",
            service: "apollo",
            mode: "phone",
            liUrl: state.liUrl,
          });
          await sleep(4200);
        }
      }

      // Quét lại DOM lần cuối trước khi đóng gói gửi về Server 127.0.0.1:8765
      await broadcastToFrames({ action: "SCAN_DOM_ALL", liUrl: state.liUrl });
      await sleep(800);

      const personalList = Array.from(state.personalEmails);
      const workList = Array.from(state.workEmails);
      const allEmailList = Array.from(new Set([...workList, ...personalList, ...state.allEmails]));
      const phoneList = Array.from(state.phones.values());
      const needSignalHire = !alreadyHasPhone && phoneList.length === 0;

      if (needSignalHire) {
        renderHud("⚠️ Thiếu SĐT -> Chờ SignalHire");
        state.sourceStatus.signalhire = "⚠️ Cần bấm cứu nét";
        renderHud();
      } else {
        renderHud("✅ Hoàn tất hồ sơ");
      }

      await chrome.runtime.sendMessage({
        command: "ARGON_SAVE_MERGED_RESULT",
        data: {
          source: Array.from(state.checkedSources).join("+") || "multi",
          checkedSources: Array.from(state.checkedSources),
          exhaustedSources: Array.from(state.exhaustedSources),
          sourceCredits: state.sourceCredits,
          phoneSource: state.phoneSource || "",
          needSignalHire,
          liUrl: state.liUrl,
          fullName: state.fullName,
          headline: state.headline,
          company: state.company,
          workEmails: workList,
          personalEmails: personalList,
          uiEmails: allEmailList,
          emails: allEmailList,
          uiPhones: phoneList,
          phones: phoneList,
        },
      });
    } catch (_) {
    } finally {
      isOrchestrating = false;
    }
  }

  // Theo dõi chuyển trang SPA trên LinkedIn
  setInterval(() => {
    const clean = getCleanProfileUrl(window.location.href);
    if (isLinkedInProfilePage(clean) && clean !== lastOrchestratedUrl && !isOrchestrating) {
      orchestrateCurrentProfile();
    }
  }, 1200);

  if (isLinkedInProfilePage(window.location.href)) {
    orchestrateCurrentProfile();
  }
})();
