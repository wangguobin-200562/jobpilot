"use strict";

const QUEUE_KEY = "jobpilot_discovered_jobs";
const TOKEN_KEY = "jobpilot_bridge_token";
const APPLY_STATE_KEY = "jobpilot_apply_runtime_state";
const APPLY_ALARM = "jobpilot_apply_next_step";
const HEARTBEAT_ALARM = "jobpilot_bridge_heartbeat";
const BRIDGE_URL_KEY = "jobpilot_bridge_url";
const BRIDGE_URL = "http://127.0.0.1:8765";
const APPLY_NEXT_ENDPOINT = "http://127.0.0.1:8765/v1/apply/tasks/next";
const APPLY_RESULT_ENDPOINT = "http://127.0.0.1:8765/v1/apply/results";
const APPLY_HEARTBEAT_ENDPOINT = "http://127.0.0.1:8765/v1/apply/heartbeat";
const DISCOVERY_ENDPOINT = "http://127.0.0.1:8765/v1/discovery";
const CAPTURE_STATE_KEY = "jobpilot_capture_state";

const connectionError = (error) => error?.name === "AbortError"
  ? { stage: "timeout", message: "连接 JobPilot 超时。" }
  : { stage: "bridge_unavailable", message: "Bridge 未启动或本地连接不可达。" };

const authError = (payload) => payload?.status === "invalid_extension_origin"
  ? { stage: "invalid_origin", message: "Extension 来源未通过本地校验。" }
  : { stage: "invalid_token", message: "连接令牌已失效，JobPilot 可能已重启。" };

const identity = (job) => job.source_url
  ? `url:${job.source_url}`
  : `name:${String(job.company || "").toLowerCase()}|${String(job.job_title || "").toLowerCase()}`;

const mergeJobs = (existing, incoming) => {
  const seen = new Set();
  const output = [];
  for (const job of [...existing, ...incoming]) {
    const key = identity(job);
    if (seen.has(key)) continue;
    seen.add(key);
    output.push(job);
    if (output.length === 20) break;
  }
  return output;
};

const getApplyState = async () => {
  const stored = await chrome.storage.local.get({
    [APPLY_STATE_KEY]: { running: false, auto_contact_enabled: true, stage: "idle", message: "尚未启动沟通任务。" }
  });
  return stored[APPLY_STATE_KEY];
};

const setApplyState = async (updates) => {
  const current = await getApplyState();
  const next = { ...current, ...updates, updated_at: new Date().toISOString() };
  await chrome.storage.local.set({ [APPLY_STATE_KEY]: next });
  return next;
};

const bridgeToken = async () => {
  const stored = await chrome.storage.local.get({ [TOKEN_KEY]: "" });
  return String(stored[TOKEN_KEY] || "").trim();
};

const bridgeRequest = async (url, token, options = {}) => {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 8000);
  try {
    return await fetch(url, {
      credentials: "omit",
      cache: "no-store",
      referrerPolicy: "no-referrer",
      signal: controller.signal,
      ...options,
      headers: {
        ...(options.body ? { "Content-Type": "application/json" } : {}),
        "X-JobPilot-Bridge-Token": token
      }
    });
  } finally {
    clearTimeout(timeout);
  }
};

const safeJson = async (response) => {
  try { return await response.json(); } catch (_) { return {}; }
};

