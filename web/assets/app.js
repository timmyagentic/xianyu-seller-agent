const state = {
  view: "overview",
};

const titles = {
  overview: ["总览", "本地运行状态与关键开关"],
  delivery: ["自动发货", "按商品配置发货内容"],
  relist: ["自动上架", "发货后的库存恢复与重新上架"],
  publish: ["发布商品", "通过卖家发布页创建新商品"],
  jobs: ["任务记录", "最近的平台动作与本地审计"],
};

document.querySelectorAll(".nav-item").forEach((button) => {
  button.addEventListener("click", () => setView(button.dataset.view));
});

document.getElementById("refreshBtn").addEventListener("click", refreshAll);
document.getElementById("deliveryForm").addEventListener("submit", submitDelivery);
document.getElementById("relistConfigForm").addEventListener("submit", submitRelistConfig);
document.getElementById("relistRunForm").addEventListener("submit", submitRelistRun);
document.getElementById("publishForm").addEventListener("submit", submitPublish);

refreshAll();

function setView(view) {
  state.view = view;
  document.querySelectorAll(".nav-item").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.view === view);
  });
  document.querySelectorAll(".view").forEach((section) => {
    section.classList.toggle("is-active", section.id === `view-${view}`);
  });
  document.getElementById("pageTitle").textContent = titles[view][0];
  document.getElementById("pageSubtitle").textContent = titles[view][1];
}

async function refreshAll() {
  const [summary, delivery, relist, jobs, items] = await Promise.all([
    getJson("/api/summary"),
    getJson("/api/delivery-configs"),
    getJson("/api/auto-relist"),
    getJson("/api/listing-jobs?limit=20"),
    getJson("/api/items"),
  ]);
  renderSummary(summary);
  renderDelivery(delivery.configs || []);
  renderRelist(relist.configs || []);
  renderJobs(jobs.jobs || []);
  renderItems(items.items || []);
}

async function submitDelivery(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const data = formData(form);
  data.enabled = Boolean(data.enabled);
  await postJson("/api/delivery-configs", data);
  form.reset();
  form.enabled.checked = true;
  await refreshAll();
  showNotice("发货配置已保存");
}

async function submitRelistConfig(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const data = formData(form);
  data.target_stock = Number(data.target_stock);
  data.enabled = Boolean(data.enabled);
  data.allow_playwright = Boolean(data.allow_playwright);
  await postJson("/api/auto-relist", data);
  await refreshAll();
  showNotice("自动上架配置已保存");
}

async function submitRelistRun(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const data = formData(form);
  data.target_stock = Number(data.target_stock);
  data.allow_playwright = Boolean(data.allow_playwright);
  data.confirm_real_relist = Boolean(data.confirm_real_relist);
  const result = await postJson("/api/relist", data);
  await refreshAll();
  showNotice(`重新上架结果：${result.result?.status || "unknown"}`, !result.success);
}

async function submitPublish(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const data = formData(form);
  data.stock = Number(data.stock);
  data.images = String(data.images || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  data.confirm_real_publish = Boolean(data.confirm_real_publish);
  const result = await postJson("/api/publish", data);
  await refreshAll();
  showNotice(result.success ? "商品发布成功" : `发布失败：${result.result?.failed_reason || result.failed_reason}`, !result.success);
}

function renderSummary(payload) {
  const counts = payload.counts || {};
  document.getElementById("metricDelivery").textContent = counts.delivery_configs ?? 0;
  document.getElementById("metricRelist").textContent = counts.auto_relist_configs ?? 0;
  document.getElementById("metricItems").textContent = counts.items ?? 0;
  document.getElementById("metricJobs").textContent = counts.listing_jobs ?? 0;

  const env = payload.env || {};
  const labels = {
    auto_reply_enabled: "自动回复",
    auto_delivery_enabled: "自动发货",
    auto_confirm_delivery_enabled: "确认发货",
    auto_relist_enabled: "自动上架",
    auto_relist_allow_playwright: "允许浏览器",
    auto_relist_confirm_playwright: "确认浏览器执行",
    cookies_present: "登录 Cookie",
  };
  document.getElementById("envList").innerHTML = Object.entries(labels)
    .map(([key, label]) => `<div class="switch-item"><span>${escapeHtml(label)}</span><strong>${env[key] ? "开启" : "关闭"}</strong></div>`)
    .join("");
}

function renderDelivery(configs) {
  renderTable("deliveryTable", ["ID", "商品", "名称", "类型", "启用", "内容"], configs.map((config) => [
    config.id,
    config.item_id,
    config.name,
    config.delivery_type,
    config.enabled ? "是" : "否",
    config.content_preview || "",
  ]));
}

function renderRelist(configs) {
  renderTable("relistConfigTable", ["ID", "商品", "库存", "标题", "浏览器", "启用"], configs.map((config) => [
    config.id,
    config.item_id,
    config.target_stock,
    config.expected_title,
    config.allow_playwright ? "是" : "否",
    config.enabled ? "是" : "否",
  ]));
}

function renderJobs(jobs) {
  renderTable("jobsTable", ["ID", "商品", "库存", "结果", "原因", "时间"], jobs.map((job) => [
    job.id,
    job.item_id,
    job.target_stock ?? "",
    job.result_status,
    job.failed_reason,
    job.created_at,
  ]));
}

function renderItems(items) {
  renderTable("itemsTable", ["商品", "标题", "状态", "库存"], items.map((item) => [
    item.item_id,
    item.title,
    item.status,
    item.stock ?? "",
  ]));
}

function renderTable(id, headers, rows) {
  const table = document.getElementById(id);
  const thead = `<thead><tr>${headers.map((header) => `<th>${escapeHtml(header)}</th>`).join("")}</tr></thead>`;
  const tbody = `<tbody>${rows.map((row) => `<tr>${row.map((cell) => `<td>${escapeHtml(String(cell ?? ""))}</td>`).join("")}</tr>`).join("")}</tbody>`;
  table.innerHTML = thead + tbody;
}

function formData(form) {
  const data = {};
  const formDataObject = new FormData(form);
  for (const [key, value] of formDataObject.entries()) {
    data[key] = value;
  }
  form.querySelectorAll('input[type="checkbox"]').forEach((input) => {
    data[input.name] = input.checked;
  });
  return data;
}

async function getJson(url) {
  const response = await fetch(url);
  return response.json();
}

async function postJson(url, data) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  const payload = await response.json();
  if (!response.ok && !payload.success) {
    return payload;
  }
  return payload;
}

function showNotice(message, error = false) {
  const notice = document.getElementById("notice");
  notice.textContent = message;
  notice.hidden = false;
  notice.classList.toggle("is-error", Boolean(error));
  window.setTimeout(() => {
    notice.hidden = true;
  }, 4500);
}

function escapeHtml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
