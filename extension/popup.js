"use strict";

const ENDPOINT = "http://127.0.0.1:8765/v1/discovery";
const TOKEN_KEY = "jobpilot_bridge_token";
const statusNode = document.getElementById("status");
const tokenNode = document.getElementById("token");

const setStatus = (message) => { statusNode.textContent = message; };
const runtimeMessage = (message) => new Promise((resolve) => {
  chrome.runtime.sendMessage(message, (response) => {
    if (chrome.runtime.lastError) {
      resolve({ ok: false, message: "Extension background 暂时不可用。" });
      return;
    }
    resolve(response);
  });
});
const tabMessage = (tabId, message) => new Promise((resolve) => {
  if (!tabId) {
    resolve({ ok: false });
    return;
  }
  chrome.tabs.sendMessage(tabId, message, (response) => {
    if (chrome.runtime.lastError) {
      resolve({ ok: false });
      return;
    }
    resolve(response || { ok: true });
  });
});

chrome.storage.local.get({ [TOKEN_KEY]: "" }, (stored) => {
  tokenNode.value = stored[TOKEN_KEY];
});

tokenNode.addEventListener("change", async () => {
  const token = tokenNode.value.trim();
  if (!token) return;
  await chrome.storage.local.set({ [TOKEN_KEY]: token });
  await runtimeMessage({ type: "JOBPILOT_ENABLE_CONTACT_MONITOR" });
});

runtimeMessage({ type: "JOBPILOT_CHECK_BRIDGE" }).then((result) => {
  if (result?.message) setStatus(result.message);
  return runtimeMessage({ type: "JOBPILOT_GET_APPLY_STATE" });
}).then((result) => {
  if (result?.state?.message) setStatus(result.state.message);
});

chrome.storage.onChanged.addListener((changes, areaName) => {
  if (areaName === "local" && changes.jobpilot_apply_runtime_state?.newValue?.message) {
    setStatus(changes.jobpilot_apply_runtime_state.newValue.message);
  }
  if (areaName === "local" && changes.jobpilot_capture_state?.newValue) {
    const capture = changes.jobpilot_capture_state.newValue;
    if (capture.status === "capture_pending") setStatus("正在等待当前岗位详情稳定。");
    if (capture.status === "capture_failed") setStatus(`当前岗位采集失败（${capture.failure_reason || "页面未就绪"}）。`);
    if (capture.status === "captured") setStatus(`采集完成，当前批次已读取 ${capture.count || 0} 个岗位。`);
  }
});

document.getElementById("capture").addEventListener("click", async () => {
  const token = tokenNode.value.trim();
  if (token) {
    await chrome.storage.local.set({ [TOKEN_KEY]: token });
    await runtimeMessage({ type: "JOBPILOT_ENABLE_CONTACT_MONITOR" });
  }
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.url?.startsWith("https://www.zhipin.com/")) {
    setStatus("请先打开 BOSS 职位页面。");
    return;
  }
  try {
    const capture = await runtimeMessage({ type: "JOBPILOT_SET_CAPTURE", enabled: true });
    const page = await tabMessage(tab.id, { type: "JOBPILOT_CAPTURE_START", count: capture.state?.count || 0 });
    if (!page?.ok) throw new Error("ContentScriptUnavailable");
    setStatus(`连续采集已开启。已读取 ${capture.state?.count || 0} 个岗位。`);
  } catch (_) {
    setStatus("当前页面暂时无法读取，请刷新页面后重试。");
  }
});

document.getElementById("pause").addEventListener("click", async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const queued = await runtimeMessage({ type: "JOBPILOT_GET_JOBS" });
  await runtimeMessage({ type: "JOBPILOT_SET_CAPTURE", enabled: false });
  if (tab?.id) await tabMessage(tab.id, { type: "JOBPILOT_CAPTURE_PAUSE", count: queued.jobs?.length || 0 });
  setStatus(`采集已暂停。已保留 ${queued.jobs?.length || 0} 个岗位。`);
});

document.getElementById("clear").addEventListener("click", async () => {
  await runtimeMessage({ type: "JOBPILOT_CLEAR_JOBS" });
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (tab?.id) await tabMessage(tab.id, { type: "JOBPILOT_CAPTURE_CLEAR" });
  setStatus("已清空扩展中的岗位。");
});

document.getElementById("send").addEventListener("click", async () => {
  const token = tokenNode.value.trim();
  if (!token) {
    setStatus("请先填写 JobPilot 本地连接令牌。");
    return;
  }
  const queued = await runtimeMessage({ type: "JOBPILOT_GET_JOBS" });
  const jobs = Array.isArray(queued?.jobs) ? queued.jobs.slice(0, 20) : [];
  if (!jobs.length) {
    setStatus("尚未读取到包含完整 JD 的岗位。");
    return;
  }
  await chrome.storage.local.set({ [TOKEN_KEY]: token });
  await runtimeMessage({ type: "JOBPILOT_ENABLE_CONTACT_MONITOR" });
  let response;
  try {
    response = await fetch(ENDPOINT, {
      method: "POST",
      credentials: "omit",
      cache: "no-store",
      referrerPolicy: "no-referrer",
      headers: {
        "Content-Type": "application/json",
        "X-JobPilot-Bridge-Token": token
      },
      body: JSON.stringify({ site: "boss", jobs })
    });
  } catch (_) {
        setStatus("无法连接本地 JobPilot。请先在批量岗位筛选中启动本地扩展连接。");
    return;
  }
  if (response.status === 403) {
    const result = await response.json().catch(() => ({}));
    setStatus(result.status === "invalid_extension_origin"
      ? "Extension 来源未通过本地校验。"
      : "连接令牌已失效，JobPilot 可能已重启。请复制当前令牌。");
    return;
  }
  if (response.status === 422) {
    setStatus("岗位数据未通过校验。请重新读取当前岗位后再发送。");
    return;
  }
  if (!response.ok) {
    setStatus(`本地 JobPilot 暂时无法接收（HTTP ${response.status}）。`);
    return;
  }
  try {
    const result = await response.json();
    setStatus(`已连接，本地 JobPilot 已接收 ${result.job_count} 个岗位。后续岗位会自动同步。`);
  } catch (_) {
    setStatus("岗位已发送，但本地响应无法读取。请回到 JobPilot 检查接收状态。");
  }
});

document.getElementById("stop-apply").addEventListener("click", async () => {
  await runtimeMessage({ type: "JOBPILOT_STOP_CONTACT" });
  setStatus("已请求停止，不会获取新的沟通任务。请回到 JobPilot 检查状态。");
});