const probeBridge = async ({ resumeTasks = false } = {}) => {
  const token = await bridgeToken();
  if (!token) {
    const message = "请先填写 JobPilot 本地连接令牌。";
    await setApplyState({ bridge_connected: false, stage: "waiting_for_token", message });
    return { ok: false, status: "waiting_for_token", message };
  }
  try {
    const response = await bridgeRequest(APPLY_HEARTBEAT_ENDPOINT, token, {
      method: "POST",
      body: JSON.stringify({ extension_connected: true, execution_id: null })
    });
    const payload = await safeJson(response);
    if (response.status === 403) {
      const failure = authError(payload);
      await setApplyState({ running: false, bridge_connected: false, ...failure });
      return { ok: false, status: failure.stage, message: failure.message };
    }
    if (!response.ok) {
      const message = `JobPilot Bridge 返回 HTTP ${response.status}。`;
      await setApplyState({ bridge_connected: false, stage: "bridge_error", message });
      return { ok: false, status: "bridge_error", message };
    }
    const state = await setApplyState({
      bridge_connected: true,
      stage: "connected",
      message: "● 已连接 JobPilot",
      execution_id: payload.execution_id || null,
      last_heartbeat_at: new Date().toISOString()
    });
    if (
      resumeTasks
      && state.auto_contact_enabled !== false
      && !state.running
      && (payload.pending || 0) > 0
    ) {
      await setApplyState({ running: true, stage: "connecting", message: "已恢复连接，正在获取已确认任务。" });
      return runOneApplyStep();
    }
    return { ok: true, status: "connected", payload, message: "● 已连接 JobPilot" };
  } catch (error) {
    const failure = connectionError(error);
    await setApplyState({ running: false, bridge_connected: false, ...failure });
    return { ok: false, status: failure.stage, message: failure.message };
  }
};

const ensureHeartbeatAlarm = async () => {
  await chrome.alarms.create(HEARTBEAT_ALARM, { periodInMinutes: 0.5 });
};

const syncDiscoveredJobs = async (jobs) => {
  const token = await bridgeToken();
  if (!token || !jobs.length) return { ok: false, status: "waiting_for_token" };
  try {
    const response = await bridgeRequest(DISCOVERY_ENDPOINT, token, {
      method: "POST",
      body: JSON.stringify({ site: "boss", jobs: jobs.slice(0, 20) })
    });
    return { ok: response.ok, status: response.status, payload: await safeJson(response) };
  } catch (_) {
    return { ok: false, status: "bridge_unavailable" };
  }
};

const scheduleNextStep = async (delayMs = 2500) => {
  const state = await getApplyState();
  if (!state.running) return;
  await chrome.alarms.create(APPLY_ALARM, { when: Date.now() + delayMs });
};

const waitForTab = (tabId, timeoutMs = 15000) => new Promise((resolve, reject) => {
  const timeout = setTimeout(() => {
    chrome.tabs.onUpdated.removeListener(listener);
    reject(new Error("PageLoadTimeout"));
  }, timeoutMs);
  const listener = (updatedId, changeInfo) => {
    if (updatedId !== tabId || changeInfo.status !== "complete") return;
    clearTimeout(timeout);
    chrome.tabs.onUpdated.removeListener(listener);
    resolve();
  };
  chrome.tabs.onUpdated.addListener(listener);
});

const waitForChildTab = (openerTabId, timeoutMs = 3500) => new Promise((resolve) => {
  const timeout = setTimeout(() => {
    chrome.tabs.onCreated.removeListener(listener);
    resolve(null);
  }, timeoutMs);
  const listener = (created) => {
    if (created.openerTabId !== openerTabId) return;
    clearTimeout(timeout);
    chrome.tabs.onCreated.removeListener(listener);
    resolve(created);
  };
  chrome.tabs.onCreated.addListener(listener);
});

const waitUntilComplete = async (tabId) => {
  const current = await chrome.tabs.get(tabId);
  if (current.status === "complete") return;
  await waitForTab(tabId);
};

const sleep = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

const pingBossAdapter = async (tabId) => {
  try {
    const response = await chrome.tabs.sendMessage(tabId, { type: "JOBPILOT_BOSS_ADAPTER_PING" });
    return Boolean(response?.ready);
  } catch (_) {
    return false;
  }
};

