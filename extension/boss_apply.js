(() => {
  "use strict";

  // BOSS contact selectors are centralized because the site DOM may change.
  const CONTACT_SELECTORS = Object.freeze({
    actionButtons: [
      ".job-detail-header .btn-startchat",
      ".job-banner .btn-startchat",
      ".job-op .btn-startchat",
      "button",
      "a"
    ],
    dialogs: [
      ".boss-dialog",
      ".dialog-wrap",
      ".dialog-container",
      "[role='dialog']"
    ],
    extraFields: ["input", "textarea", "select", "input[type='file']"]
    ,conversationStates: [
      ".job-detail-header .btn-startchat",
      ".job-banner .btn-startchat",
      ".job-op .btn-startchat",
      "button",
      "a"
    ]
  });

  const visible = (node) => {
    if (!node) return false;
    const style = globalThis.getComputedStyle ? globalThis.getComputedStyle(node) : null;
    if (style && (style.display === "none" || style.visibility === "hidden")) return false;
    return node.getClientRects ? node.getClientRects().length > 0 : true;
  };

  const text = (node) => String(node?.innerText || node?.textContent || "")
    .replace(/\s+/g, " ").trim();
  const normalized = (value) => String(value || "").replace(/\s+/g, "").trim();
  const pageText = (doc) => text(doc.body || doc.documentElement);

  const findVisible = (doc, selectors, predicate = () => true) => {
    for (const selector of selectors) {
      let nodes = [];
      try { nodes = Array.from(doc.querySelectorAll(selector)); } catch (_) { continue; }
      const match = nodes.find((node) => visible(node) && predicate(node));
      if (match) return match;
    }
    return null;
  };

  const hasExtraForm = (doc) => {
    const dialog = findVisible(doc, CONTACT_SELECTORS.dialogs);
    if (!dialog) return false;
    return CONTACT_SELECTORS.extraFields.some((selector) => {
      try { return Array.from(dialog.querySelectorAll(selector)).some(visible); }
      catch (_) { return false; }
    });
  };

  const contactButton = (doc) => findVisible(
    doc,
    CONTACT_SELECTORS.actionButtons,
    (node) => /^立即沟通$/.test(text(node))
  );

  const matchesExpectedJob = (doc, expectedJob = {}) => {
    const expectedTitle = normalized(expectedJob.job_title);
    if (!expectedTitle) return true;
    return normalized(pageText(doc)).includes(expectedTitle);
  };

  const evidence = (doc, expectedJob = {}) => {
    const content = pageText(doc);
    const href = String(doc.location?.href || "");
    const continueButton = findVisible(
      doc,
      CONTACT_SELECTORS.conversationStates,
      (node) => /^(继续沟通|继续聊|发消息)$/.test(text(node))
    );
    const continueContact = Boolean(continueButton) || /(继续沟通|继续聊|发消息)/.test(content);
    const explicitSuccess = /(沟通成功|已沟通)/.test(content);
    const chatRoute = /\/web\/geek\/(chat|message)/i.test(href);
    const expected = [expectedJob.company, expectedJob.job_title]
      .map(normalized)
      .filter(Boolean);
    const conversationIdentityFound = expected.some((value) => normalized(content).includes(value));
    return {
      contact_success_detected: continueContact || explicitSuccess || chatRoute,
      conversation_found: continueContact || (chatRoute && conversationIdentityFound)
    };
  };

  const result = (status, message, extra = {}) => ({
    status,
    message,
    contact_button_clicked: false,
    contact_success_detected: false,
    conversation_found: false,
    ...extra
  });

  const inspectBossContactPage = (doc, afterAction = false, buttonClicked = false, expectedJob = {}) => {
    const content = pageText(doc);
    if (/(验证码|安全验证|完成验证|滑动验证|访问异常)/.test(content)) {
      return result("manual_required", "页面出现验证码或安全验证。", {
        contact_button_clicked: buttonClicked
      });
    }
    if (hasExtraForm(doc)) {
      return result("manual_required", "页面需要人工填写或确认额外信息。", {
        contact_button_clicked: buttonClicked
      });
    }
    if (/(职位已关闭|岗位已关闭|职位不存在|该职位已下线|页面不存在)/.test(content)) {
      return result("skipped", "岗位已关闭或链接失效。", {
        contact_button_clicked: buttonClicked
      });
    }

    const contactEvidence = evidence(doc, expectedJob);
    if (contactEvidence.conversation_found) {
      return result(
        afterAction ? "contacted" : "already_contacted",
        afterAction ? "页面已显示继续沟通，会话已建立。" : "页面显示该岗位已存在沟通会话。",
        { contact_button_clicked: buttonClicked, ...contactEvidence }
      );
    }
    if (afterAction && contactEvidence.contact_success_detected) {
      return result("manual_required", "页面提示沟通成功，但无法确认会话已建立。", {
        contact_button_clicked: buttonClicked,
        ...contactEvidence
      });
    }
    if (!contactButton(doc)) {
      return result("failed", "未找到可识别的“立即沟通”入口。", {
        contact_button_clicked: buttonClicked
      });
    }
    return result("ready", "页面已准备好发起确认过的初始沟通。", {
      contact_button_clicked: buttonClicked
    });
  };

  const wait = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

  const executeBossContact = async (doc, expectedJob = {}) => {
    if (!matchesExpectedJob(doc, expectedJob)) {
      return result("manual_required", "当前页面岗位与确认任务不一致。");
    }
    const before = inspectBossContactPage(doc, false, false, expectedJob);
    if (before.status !== "ready") return before;
    const button = contactButton(doc);
    if (!button) return result("failed", "沟通入口在执行前发生变化。");
    button.click();
    let after = null;
    for (let attempt = 0; attempt < 6; attempt += 1) {
      await wait(1000);
      after = inspectBossContactPage(doc, true, true, expectedJob);
      if (!["ready", "failed", "manual_required"].includes(after.status)) break;
      if (after.status === "manual_required" && !after.contact_success_detected) break;
    }
    if (after.status === "ready" || after.status === "failed") {
      return result("manual_required", "已点击“立即沟通”，但页面没有可靠的会话成功证据。", {
        contact_button_clicked: true
      });
    }
    return after;
  };

  globalThis.JobPilotBossContact = Object.freeze({
    CONTACT_SELECTORS,
    inspectBossContactPage,
    executeBossContact
  });

  if (typeof chrome !== "undefined" && chrome.runtime?.onMessage) {
    chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
      if (message?.type === "JOBPILOT_BOSS_ADAPTER_PING") {
        sendResponse({ ok: true, ready: true });
        return false;
      }
      if (message?.type === "JOBPILOT_INSPECT_BOSS_CONTACT") {
        sendResponse({
          ok: true,
          ...inspectBossContactPage(
            document,
            true,
            Boolean(message.button_clicked),
            message.job || {}
          )
        });
        return false;
      }
      if (message?.type !== "JOBPILOT_CONTACT_BOSS") return false;
      executeBossContact(document, message.job || {})
        .then((contactResult) => sendResponse({ ok: true, ...contactResult }))
        .catch((error) => sendResponse({
          ok: false,
          ...result(
            "failed",
            error?.name === "Error" ? "页面执行发生技术错误。" : "页面结构异常。"
          )
        }));
      return true;
    });
  }
})();
