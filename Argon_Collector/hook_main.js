// hook_main.js — Chạy trong MAIN world của mọi frame (LinkedIn + Iframe của 6 Extension)
// Nhiệm vụ:
// 1. Mở khóa toàn bộ Shadow DOM (closed -> open) để đọc/bấm nút của Lusha, Kendo, Snov, SignalHire, ContactOut, Apollo
// 2. Nghe lén fetch / XMLHttpRequest bắt trọn Email (Công ty + Cá nhân), SĐT và số dư Credit thực tế
// 3. Thực thi lệnh bấm Reveal theo đúng phân tầng:
//    - Email: đánh hội đồng 5 extension tự động (ContactOut, Kendo, Snov, Apollo 1-cr, Lusha)
//    - SĐT: thác nước ContactOut -> Lusha -> Apollo (8-cr)
//    - SignalHire (10-cr/tháng): TUYỆT ĐỐI KHÔNG tự bấm; chỉ bắt kết quả khi người dùng bấm tay hoặc bấm nút HUD
(function () {
  "use strict";

  if (window.__argon_hook_main_v2__) return;
  window.__argon_hook_main_v2__ = true;

  const EVENT_FROM_MAIN = "__argon_collector_to_bridge__";
  const EVENT_TO_MAIN = "__argon_bridge_to_main__";

  const origFetch = window.fetch;
  const origXhrOpen = XMLHttpRequest.prototype.open;
  const origXhrSend = XMLHttpRequest.prototype.send;
  const origAttachShadow = Element.prototype.attachShadow;
  const OrigPointerEvent = window.PointerEvent;
  const OrigMouseEvent = window.MouseEvent;
  const OrigCustomEvent = window.CustomEvent;
  const origDispatchEvent = EventTarget.prototype.dispatchEvent;

  // Danh sách toàn bộ ShadowRoot đã tạo trên trang/frame này để quét nút và kết quả
  const shadowRoots = new Set();

  if (typeof origAttachShadow === "function") {
    Element.prototype.attachShadow = function (init) {
      const opts = init && typeof init === "object" ? { ...init, mode: "open" } : { mode: "open" };
      const root = origAttachShadow.call(this, opts);
      try {
        shadowRoots.add(root);
      } catch (_) {}
      return root;
    };
  }

  const BLOCKED_TELEMETRY = [
    "sentry.io",
    "mixpanel.com",
    "google-analytics.com",
    "googletagmanager.com",
    "amplitude.com",
    "segment.io",
    "segment.com",
    "hotjar.com",
    "fullstory.com",
    "datadoghq.com",
    "logrocket.io",
    "statistics/url",
    "statistics/app",
    "statistics/engage",
  ];

  function isTelemetryUrl(url) {
    if (!url || typeof url !== "string") return false;
    const l = url.toLowerCase();
    return BLOCKED_TELEMETRY.some((pat) => l.includes(pat));
  }

  function emitToBridge(type, payload) {
    try {
      const evt = new OrigCustomEvent(EVENT_FROM_MAIN, {
        bubbles: false,
        cancelable: false,
        detail: { type, payload },
      });
      origDispatchEvent.call(window, evt);
    } catch (_) {}
  }

  // Nhận diện nguồn (service) dựa trên URL của request hoặc URL của frame hiện tại
  function detectServiceFromUrl(urlStr) {
    const combined = `${urlStr || ""} ${window.location.href || ""}`.toLowerCase();
    if (combined.includes("contactout.com") || combined.includes("contactout.io")) return "contactout";
    if (combined.includes("kendoninja.com") || combined.includes("kendoemailapp.com") || combined.includes("kendo")) return "kendo";
    if (combined.includes("apollo.io") || combined.includes("zenprospect.com")) return "apollo";
    if (combined.includes("snov.io") || combined.includes("snovio")) return "snov";
    if (combined.includes("lusha.com") || combined.includes("lusha")) return "lusha";
    if (combined.includes("signalhire.com") || combined.includes("signalhire")) return "signalhire";
    return "";
  }

  const PERSONAL_EMAIL_DOMAINS = new Set([
    "gmail.com",
    "googlemail.com",
    "yahoo.com",
    "yahoo.com.vn",
    "yahoo.co.uk",
    "hotmail.com",
    "outlook.com",
    "live.com",
    "msn.com",
    "icloud.com",
    "me.com",
    "aol.com",
    "protonmail.com",
    "proton.me",
    "yandex.com",
    "yandex.ru",
    "mail.ru",
    "zoho.com",
    "gmx.com",
  ]);

  const IGNORED_EMAIL_SUFFIXES = [
    "@sentry.io",
    "@contactout.com",
    "@contactout.io",
    "@apollo.io",
    "@zenprospect.com",
    "@lusha.com",
    "@snov.io",
    "@signalhire.com",
    "@kendoninja.com",
    "@kendoemailapp.com",
    ".png",
    ".svg",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".css",
    ".js",
  ];

  // Bộ nhớ tạm cho từng nguồn trong frame hiện tại
  const perSourceState = {
    contactout: { emails: new Set(), phones: new Map(), outOfCredits: false, credit: null, phoneCredit: null, accountEmail: "" },
    kendo: { emails: new Set(), phones: new Map(), outOfCredits: false, credit: null, phoneCredit: null, accountEmail: "" },
    apollo: { emails: new Set(), phones: new Map(), outOfCredits: false, credit: null, phoneCredit: null, accountEmail: "" },
    snov: { emails: new Set(), phones: new Map(), outOfCredits: false, credit: null, phoneCredit: null, accountEmail: "" },
    lusha: { emails: new Set(), phones: new Map(), outOfCredits: false, credit: null, phoneCredit: null, accountEmail: "" },
    signalhire: { emails: new Set(), phones: new Map(), outOfCredits: false, credit: null, phoneCredit: null, accountEmail: "" },
  };

  let currentLiUrl = "";
  if (window.location.href.includes("linkedin.com/in/") || window.location.href.includes("linkedin.com/pub/")) {
    currentLiUrl = window.location.href.split("?")[0];
  } else {
    const uParam = new URLSearchParams(window.location.search).get("url");
    if (uParam && uParam.includes("linkedin.com/")) {
      currentLiUrl = uParam.split("?")[0];
    }
  }

  function isValidEmail(raw, source) {
    if (!raw || typeof raw !== "string") return false;
    const lower = raw.trim().toLowerCase();
    if (!/^[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}$/.test(lower)) return false;
    if (lower.includes("*") || lower.includes("•") || lower === "email_not_unlocked@domain.com") return false;
    for (const suf of IGNORED_EMAIL_SUFFIXES) {
      if (lower.endsWith(suf)) return false;
    }
    const st = perSourceState[source];
    if (st && st.accountEmail && lower === st.accountEmail.toLowerCase()) return false;
    return true;
  }

  function classifyEmails(emailList) {
    const personalEmails = [];
    const workEmails = [];
    for (const em of emailList) {
      const lower = em.trim().toLowerCase();
      const domain = lower.split("@")[1] || "";
      if (PERSONAL_EMAIL_DOMAINS.has(domain)) {
        if (!personalEmails.includes(lower)) personalEmails.push(lower);
      } else {
        if (!workEmails.includes(lower)) workEmails.push(lower);
      }
    }
    return { personalEmails, workEmails };
  }

  function addPhoneToMap(raw, phoneMap) {
    if (!raw || typeof raw !== "string" || !phoneMap) return;
    const parts = raw.split(/[,;\n\r|]+/);
    for (let part of parts) {
      part = part.trim();
      if (!part || part.includes("*") || part.includes("•")) continue;
      if (/^(19|20)\d{2}\s*[-–]\s*(19|20)\d{2}$/.test(part)) continue;
      if (/^\d{4}-\d{2}-\d{2}/.test(part)) continue;
      const digits = part.replace(/\D/g, "");
      if (digits.length >= 8 && digits.length <= 15 && !/^0+$/.test(digits)) {
        if (digits.length === 8 && /^(19|20)\d{2}(19|20)\d{2}$/.test(digits)) continue;
        if (!phoneMap.has(digits)) {
          phoneMap.set(digits, part);
        } else {
          const ex = phoneMap.get(digits);
          if (!ex.startsWith("+") && part.startsWith("+")) {
            phoneMap.set(digits, part);
          }
        }
      }
    }
  }

  function extractFromRawText(str, source) {
    if (!str || typeof str !== "string" || !perSourceState[source]) return;
    const st = perSourceState[source];

    const emailRegex = /\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b/g;
    const emails = str.match(emailRegex) || [];
    for (const e of emails) {
      if (isValidEmail(e, source)) {
        st.emails.add(e.trim().toLowerCase());
      }
    }

    const cleaned = str.replace(/https?:\/\/[^\s"'<>]+/g, " ");
    const phonePatterns = [
      /\+\d{1,3}[\s.-]?(?:\(\d{1,4}\)[\s.-]?)?\d{2,4}[\s.-]?\d{2,4}[\s.-]?\d{2,5}/g,
      /\(\d{2,4}\)[\s.-]?\d{3,4}[\s.-]?\d{3,4}/g,
      /\b0[1-9]\d[\s.-]?\d{3,4}[\s.-]?\d{3,4}\b/g,
    ];
    for (const rgx of phonePatterns) {
      const matches = cleaned.match(rgx) || [];
      for (const m of matches) {
        addPhoneToMap(m, st.phones);
      }
    }
  }

  function walkJsonPayload(obj, source, parentKey = "") {
    if (!obj || !perSourceState[source]) return;
    const st = perSourceState[source];

    if (typeof obj === "string") {
      const lk = parentKey.toLowerCase();
      if (lk.includes("phone") || lk.includes("mobile") || lk.includes("tel") || lk.includes("cell") || lk.includes("direct")) {
        addPhoneToMap(obj, st.phones);
      }
      if (lk.includes("email") || lk.includes("mail")) {
        if (isValidEmail(obj, source)) st.emails.add(obj.trim().toLowerCase());
      }
      extractFromRawText(obj, source);
      return;
    }

    if (Array.isArray(obj)) {
      for (const item of obj) walkJsonPayload(item, source, parentKey);
      return;
    }

    if (typeof obj === "object") {
      let creditChanged = false;

      // Trường hợp object có cặp { used, limit / total / max } -> tính động số credit còn lại = limit - used
      const usedVal = obj.used ?? obj.credits_used ?? obj.creditsUsed ?? obj.consumed;
      const limitVal = obj.limit ?? obj.total ?? obj.max ?? obj.quota ?? obj.credits_limit ?? obj.creditsLimit;
      if (typeof usedVal === "number" && typeof limitVal === "number" && limitVal >= usedVal && limitVal <= 5000) {
        st.credit = Math.max(0, limitVal - usedVal);
        creditChanged = true;
      }

      for (const [k, v] of Object.entries(obj)) {
        const lk = k.toLowerCase();
        if (
          (lk === "credit" ||
            lk === "credits" ||
            lk === "emailcredit" ||
            lk === "email_credit" ||
            lk === "email_credits" ||
            lk === "emailcredits" ||
            lk === "credits_left" ||
            lk === "creditsleft" ||
            lk === "remaining_credits" ||
            lk === "remainingcredits" ||
            lk === "available_credits" ||
            lk === "availablecredits" ||
            lk === "export_credits" ||
            lk === "lookup_credits" ||
            lk === "balance" ||
            lk === "quota_left" ||
            lk === "quotaleft") &&
          typeof v === "number"
        ) {
          st.credit = v;
          creditChanged = true;
        } else if ((lk === "phonecredit" || lk === "phone_credit" || lk === "phone_credits") && typeof v === "number") {
          st.phoneCredit = v;
          creditChanged = true;
        } else if ((lk === "credits" || lk === "quota" || lk === "balance") && v && typeof v === "object") {
          if (typeof v.email === "number") {
            st.credit = v.email;
            creditChanged = true;
          }
          if (typeof v.phone === "number") {
            st.phoneCredit = v.phone;
            creditChanged = true;
          }
          if (typeof v.remaining === "number") {
            st.credit = v.remaining;
            creditChanged = true;
          }
          if (typeof v.available === "number") {
            st.credit = v.available;
            creditChanged = true;
          }
        }
        walkJsonPayload(v, source, k);
      }
      if (creditChanged) {
        emitToBridge("credit_sync", {
          service: source,
          accountEmail: st.accountEmail,
          emailCredit: st.credit,
          phoneCredit: st.phoneCredit,
          outOfCredits: st.credit === 0,
        });
      }
    }
  }

  function emitSourceUpdate(source, immediateSave = false) {
    const st = perSourceState[source];
    if (!st) return;
    const allEmails = Array.from(st.emails);
    const allPhones = Array.from(st.phones.values());
    const { personalEmails, workEmails } = classifyEmails(allEmails);

    emitToBridge(immediateSave ? "source_result" : "source_partial", {
      source,
      liUrl: currentLiUrl || window.location.href.split("?")[0],
      emails: allEmails,
      personalEmails,
      workEmails,
      phones: allPhones,
      outOfCredits: st.outOfCredits,
      remainingCredit: st.credit,
      remainingPhoneCredit: st.phoneCredit,
      accountEmail: st.accountEmail,
      immediateSave,
    });
  }

  function inspectNetworkPayload(reqUrl, status, rawText) {
    const source = detectServiceFromUrl(reqUrl);
    if (!source || !perSourceState[source]) return;
    const st = perSourceState[source];

    if (status === 402 || status === 429) {
      st.outOfCredits = true;
      st.credit = 0;
      emitToBridge("credit_sync", {
        service: source,
        emailCredit: 0,
        outOfCredits: true,
      });
    }

    if (!rawText || typeof rawText !== "string") return;
    const lower = rawText.toLowerCase();
    if (
      lower.includes("out of credit") ||
      lower.includes("no credits") ||
      lower.includes("not enough credit") ||
      lower.includes("credit limit") ||
      lower.includes("quota exceeded") ||
      lower.includes("upgrade your plan")
    ) {
      st.outOfCredits = true;
    }

    const prevEmailCount = st.emails.size;
    const prevPhoneCount = st.phones.size;

    extractFromRawText(rawText, source);
    try {
      const parsed = JSON.parse(rawText);
      walkJsonPayload(parsed, source);
    } catch (_) {}

    if (st.emails.size > prevEmailCount || st.phones.size > prevPhoneCount || st.outOfCredits) {
      // Nếu là SignalHire (bấm tay), lưu ngay lập tức vào ket_qua.json / ket_qua.csv!
      emitSourceUpdate(source, source === "signalhire");
    }
  }

  // 1. Hook window.fetch
  if (typeof origFetch === "function") {
    window.fetch = new Proxy(origFetch, {
      apply(target, thisArg, argArray) {
        const reqUrl =
          typeof argArray[0] === "string"
            ? argArray[0]
            : (argArray[0] && argArray[0].url) || "";

        if (isTelemetryUrl(reqUrl)) {
          return Promise.resolve(
            new Response(JSON.stringify({ ok: true }), {
              status: 200,
              headers: { "Content-Type": "application/json" },
            })
          );
        }

        const p = Reflect.apply(target, thisArg, argArray);
        return Promise.resolve(p).then((res) => {
          try {
            const clone = res.clone();
            const status = res.status || 200;
            clone
              .text()
              .then((txt) => inspectNetworkPayload(reqUrl, status, txt))
              .catch(() => {});
          } catch (_) {}
          return res;
        });
      },
    });
  }

  // 2. Hook XMLHttpRequest
  const xhrMeta = new WeakMap();
  if (typeof origXhrOpen === "function" && typeof origXhrSend === "function") {
    XMLHttpRequest.prototype.open = new Proxy(origXhrOpen, {
      apply(target, thisArg, argArray) {
        try {
          const url = String(argArray[1] || "");
          const blocked = isTelemetryUrl(url);
          xhrMeta.set(thisArg, { url, blocked });
          if (blocked) {
            const newArgs = argArray.slice();
            newArgs[0] = "GET";
            newArgs[1] = "data:application/json,%7B%22ok%22%3Atrue%7D";
            return Reflect.apply(target, thisArg, newArgs);
          }
        } catch (_) {}
        return Reflect.apply(target, thisArg, argArray);
      },
    });

    XMLHttpRequest.prototype.send = new Proxy(origXhrSend, {
      apply(target, thisArg, argArray) {
        const meta = xhrMeta.get(thisArg);
        if (meta && meta.blocked) {
          return Reflect.apply(target, thisArg, []);
        }
        try {
          thisArg.addEventListener("load", function () {
            try {
              const reqUrl = (meta && meta.url) || "";
              const status = this.status || 200;
              if (this.responseType === "" || this.responseType === "text") {
                inspectNetworkPayload(reqUrl, status, this.responseText);
              } else if (this.responseType === "json" && this.response) {
                inspectNetworkPayload(reqUrl, status, JSON.stringify(this.response));
              }
            } catch (_) {}
          });
        } catch (_) {}
        return Reflect.apply(target, thisArg, argArray);
      },
    });
  }

  // 3. Lắng nghe postMessage từ ContactOut / Apollo / Lusha / Kendo
  window.addEventListener("message", (event) => {
    try {
      const msg = event.data;
      if (!msg || typeof msg !== "object") return;
      if (msg.type === "contact_out_profile_page_data" && msg.payload && msg.payload.data) {
        const d = msg.payload.data;
        const newUrl = d.liUrl || d.publicUrl || "";
        if (newUrl && newUrl.includes("linkedin.com/")) {
          currentLiUrl = newUrl.split("?")[0];
        }
      }
      if (msg.type === "contact_out_set_user" || msg.type === "contact_out_refresh_user") {
        const u = (msg.payload && msg.payload.userInfo) || msg.user;
        if (u) {
          if (u.email) perSourceState.contactout.accountEmail = u.email;
          if (typeof u.credit === "number") perSourceState.contactout.credit = u.credit;
          if (typeof u.phoneCredit === "number") perSourceState.contactout.phoneCredit = u.phoneCredit;
          emitToBridge("credit_sync", {
            service: "contactout",
            accountEmail: u.email || "",
            emailCredit: perSourceState.contactout.credit,
            phoneCredit: perSourceState.contactout.phoneCredit,
          });
        }
      }
    } catch (_) {}
  });

  // Công cụ duyệt toàn bộ phần tử DOM + mọi ShadowRoot đã mở khóa
  function queryAllDeep(selector) {
    const results = [];
    try {
      document.querySelectorAll(selector).forEach((el) => results.push(el));
    } catch (_) {}
    for (const root of shadowRoots) {
      try {
        root.querySelectorAll(selector).forEach((el) => results.push(el));
      } catch (_) {}
    }
    return results;
  }

  function isVisible(el) {
    if (!el) return false;
    const rect = el.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return false;
    const style = window.getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden" || style.opacity === "0") return false;
    return true;
  }

  async function sleep(ms) {
    return new Promise((r) => setTimeout(r, ms));
  }

  async function humanClick(el) {
    if (!el || !isVisible(el)) return false;
    try {
      const rect = el.getBoundingClientRect();
      const clientX = Math.round(rect.left + rect.width * (0.35 + Math.random() * 0.3));
      const clientY = Math.round(rect.top + rect.height * (0.35 + Math.random() * 0.3));
      const opts = {
        bubbles: true,
        cancelable: true,
        composed: true,
        view: window,
        clientX,
        clientY,
      };
      el.dispatchEvent(new OrigPointerEvent("pointerover", { ...opts, pointerId: 1, pointerType: "mouse", isPrimary: true }));
      el.dispatchEvent(new OrigMouseEvent("mouseover", { ...opts, button: 0, buttons: 0 }));
      await sleep(35 + Math.floor(Math.random() * 40));
      if (!isVisible(el)) return false;
      el.dispatchEvent(new OrigPointerEvent("pointerdown", { ...opts, pointerId: 1, pointerType: "mouse", isPrimary: true, button: 0, buttons: 1 }));
      el.dispatchEvent(new OrigMouseEvent("mousedown", { ...opts, button: 0, buttons: 1, detail: 1 }));
      await sleep(45 + Math.floor(Math.random() * 45));
      if (!isVisible(el)) return false;
      el.dispatchEvent(new OrigPointerEvent("pointerup", { ...opts, pointerId: 1, pointerType: "mouse", isPrimary: true, button: 0, buttons: 0 }));
      el.dispatchEvent(new OrigMouseEvent("mouseup", { ...opts, button: 0, buttons: 0, detail: 1 }));
      el.dispatchEvent(new OrigMouseEvent("click", { ...opts, button: 0, buttons: 0, detail: 1 }));
      return true;
    } catch (_) {
      return false;
    }
  }

  // Nhận diện một phần tử nút bấm thuộc về Extension nào (khi nhiều extension cùng gắn vào DOM LinkedIn)
  function inferElementService(el) {
    const frameSvc = detectServiceFromUrl(window.location.href);
    if (frameSvc) return frameSvc;

    let cur = el;
    let depth = 0;
    while (cur && depth < 10) {
      const idCls = `${cur.id || ""} ${cur.className || ""} ${cur.getAttribute ? cur.getAttribute("data-testid") || "" : ""}`.toLowerCase();
      if (idCls.includes("contactout") || idCls.includes("co-")) return "contactout";
      if (idCls.includes("kendo")) return "kendo";
      if (idCls.includes("apollo") || idCls.includes("zp_") || idCls.includes("zp-")) return "apollo";
      if (idCls.includes("snov")) return "snov";
      if (idCls.includes("lusha")) return "lusha";
      if (idCls.includes("signalhire") || idCls.includes("sh-")) return "signalhire";
      cur = cur.parentElement || (cur.getRootNode && cur.getRootNode().host) || null;
      depth++;
    }
    return "";
  }

  // Quét động số dư Credit hiển thị trực tiếp trên DOM / Badge của từng Extension (không dùng số gán cứng)
  function scanDomCreditsForSource(activeSvc) {
    if (!activeSvc || !perSourceState[activeSvc]) return;
    const st = perSourceState[activeSvc];
    const frameSvc = detectServiceFromUrl(window.location.href);

    const nodes = queryAllDeep("span, div, p, b, strong, small, button, a");
    let foundCredit = null;
    let foundOut = false;

    for (const node of nodes) {
      if (!isVisible(node)) continue;
      if (!frameSvc) {
        const nodeSvc = inferElementService(node);
        if (nodeSvc !== activeSvc) continue;
      }
      if (node.children && node.children.length > 2) continue;

      const rawTxt = (node.innerText || node.textContent || "").replace(/\s+/g, " ").trim();
      if (!rawTxt || rawTxt.length > 90) continue;
      const lower = rawTxt.toLowerCase();

      if (
        lower.includes("out of credit") ||
        lower.includes("no credits left") ||
        lower.includes("0 credits left") ||
        lower.includes("0 credit left") ||
        lower.includes("limit reached") ||
        lower.includes("not enough credit") ||
        /\b0\s*\/\s*\d+\s*(?:credits?|cr)\b/i.test(rawTxt)
      ) {
        foundOut = true;
        foundCredit = 0;
        break;
      }

      // Khớp dạng "38 / 50 credits" hoặc "4/5 credits left"
      const mFrac = rawTxt.match(/\b(\d{1,4})\s*\/\s*(\d{1,4})\s*(?:email\s+|phone\s+)?(?:credits?|cr|lượt)\b/i);
      if (mFrac) {
        const num = parseInt(mFrac[1], 10);
        const den = parseInt(mFrac[2], 10);
        if (!isNaN(num) && !isNaN(den) && num <= den && den <= 5000) {
          foundCredit = lower.includes("used") ? Math.max(0, den - num) : num;
          break;
        }
      }

      // Khớp dạng "42 credits left", "42 credits remaining", "Credits: 42", "Balance: 42"
      const mAfter = rawTxt.match(/\b(\d{1,4})\s+(?:free\s+|email\s+|monthly\s+|daily\s+)?(?:credits?|cr)\s*(?:left|remaining|available)?\b/i);
      if (mAfter && !lower.includes("cost") && !lower.includes("use 1") && !lower.includes("use 8")) {
        const val = parseInt(mAfter[1], 10);
        if (!isNaN(val) && val <= 5000) {
          foundCredit = val;
        }
      }

      const mBefore = rawTxt.match(/\b(?:credits?\s*(?:left|remaining|balance)?|balance|remaining)\s*[:\-]\s*(\d{1,4})\b/i);
      if (mBefore) {
        const val = parseInt(mBefore[1], 10);
        if (!isNaN(val) && val <= 5000) {
          foundCredit = val;
          break;
        }
      }
    }

    let changed = false;
    if (foundOut && !st.outOfCredits) {
      st.outOfCredits = true;
      st.credit = 0;
      changed = true;
    }
    if (typeof foundCredit === "number" && foundCredit !== st.credit) {
      st.credit = foundCredit;
      if (foundCredit === 0) st.outOfCredits = true;
      changed = true;
    }

    if (changed) {
      emitToBridge("credit_sync", {
        service: activeSvc,
        accountEmail: st.accountEmail,
        emailCredit: st.credit,
        phoneCredit: st.phoneCredit,
        outOfCredits: st.outOfCredits,
      });
    }
  }

  // Quét DOM của frame/shadowRoot hiện tại để gom thêm Email, SĐT & số dư Credit thực tế hiển thị trên UI
  function scanDomForSource(targetSource) {
    const frameSvc = detectServiceFromUrl(window.location.href);
    const activeSvc = targetSource || frameSvc;
    if (!activeSvc || !perSourceState[activeSvc]) return;
    const st = perSourceState[activeSvc];

    scanDomCreditsForSource(activeSvc);

    const nodes = queryAllDeep("a[href^='mailto:'], a[href^='tel:'], span, div, p, li, td");
    for (const node of nodes) {
      if (!isVisible(node)) continue;
      if (!frameSvc) {
        const nodeSvc = inferElementService(node);
        if (nodeSvc !== activeSvc) continue;
      }

      if (node.tagName === "A") {
        const href = node.getAttribute("href") || "";
        if (href.toLowerCase().startsWith("mailto:")) {
          const mail = decodeURIComponent(href.replace(/^mailto:/i, "")).split("?")[0].trim();
          if (isValidEmail(mail, activeSvc)) st.emails.add(mail.toLowerCase());
        } else if (href.toLowerCase().startsWith("tel:")) {
          const tel = decodeURIComponent(href.replace(/^tel:/i, "")).trim();
          addPhoneToMap(tel, st.phones);
        }
      }

      if (node.children && node.children.length === 0 && node.textContent) {
        const txt = node.textContent.trim();
        if (txt.length >= 6 && txt.length <= 90) {
          extractFromRawText(txt, activeSvc);
        }
      }
    }
  }

  // Thực thi bấm nút Reveal cho đúng Extension và đúng Loại (email | phone | manual_signalhire)
  async function executeServiceAction(service, mode) {
    const frameSvc = detectServiceFromUrl(window.location.href);
    // Nếu đang ở trong iframe của thằng khác thì bỏ qua
    if (frameSvc && frameSvc !== service) return;

    // Bảo vệ tuyệt đối: SignalHire chỉ chạy khi mode === "manual_signalhire" (do người dùng bấm)
    if (service === "signalhire" && mode !== "manual_signalhire") {
      return;
    }

    // Nếu Tầng 3 SĐT gọi Apollo: phát thêm tín hiệu sang iframe sidebar của Apollo_Mod (nếu có)
    if (service === "apollo" && mode === "phone") {
      try {
        window.postMessage({ type: "ARGON_APOLLO_UNLOCK_PHONE", liUrl: currentLiUrl }, "*");
      } catch (_) {}
    }

    const candidates = queryAllDeep("button, a, div[role='button'], span[role='button']");
    const matchedButtons = [];

    for (const el of candidates) {
      if (!isVisible(el)) continue;
      if (el.hasAttribute("disabled") || el.getAttribute("aria-disabled") === "true") continue;

      if (!frameSvc) {
        const elSvc = inferElementService(el);
        if (elSvc && elSvc !== service) continue;
        if (!elSvc) continue;
      }

      const txt = (el.innerText || el.textContent || "").replace(/\s+/g, " ").trim().toLowerCase();
      const testId = (el.getAttribute("data-testid") || "").toLowerCase();
      const aria = (el.getAttribute("aria-label") || "").toLowerCase();

      if (mode === "email") {
        // Khi chỉ lấy Email: KHÔNG bấm nút Phone/Mobile của Apollo (8cr) hoặc Lusha Phone-only
        if (
          service === "apollo" &&
          (txt.includes("phone") || txt.includes("mobile") || txt.includes("direct dial") || txt.includes("call"))
        ) {
          continue;
        }
        if (
          testId === "reveal-emails" ||
          testId === "deep-search-email" ||
          txt === "view email" ||
          txt === "find email" ||
          txt === "show email" ||
          txt === "get email" ||
          txt === "access email" ||
          txt === "access email only" ||
          txt.startsWith("access email") ||
          txt.includes("find email") ||
          txt.includes("view email") ||
          txt.includes("get email") ||
          txt.includes("show email") ||
          (service === "kendo" && (txt.includes("get") || txt.includes("find") || txt.includes("show") || txt.includes("reveal"))) ||
          (service === "snov" && (txt.includes("find") || txt.includes("get") || txt.includes("save") || txt.includes("search"))) ||
          (service === "lusha" && (txt.includes("show email") || txt.includes("show contact") || txt === "show")) ||
          (service === "contactout" && (txt === "show" || txt === "reveal" || aria === "reveal button"))
        ) {
          matchedButtons.push(el);
        }
      } else if (mode === "phone") {
        // Khi lấy SĐT theo thác nước (ContactOut -> Lusha -> Apollo)
        if (
          testId === "reveal-phones" ||
          txt.includes("view phone") ||
          txt.includes("find phone") ||
          txt.includes("show phone") ||
          txt.includes("get phone") ||
          txt.includes("access mobile") ||
          txt.includes("access phone") ||
          txt.includes("reveal phone") ||
          txt.includes("reveal mobile") ||
          txt.includes("direct dial") ||
          (service === "lusha" && (txt.includes("show") || txt.includes("reveal") || txt.includes("phone") || txt.includes("contact"))) ||
          (service === "contactout" && (txt === "show" || txt === "reveal" || aria === "reveal button"))
        ) {
          matchedButtons.push(el);
        }
      } else if (mode === "manual_signalhire" && service === "signalhire") {
        if (
          txt.includes("reveal") ||
          txt.includes("show") ||
          txt.includes("find") ||
          txt.includes("contact") ||
          txt.includes("get")
        ) {
          matchedButtons.push(el);
        }
      }
    }

    for (const btn of matchedButtons.slice(0, 3)) {
      await humanClick(btn);
      await sleep(450 + Math.floor(Math.random() * 250));
    }

    await sleep(1600);
    scanDomForSource(service);
    emitSourceUpdate(service, mode === "manual_signalhire");
  }

  // 4. Nếu người dùng tự tay click trực tiếp vào nút Reveal của SignalHire trên giao diện gốc của SignalHire -> tự bắt kết quả sau 2.5s
  document.addEventListener(
    "click",
    (e) => {
      try {
        const target = e.target;
        if (!target) return;
        const svc = inferElementService(target);
        if (svc === "signalhire") {
          setTimeout(() => {
            scanDomForSource("signalhire");
            emitSourceUpdate("signalhire", true);
          }, 2500);
          setTimeout(() => {
            scanDomForSource("signalhire");
            emitSourceUpdate("signalhire", true);
          }, 5500);
        }
      } catch (_) {}
    },
    true
  );

  // 5. Lắng nghe lệnh điều phối từ hook_bridge.js
  window.addEventListener(EVENT_TO_MAIN, (event) => {
    try {
      const cmd = event && event.detail;
      if (!cmd || typeof cmd !== "object") return;

      if (cmd.liUrl) {
        currentLiUrl = String(cmd.liUrl).split("?")[0];
      }

      if (cmd.action === "RESET_FOR_URL") {
        for (const k of Object.keys(perSourceState)) {
          perSourceState[k].emails.clear();
          perSourceState[k].phones.clear();
          perSourceState[k].outOfCredits = false;
        }
        return;
      }

      if (cmd.action === "RUN_SERVICE") {
        executeServiceAction(cmd.service, cmd.mode || "email");
        return;
      }

      if (cmd.action === "SCAN_DOM_ALL") {
        for (const k of ["contactout", "kendo", "apollo", "snov", "lusha", "signalhire"]) {
          scanDomForSource(k);
          if (perSourceState[k].emails.size > 0 || perSourceState[k].phones.size > 0) {
            emitSourceUpdate(k, false);
          }
        }
      }
    } catch (_) {}
  });

  // 6. Tự động đọc động số dư Credit từ UI/DOM của Extension mỗi 3.5s
  setInterval(() => {
    try {
      const frameSvc = detectServiceFromUrl(window.location.href);
      if (frameSvc) {
        scanDomCreditsForSource(frameSvc);
      } else if (window.location.href.includes("linkedin.com/")) {
        for (const k of ["contactout", "kendo", "apollo", "snov", "lusha", "signalhire"]) {
          scanDomCreditsForSource(k);
        }
      }
    } catch (_) {}
  }, 3500);
})();