const ensureBossAdapterReady = async (tabId, maxRetries = 2) => {
  for (let attempt = 0; attempt <= maxRetries; attempt += 1) {
    if (await pingBossAdapter(tabId)) return true;
    try { await waitUntilComplete(tabId); } catch (_) { /* DOM readiness is checked below. */ }
    if (await pingBossAdapter(tabId)) return true;
    try {
      await chrome.scripting.executeScript({ target: { tabId }, files: ["boss_apply.js"] });
    } catch (_) {
      // A slow navigation can reject injection; the bounded retry handles it.
    }
    if (await pingBossAdapter(tabId)) return true;
    if (attempt < maxRetries) {
      try { await chrome.tabs.reload(tabId); } catch (_) { /* Retry will fail safely. */ }
      await sleep(800);
    }
  }
  return false;
};

const reconcileBossContact = async (tabId, task, buttonClicked) => {
  for (let attempt = 0; attempt < 4; attempt += 1) {
    await sleep(1500);
    if (!await ensureBossAdapterReady(tabId, 0)) continue;
    try {
      const checked = await chrome.tabs.sendMessage(tabId, {
        type: "JOBPILOT_INSPECT_BOSS_CONTACT",
        job: { company: task.company, job_title: task.job_title },
        button_clicked: buttonClicked
      });
      if (checked?.conversation_found && checked?.contact_success_detected) {
        return { ...checked, status: "contacted", contact_button_clicked: buttonClicked };
      }
      if (checked?.status === "manual_required" && !checked?.contact_success_detected) return checked;
    } catch (_) {
      // Same-tab navigation can temporarily replace the content script.
    }
  }
  return null;
};

const reportContactResult = async (token, taskId, result) => {
  const response = await bridgeRequest(APPLY_RESULT_ENDPOINT, token, {
    method: "POST",
    body: JSON.stringify({
      task_id: taskId,
      status: result.status,
      message: result.message,
      contact_button_clicked: Boolean(result.contact_button_clicked),
      contact_success_detected: Boolean(result.contact_success_detected),
      conversation_found: Boolean(result.conversation_found)
    })
  });
  if (!response.ok) throw new Error(`ResultReportHTTP${response.status}`);
};

const runSafeHandoff = async (token, task) => {
  await setApplyState({
    stage: "opening",
    message: "正在打开安全测试页面（不会执行沟通）。",
    task: { company: task.company, job_title: task.job_title }
  });
  const tab = await chrome.tabs.create({ url: task.source_url, active: true });
  await waitForTab(tab.id);
  await reportContactResult(token, task.task_id, {
    status: "skipped",
    message: "安全任务交接测试完成，未执行任何沟通。"
  });
  await setApplyState({ stage: "waiting", message: "安全任务已回报，等待下一任务。" });
};

