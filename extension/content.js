(() => {
  "use strict";

  // Change-prone BOSS selectors are intentionally centralized here.
  const SELECTORS = Object.freeze({
    cards: [
      ".job-card-wrapper",
      ".job-list-box .job-card-box",
      ".search-job-result li.job-card-box",
      ".job-card-box",
      "[class*='job-card-wrapper']"
    ],
    title: [".job-name", ".job-title", "[class*='job-name']"],
    company: [
      ".company-name", ".company-name a", ".company-info .name",
      ".company-info h3", ".company-text .name", ".job-card-footer [class*='company']",
      "[class*='company-name']"
    ],
    companyLogo: [".company-logo img", "[class*='company-logo'] img"],
    location: [
      ".job-area", ".job-address", ".job-location", ".job-area-wrapper",
      ".job-card-footer .job-area", ".job-card-footer [class*='location']",
      "[class*='job-area']", "[class*='location']"
    ],
    salary: [".salary", ".job-salary", "[class*='salary']"],
    link: ["a[href*='/job_detail/']", "a.job-card-left"],
    jd: [
      ".job-sec-text",
      ".job-detail-section .job-sec-text",
      ".job-detail-body",
      "[class*='job-description']"
    ],
    activeCard: [
      ".job-card-wrapper.active",
      ".job-card-box.active",
      ".job-card-wrapper.selected",
      ".job-card-box.selected",
      ".job-card-wrapper:has([class*='active'])"
    ],
    detailTitle: [
      ".job-detail-header .job-name", ".job-banner .name h1",
      ".job-primary .name h1", ".job-detail-box .job-name"
    ],
    detailCompany: [
      ".job-detail-company .company-name", ".job-company .company-name",
      ".sider-company .company-name", ".company-sider .company-name",
      ".company-info-box .company-name", ".company-info .company-name",
      ".boss-info-attr .name"
    ],
    detailLocation: [
      ".job-detail-header .job-area", ".job-detail-header .location",
      ".job-primary .job-address", ".job-banner .job-address"
    ],
    detailSalary: [
      ".job-detail-header .salary", ".job-banner .salary",
      ".job-primary .salary"
    ]
  });

  const clean = (value) => {
    const normalized = String(value || "").replace(/\s+/g, " ").trim();
    return normalized || null;
  };

  const firstNode = (scope, selectors) => {
    for (const selector of selectors) {
      try {
        const node = scope.querySelector(selector);
        if (node) return node;
      } catch (_) {
        // A changed selector must not stop other fallbacks.
      }
    }
    return null;
  };

  const nodeVisibleText = (node) => {
    if (!node) return null;
    const value = typeof node.innerText === "string" ? node.innerText : node.textContent;
    return clean(value);
  };

  const firstText = (scope, selectors) => nodeVisibleText(firstNode(scope, selectors));

  const cleanJobDescription = (node) => {
    if (!node) return null;
    const source = typeof node.innerText === "string" ? node.innerText : node.textContent;
    if (!source) return null;
    const chromeLabels = /^(举报|微信扫码分享|不合适|职位描述)$/;
    const cssArtifact = /(display\s*:\s*none|visibility\s*:\s*hidden|font-style\s*:|font-weight\s*:|!important|\{\s*(?:display|font|width|height)\s*:)/i;
    const lines = String(source)
      .replace(/^(?:(?:举报|微信扫码分享|不合适|职位描述)\s*)+/u, "")
      .split(/\r?\n/)
      .map(clean)
      .filter((line) => line && !chromeLabels.test(line) && !cssArtifact.test(line));
    return lines.join("\n") || null;
  };

  const firstJobDescription = (scope) => cleanJobDescription(firstNode(scope, SELECTORS.jd));

  const firstAttribute = (scope, selectors, names) => {
    const node = firstNode(scope, selectors);
    if (!node) return null;
    for (const name of names) {
      const value = clean(node.getAttribute?.(name));
      if (value) return value;
    }
    return null;
  };

  const rawLines = (scope) => String(scope?.innerText || scope?.textContent || "")
    .split(/\r?\n/)
    .map(clean)
    .filter(Boolean);

  const containsProtectedGlyphs = (value) => /[\uE000-\uF8FF\uFFFD□]/u.test(value || "");

  const fallbackSalary = (lines) => {
    const salaryPattern = /(面议|\d+(?:\.\d+)?\s*[-–—~至]\s*\d+(?:\.\d+)?\s*(?:K|k|万|元\s*\/\s*天|元\s*\/\s*月)(?:\s*[·・]\s*\d+薪)?)/;
    for (const line of lines) {
      const match = line.match(salaryPattern);
      if (match && !containsProtectedGlyphs(match[1])) return clean(match[1]);
    }
    return null;
  };

  const safeSalary = (scope, selectors, lines = rawLines(scope)) => {
    const fromAttribute = firstAttribute(scope, selectors, ["data-salary", "aria-label", "title"]);
    const value = fromAttribute || firstText(scope, selectors) || fallbackSalary(lines);
    return containsProtectedGlyphs(value) ? null : value;
  };

  const fallbackLocation = (lines) => {
    const location = /(北京|上海|广州|深圳|杭州|南京|苏州|成都|重庆|武汉|西安|天津|长沙|郑州|厦门|佛山|东莞|珠海|合肥|青岛|济南|宁波|无锡)(?:[·・][\u4e00-\u9fa5A-Za-z0-9]+){0,3}/;
    for (const line of [...lines].reverse()) {
      const matches = [...line.matchAll(new RegExp(location.source, "g"))];
      if (matches.length) return clean(matches[matches.length - 1][0]);
    }
    return null;
  };

  const fallbackCompany = (lines, title, location, salary) => {
    const ignored = /(在校|应届|经验|学历|本科|硕士|博士|天\/周|个月|年|面议|K|薪)/i;
    const looksLikeLocation = (value) => /^(北京|上海|广州|深圳|杭州|南京|苏州|成都|重庆|武汉|西安|天津|长沙|郑州|厦门|佛山|东莞|珠海|合肥|青岛|济南|宁波|无锡)(?:[·・].+)?$/.test(value || "");
    if (location) {
      const combined = [...lines].reverse().find((line) => line.includes(location) && line !== location);
      const prefix = clean(combined?.replace(location, ""));
      if (prefix && prefix !== title && prefix !== salary && !looksLikeLocation(prefix) && !ignored.test(prefix) && prefix.length <= 40) {
        return prefix;
      }
    }
    const locationIndex = location ? lines.lastIndexOf(location) : -1;
    const candidates = locationIndex > 0 ? lines.slice(0, locationIndex).reverse() : [...lines].reverse();
    return candidates.find((line) => (
      line !== title && line !== salary && !looksLikeLocation(line) && !ignored.test(line) && line.length <= 40
    )) || null;
  };

  const safeBossUrl = (value, baseUrl) => {
    try {
      const url = new URL(value || "", baseUrl);
      if (url.protocol !== "https:" || !url.hostname.endsWith("zhipin.com")) return null;
      return url.href;
    } catch (_) {
      return null;
    }
  };

  const findCards = (doc) => {
    for (const selector of SELECTORS.cards) {
      try {
        const cards = Array.from(doc.querySelectorAll(selector));
        if (cards.length) return cards;
      } catch (_) {
        // Continue through the selector fallback list.
      }
    }
    return [];
  };

  const cardData = (card, baseUrl) => {
    const lines = rawLines(card);
    const jobTitle = firstText(card, SELECTORS.title) || lines[0] || null;
    const location = firstText(card, SELECTORS.location) || fallbackLocation(lines);
    const salary = safeSalary(card, SELECTORS.salary, lines);
    const company = firstText(card, SELECTORS.company)
      || firstAttribute(card, SELECTORS.companyLogo, ["alt", "title"])
      || fallbackCompany(lines, jobTitle, location, salary);
    return {
      company,
      job_title: jobTitle,
      location,
      salary,
      source: "boss",
      source_url: safeBossUrl(firstNode(card, SELECTORS.link)?.getAttribute("href"), baseUrl),
      jd_text: firstJobDescription(card)
    };
  };

  const canonicalUrl = (value) => {
    if (!value) return null;
    try {
      const parsed = new URL(value, "https://www.zhipin.com/");
      if (parsed.hostname === "zhipin.com" || parsed.hostname.endsWith(".zhipin.com")) {
        parsed.hostname = "www.zhipin.com";
      }
      parsed.search = "";
      parsed.hash = "";
      if (parsed.pathname !== "/") parsed.pathname = parsed.pathname.replace(/\/+$/, "");
      return parsed.toString();
    } catch (_) { return value; }
  };

  const identity = (job) => {
    if (job.source_url) return `url:${canonicalUrl(job.source_url).toLowerCase()}`;
    return `name:${String(job.company || "").toLowerCase()}|${String(job.job_title || "").toLowerCase()}`;
  };

  const deduplicate = (jobs) => {
    const seen = new Set();
    const output = [];
    for (const job of jobs) {
      const key = identity(job);
      if (seen.has(key)) continue;
      seen.add(key);
      output.push(job);
      if (output.length === 20) break;
    }
    return output;
  };

  const extractBossPage = (doc, pageUrl) => {
    const baseUrl = pageUrl || doc.location?.href || "https://www.zhipin.com/";
    const cardNodes = findCards(doc).slice(0, 20);
    const cards = cardNodes.map((card) => cardData(card, baseUrl));
    const detailTitle = firstText(doc, SELECTORS.detailTitle);
    let active = firstNode(doc, SELECTORS.activeCard);
    if (!active && detailTitle) {
      active = cardNodes.find((card) => {
        const cardTitle = firstText(card, SELECTORS.title);
        return cardTitle && (cardTitle === detailTitle || detailTitle.includes(cardTitle));
      }) || null;
    }
    const detailJd = firstJobDescription(doc);
    const detailPage = String(baseUrl).includes("/job_detail/");
    const current = active ? cardData(active, baseUrl) : (detailPage ? cardData(doc, baseUrl) : null);
    if (current && !current.source_url && detailPage) {
      current.source_url = safeBossUrl(baseUrl, baseUrl);
    }
    if (current && detailJd) current.jd_text = detailJd;
    if (current) {
      current.job_title = detailTitle || current.job_title;
      current.company = firstText(doc, SELECTORS.detailCompany) || current.company;
      current.location = firstText(doc, SELECTORS.detailLocation) || current.location;
      current.salary = safeSalary(doc, SELECTORS.detailSalary) || current.salary;
    }

    if (current?.jd_text) {
      for (const card of cards) {
        if (identity(card) === identity(current)) card.jd_text = current.jd_text;
      }
    }

    const candidates = current?.jd_text ? [current, ...cards] : cards;
    const complete = [];
    const failures = [];
    candidates.forEach((job, index) => {
      if (!job.source_url || !job.jd_text) {
        failures.push({ index: index + 1, reason: !job.source_url ? "missing_url" : "missing_jd" });
        return;
      }
      complete.push(job);
    });
    return { jobs: deduplicate(complete), failures };
  };

  const api = Object.freeze({ SELECTORS, clean, safeBossUrl, deduplicate, extractBossPage });
  globalThis.JobPilotBossExtractor = api;

  let captureEnabled = false;
  let captureTimer = null;
  let lastCaptureIdentity = null;
  let lastStableSignature = null;
  let stableChecks = 0;
  let heartbeatTimer = null;
  let captureStartedAt = null;
  let captureAttempts = 0;

  // Reloading an unpacked MV3 extension invalidates content scripts that are
  // already running in open tabs. Guard runtime messaging so those stale
  // scripts stop quietly instead of creating recurring Chrome extension errors.
  const sendRuntimeMessage = (message, callback = () => {}) => {
    try {
      if (!chrome.runtime?.id) return false;
      chrome.runtime.sendMessage(message, (response) => {
        if (chrome.runtime.lastError) return;
        callback(response);
      });
      return true;
    } catch (_) {
      return false;
    }
  };

  const captureBadge = () => {
    let badge = document.getElementById("jobpilot-capture-badge");
    if (!badge) {
      badge = document.createElement("div");
      badge.id = "jobpilot-capture-badge";
      Object.assign(badge.style, {
        position: "fixed", right: "18px", bottom: "18px", zIndex: "2147483647",
        padding: "8px 11px", borderRadius: "7px", background: "#172033",
        color: "#fff", font: "12px/1.45 system-ui,sans-serif", boxShadow: "0 2px 10px rgba(0,0,0,.15)"
      });
      document.documentElement.appendChild(badge);
    }
    return badge;
  };

  const updateCaptureBadge = (count = 0) => {
    const badge = captureBadge();
    badge.style.display = captureEnabled ? "block" : "none";
    badge.textContent = `JobPilot ● 采集中 · 已读取 ${count} 个岗位`;
  };

  const currentSignature = () => {
    const extracted = extractBossPage(document, location.href);
    const job = extracted.jobs[0];
    if (!job?.jd_text || job.jd_text.length < 40 || !job.source_url) return null;
    return { job, identity: identity(job), signature: `${identity(job)}:${job.jd_text.length}` };
  };

  const reportCaptureState = (status, reason = null) => sendRuntimeMessage({
    type: "JOBPILOT_CAPTURE_STATUS", status, reason
  });

  const tryContinuousCapture = () => {
    captureTimer = null;
    if (!captureEnabled) return;
    let current = null;
    try { current = currentSignature(); } catch (_) {
      reportCaptureState("capture_failed", "extraction_error");
    }
    if (!current) {
      captureAttempts += 1;
      reportCaptureState("capture_pending", "detail_not_ready");
      if (captureAttempts < 20) captureTimer = setTimeout(tryContinuousCapture, 300);
      else reportCaptureState("capture_failed", "detail_timeout");
      return;
    }
    if (current.signature !== lastStableSignature) {
      lastStableSignature = current.signature;
      stableChecks = 1;
      reportCaptureState("capture_pending", "stabilizing");
      captureTimer = setTimeout(tryContinuousCapture, 300);
      return;
    }
    stableChecks += 1;
    if (stableChecks < 2 || current.identity === lastCaptureIdentity) return;
    lastCaptureIdentity = current.identity;
    current.job.source_url = canonicalUrl(current.job.source_url);
    current.job.canonical_job_key = current.identity;
    current.job.capture_event_id = crypto.randomUUID();
    current.job.discovered_at = new Date().toISOString();
    sendRuntimeMessage({ type: "JOBPILOT_CAPTURED_JOBS", jobs: [current.job] }, (response) => {
      updateCaptureBadge(response?.jobs?.length || 0);
      reportCaptureState(response?.ok ? "captured" : "capture_failed", response?.ok ? null : "storage_error");
    });
  };

  const scheduleCapture = () => {
    if (!captureEnabled || captureTimer) return;
    captureTimer = setTimeout(tryContinuousCapture, 250);
  };

  if (typeof MutationObserver !== "undefined" && typeof chrome !== "undefined" && chrome.storage?.local) {
    const captureObserver = new MutationObserver(scheduleCapture);
    captureObserver.observe(document.documentElement, { childList: true, subtree: true, characterData: true });
    chrome.storage.local.get({ jobpilot_capture_state: { enabled: false, count: 0 } }, (stored) => {
      captureEnabled = Boolean(stored.jobpilot_capture_state?.enabled);
      updateCaptureBadge(stored.jobpilot_capture_state?.count || 0);
      scheduleCapture();
    });
    heartbeatTimer = setInterval(() => {
      if (sendRuntimeMessage({ type: "JOBPILOT_BRIDGE_TICK" })) return;
      clearInterval(heartbeatTimer);
      heartbeatTimer = null;
    }, 4000);
  }

  if (typeof chrome !== "undefined" && chrome.runtime?.onMessage) {
    chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
      if (message?.type === "JOBPILOT_CAPTURE_START") {
        captureEnabled = true;
        lastStableSignature = null;
        stableChecks = 0;
        captureAttempts = 0;
        captureStartedAt = new Date().toISOString();
        updateCaptureBadge(message.count || 0);
        scheduleCapture();
        sendResponse({ ok: true });
        return false;
      }
      if (message?.type === "JOBPILOT_CAPTURE_PAUSE") {
        captureEnabled = false;
        if (captureTimer) clearTimeout(captureTimer);
        captureTimer = null;
        updateCaptureBadge(message.count || 0);
        sendResponse({ ok: true });
        return false;
      }
      if (message?.type === "JOBPILOT_CAPTURE_CLEAR") {
        lastCaptureIdentity = null;
        lastStableSignature = null;
        stableChecks = 0;
        updateCaptureBadge(0);
        sendResponse({ ok: true });
        return false;
      }
      if (message?.type !== "JOBPILOT_EXTRACT_BOSS") return false;
      try {
        sendResponse({ ok: true, ...extractBossPage(document, location.href) });
      } catch (error) {
        sendResponse({ ok: false, error_type: error?.name || "ExtractionError" });
      }
      return false;
    });
  }
})();