const runBossContactTask = async (token, task) => {
  let tab = null;
  try {
    await setApplyState({ stage: "opening", message: "正在打开岗位页面。" });
    const state = await getApplyState();
    if (state.worker_tab_id) {
      try { tab = await chrome.tabs.update(state.worker_tab_id, { url: task.source_url, active: false }); }
      catch (_) { tab = null; }
    }
    if (!tab) tab = await chrome.tabs.create({ url: task.source_url, active: false });
    await setApplyState({ worker_tab_id: tab.id });
    if (!await ensureBossAdapterReady(tab.id, 2)) throw new Error("BossAdapterNotReady");
    await setApplyState({ stage: "executing", message: "正在发起已确认的初始沟通。" });
    const childPromise = waitForChildTab(tab.id);
    let result = null;
    try {
      result = await chrome.tabs.sendMessage(tab.id, {
        type: "JOBPILOT_CONTACT_BOSS",
        job: { company: task.company, job_title: task.job_title }
      });
    } catch (_) {
      // A successful click may navigate the same tab and close the message port.
      result = { ok: true, status: "manual_required", contact_button_clicked: true,
        message: "页面跳转后正在核对沟通状态。" };
    }
    const child = await childPromise;
    let verified = result;
    if (child?.id) {
      try {
        await waitUntilComplete(child.id);
        await ensureBossAdapterReady(child.id, 2);
        const childEvidence = await chrome.tabs.sendMessage(child.id, {
          type: "JOBPILOT_INSPECT_BOSS_CONTACT",
          job: { company: task.company, job_title: task.job_title },
          button_clicked: Boolean(result?.contact_button_clicked)
        });
        if (childEvidence?.conversation_found) {
          verified = {
            ...result,
            status: "contacted",
            contact_button_clicked: Boolean(result?.contact_button_clicked),
            contact_success_detected: true,
            conversation_found: true,
            message: "已建立沟通会话。"
          };
        }
      } finally {
        await chrome.tabs.remove(child.id);
      }
    }
    if (!["contacted", "already_contacted"].includes(verified?.status)) {
      const reconciled = await reconcileBossContact(
        tab.id,
        task,
        Boolean(verified?.contact_button_clicked)
      );
      if (reconciled?.conversation_found) verified = reconciled;
    }
    const safeResult = verified?.ok
      ? { status: verified.status, message: verified.message }
      : { status: "failed", message: "浏览器页面执行发生技术错误。" };
    const evidenceResult = {
      ...safeResult,
      contact_button_clicked: Boolean(verified?.contact_button_clicked),
      contact_success_detected: Boolean(verified?.contact_success_detected),
      conversation_found: Boolean(verified?.conversation_found)
    };
    await reportContactResult(token, task.task_id, evidenceResult);
    if (safeResult.status === "manual_required") {
      await setApplyState({ running: false, stage: "manual_required", message: safeResult.message });
    } else {
      await setApplyState({ stage: "waiting", message: "任务结果已回报，等待下一任务。" });
    }
    return safeResult.status;
  } catch (_) {
    try {
      await reportContactResult(token, task.task_id, {
        status: "failed",
        message: "浏览器扩展连接或页面加载失败。"
      });
    } catch (_) {
      // The server keeps the reserved task fail-safe; it is never reissued.
    }
    await setApplyState({ stage: "failed", message: "岗位处理失败，请回到 JobPilot 检查状态。" });
    return "failed";
  }
};

async function runOneApplyStep() {
  const state = await getApplyState();
  if (!state.running) return { ok: false, message: "沟通流程未启动。" };
  const token = await bridgeToken();
  if (!token) {
    await setApplyState({ running: false, stage: "invalid_token", message: "本地连接令牌为空。" });
    return { ok: false, message: "请先填写本地连接令牌。" };
  }

  if (["opening", "executing"].includes(state.stage) && state.task?.task_id) {
    try {
      await reportContactResult(token, state.task.task_id, {
        status: "manual_required",
        message: "Extension 执行过程被中断，请人工确认该岗位当前状态。"
      });
      await setApplyState({
        stage: "manual_required",
        message: "上次执行被中断，该岗位需要人工确认。"
      });
      await scheduleNextStep(5000);
      return { ok: true, message: "中断任务已转为人工确认。" };
    } catch (_) {
      await setApplyState({ running: false, stage: "bridge_unavailable", message: "JobPilot Bridge 不可用。" });
      return { ok: false, message: "JobPilot Bridge 不可用。" };
    }
  }

  try {
    await setApplyState({ stage: "connecting", message: "正在连接 JobPilot。" });
    const heartbeat = await bridgeRequest(APPLY_HEARTBEAT_ENDPOINT, token, {
      method: "POST",
      body: JSON.stringify({
        extension_connected: true,
        execution_id: null
      })
    });
    const heartbeatPayload = await safeJson(heartbeat);
    if (heartbeat.status === 403) {
      const failure = authError(heartbeatPayload);
      await setApplyState({ running: false, bridge_connected: false, ...failure });
      return { ok: false, message: failure.message };
    }
    if (!heartbeat.ok) throw new Error("HeartbeatFailed");
    await setApplyState({
      stage: "connected",
      message: heartbeatPayload.execution_id
        ? `已连接 · 沟通进度 ${heartbeatPayload.completed || 0} / ${(heartbeatPayload.pending || 0) + (heartbeatPayload.processing || 0) + (heartbeatPayload.completed || 0)}`
        : "已连接 JobPilot，等待已确认任务。",
      execution_id: heartbeatPayload.execution_id || null,
      bridge_connected: true,
      last_heartbeat_at: new Date().toISOString()
    });

    await setApplyState({ stage: "fetching", message: "正在获取下一任务。" });
    const response = await bridgeRequest(APPLY_NEXT_ENDPOINT, token, { method: "GET" });
    const payload = await safeJson(response);
    if (response.status === 403) {
      const failure = authError(payload);
      await setApplyState({ running: false, bridge_connected: false, ...failure });
      return { ok: false, message: failure.message };
    }
    if (response.status === 409) {
      const message = payload.status === "manual_required"
        ? "当前任务等待人工处理。"
        : "当前任务仍在处理中，请在 JobPilot 检查状态。";
      await setApplyState({ stage: payload.status, message });
      await scheduleNextStep(5000);
      return { ok: true, message };
    }
    if (!response.ok) throw new Error(`TaskFetchHTTP${response.status}`);
    if (payload.status === "no_pending_task" || !payload.task) {
      await setApplyState({ running: false, stage: "no_pending_task", message: "当前没有待执行任务。" });
      return { ok: true, message: "当前没有待执行任务。" };
    }

    const task = payload.task;
    await setApplyState({
      stage: "task_received",
      message: `已获取任务：${task.company} / ${task.job_title}`,
      task: {
        task_id: task.task_id,
        company: task.company,
        job_title: task.job_title,
        source_url: task.source_url,
        action: task.action
      }
    });
    await scheduleNextStep(35000);
    let outcome = null;
    if (task.action === "safe_handoff") {
      await runSafeHandoff(token, task);
      outcome = "skipped";
    }
    else if (task.action === "initiate_contact") outcome = await runBossContactTask(token, task);
    else {
      await reportContactResult(token, task.task_id, {
        status: "failed",
        message: "Extension 不支持该任务动作。"
      });
    }
    if (outcome !== "manual_required") await scheduleNextStep();
    return { ok: true, message: "已获取并处理一个任务。" };
  } catch (error) {
    const failure = connectionError(error);
    await setApplyState({ running: false, bridge_connected: false, ...failure });
    return { ok: false, message: failure.message };
  }
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.storage.local.set({
    [QUEUE_KEY]: [],
    [CAPTURE_STATE_KEY]: { enabled: false, count: 0 },
    [BRIDGE_URL_KEY]: BRIDGE_URL,
    [APPLY_STATE_KEY]: { running: false, bridge_connected: false, auto_contact_enabled: true, stage: "idle", message: "正在连接 JobPilot。" }
  }).then(() => ensureHeartbeatAlarm()).then(() => probeBridge({ resumeTasks: true }));
});

chrome.runtime.onStartup.addListener(() => {
  ensureHeartbeatAlarm().then(() => probeBridge({ resumeTasks: true }));
});

ensureHeartbeatAlarm().then(() => probeBridge({ resumeTasks: true }));

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === APPLY_ALARM) runOneApplyStep();
  if (alarm.name === HEARTBEAT_ALARM) probeBridge({ resumeTasks: true });
});

chrome.storage.onChanged.addListener((changes, areaName) => {
  if (areaName === "local" && changes[TOKEN_KEY]) probeBridge({ resumeTasks: true });
});

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type === "JOBPILOT_BRIDGE_TICK") {
    bridgeToken().then((token) => {
      if (!token) return { ok: false };
      return getApplyState().then((state) => {
        if (state.auto_contact_enabled === false || state.running || ["opening", "executing"].includes(state.stage)) return { ok: true };
        return setApplyState({ running: true, stage: "connecting", message: "正在检查已确认任务。" })
          .then(runOneApplyStep);
      });
    }).then(sendResponse).catch(() => sendResponse({ ok: false }));
    return true;
  }
  if (message?.type === "JOBPILOT_CAPTURED_JOBS") {
    chrome.storage.local.get({ [QUEUE_KEY]: [], [CAPTURE_STATE_KEY]: { enabled: true, count: 0 } }, async (stored) => {
      const incoming = Array.isArray(message.jobs) ? message.jobs.slice(0, 20) : [];
      const jobs = mergeJobs(stored[QUEUE_KEY], incoming);
      const captureState = { ...stored[CAPTURE_STATE_KEY], count: jobs.length };
      await chrome.storage.local.set({ [QUEUE_KEY]: jobs, [CAPTURE_STATE_KEY]: captureState });
      await syncDiscoveredJobs(jobs);
      sendResponse({ ok: true, jobs });
    });
    return true;
  }
  if (message?.type === "JOBPILOT_CAPTURE_STATE") {
    chrome.storage.local.get({ [CAPTURE_STATE_KEY]: { enabled: false, count: 0 } }, (stored) => sendResponse({ ok: true, state: stored[CAPTURE_STATE_KEY] }));
    return true;
  }
  if (message?.type === "JOBPILOT_SET_CAPTURE") {
    chrome.storage.local.get({ [CAPTURE_STATE_KEY]: { enabled: false, count: 0 } }, (stored) => {
      const state = { ...stored[CAPTURE_STATE_KEY], enabled: Boolean(message.enabled) };
      chrome.storage.local.set({ [CAPTURE_STATE_KEY]: state }, () => sendResponse({ ok: true, state }));
    });
    return true;
  }
  if (message?.type === "JOBPILOT_START_CONTACT") {
    setApplyState({
      running: true,
      stage: "starting",
      message: "正在启动任务领取流程。",
      execution_id: null,
      task: null
    })
      .then(runOneApplyStep)
      .then(sendResponse)
      .catch(() => sendResponse({ ok: false, message: "任务领取流程启动失败。" }));
    return true;
  }
  if (message?.type === "JOBPILOT_STOP_CONTACT") {
    chrome.alarms.clear(APPLY_ALARM);
    setApplyState({ running: false, auto_contact_enabled: false, stage: "stopped", message: "已停止获取新任务。" })
      .then(() => sendResponse({ ok: true }));
    return true;
  }
  if (message?.type === "JOBPILOT_GET_APPLY_STATE") {
    getApplyState().then((state) => sendResponse({ ok: true, state }));
    return true;
  }
  if (message?.type === "JOBPILOT_CHECK_BRIDGE") {
    probeBridge({ resumeTasks: true }).then(sendResponse).catch(() => sendResponse({ ok: false }));
    return true;
  }
  if (message?.type === "JOBPILOT_ENABLE_CONTACT_MONITOR") {
    setApplyState({ auto_contact_enabled: true, message: "正在连接 JobPilot。" })
      .then(() => probeBridge({ resumeTasks: true }))
      .then(sendResponse);
    return true;
  }
  if (!["JOBPILOT_ADD_JOBS", "JOBPILOT_GET_JOBS", "JOBPILOT_CLEAR_JOBS"].includes(message?.type)) {
    return false;
  }
  if (message.type === "JOBPILOT_CLEAR_JOBS") {
    chrome.storage.local.get({ [CAPTURE_STATE_KEY]: { enabled: false, count: 0 } }, (stored) => {
      const state = { ...stored[CAPTURE_STATE_KEY], count: 0 };
      chrome.storage.local.set({ [QUEUE_KEY]: [], [CAPTURE_STATE_KEY]: state }, () => sendResponse({ ok: true, jobs: [] }));
    });
    return true;
  }
  chrome.storage.local.get({ [QUEUE_KEY]: [] }, (stored) => {
    if (message.type === "JOBPILOT_GET_JOBS") {
      sendResponse({ ok: true, jobs: stored[QUEUE_KEY] });
      return;
    }
    const incoming = Array.isArray(message.jobs) ? message.jobs.slice(0, 20) : [];
    const jobs = mergeJobs(stored[QUEUE_KEY], incoming);
    chrome.storage.local.set({ [QUEUE_KEY]: jobs }, () => sendResponse({ ok: true, jobs }));
  });
  return true;
});
