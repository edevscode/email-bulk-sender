const $ = (id) => document.getElementById(id);

function applyTheme(theme) {
  if (theme === "dark") document.body.setAttribute("data-theme", "dark");
  else document.body.removeAttribute("data-theme");
}

function formatScheduleStatus(schedule) {
  if (!schedule) return "";
  const status = schedule.status || "";
  const runAt = schedule.run_at || "";
  if (status === "scheduled") return `Scheduled for ${runAt}`;
  if (status === "running") return `Running (started at ${runAt})`;
  if (status === "cancelled") return "Cancelled";
  if (status === "done") return "Completed";
  if (status === "failed") return `Failed: ${schedule.error || ""}`;
  return status;
}

async function refreshSchedule() {
  try {
    const data = await api("/api/schedule");
    const schedule = data.schedule;
    $("scheduleStatus").textContent = formatScheduleStatus(schedule);

    if (!schedule || ["cancelled", "done", "failed"].includes(schedule.status)) {
      if (schedulePollTimer) {
        clearInterval(schedulePollTimer);
        schedulePollTimer = null;
      }
    }

    if (schedule && schedule.job_id) {
      if (schedule.status === "running" && !currentJobId) {
        // Start showing existing progress UI
        $("logArea").innerHTML = "";
        $("progressBar").style.width = "0%";
        setHidden($("sendProgress"), false);
        currentJobId = schedule.job_id;
        lastLogCount = 0;
        if (jobPollTimer) clearInterval(jobPollTimer);
        jobPollTimer = setInterval(pollJob, 800);
      }
    }
  } catch {
    // ignore
  }
}

async function createSchedule() {
  await saveConfig();
  const runAt = $("scheduleAt").value;
  if (!runAt) {
    alert("Please choose a datetime to schedule.");
    return;
  }

  // datetime-local returns local time without timezone. Server interprets it as local time.
  const res = await api("/api/schedule", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ run_at: runAt }),
  });

  $("scheduleStatus").textContent = formatScheduleStatus(res.schedule);
  if (schedulePollTimer) clearInterval(schedulePollTimer);
  schedulePollTimer = setInterval(refreshSchedule, 1000);
}

async function cancelSchedule() {
  const res = await api("/api/schedule/cancel", { method: "POST" });
  $("scheduleStatus").textContent = formatScheduleStatus(res.schedule);

  if (!res.schedule && schedulePollTimer) {
    clearInterval(schedulePollTimer);
    schedulePollTimer = null;
  }
}

function getStoredTheme() {
  return localStorage.getItem("bes_theme") || "light";
}

function setStoredTheme(theme) {
  localStorage.setItem("bes_theme", theme);
}

const DRAFT_KEY = "bes_draft_v1";
let hasLocalEdits = false;

function readDraft() {
  try {
    const raw = localStorage.getItem(DRAFT_KEY);
    if (!raw) return null;
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function writeDraft(draft) {
  try {
    localStorage.setItem(DRAFT_KEY, JSON.stringify(draft));
  } catch {
    // ignore
  }
}

function getCurrentDraft() {
  return {
    fromEmail: $("fromEmail")?.value || "",
    sendDelay: $("sendDelay")?.value || "3",
    maxEmails: $("maxEmails")?.value || "150",
    enableDedup: $("enableDedup")?.checked || false,
    isHtml: $("isHtml")?.checked || false,
    signature: $("signature")?.value || "",
    subject: $("subject")?.value || "",
    body: $("body")?.value || "",
    enablePersonalize: $("enablePersonalize")?.checked || false,
  };
}

function markDirtyAndSaveDraft() {
  hasLocalEdits = true;
  writeDraft(getCurrentDraft());
}

function restoreDraftIfAny() {
  const draft = readDraft();
  if (!draft) return;

  if ($("fromEmail") && !$("fromEmail").value) $("fromEmail").value = draft.fromEmail || "";
  if ($("sendDelay") && $("sendDelay").value === "3") {
    $("sendDelay").value = draft.sendDelay || "3";
    $("sendDelayValue").textContent = $("sendDelay").value;
  }
  if ($("maxEmails") && $("maxEmails").value === "150") $("maxEmails").value = draft.maxEmails || "150";
  if ($("enableDedup")) $("enableDedup").checked = !!draft.enableDedup;
  if ($("isHtml")) $("isHtml").checked = !!draft.isHtml;
  if ($("signature") && !$("signature").value) $("signature").value = draft.signature || "";
  if ($("subject") && !$("subject").value) $("subject").value = draft.subject || "";
  if ($("body") && !$("body").value) $("body").value = draft.body || "";
  if ($("enablePersonalize")) $("enablePersonalize").checked = !!draft.enablePersonalize;
}

async function api(url, options = {}) {
  const res = await fetch(url, {
    credentials: "include",
    ...options,
  });
  if (!res.ok) {
    let detail = "Request failed";
    try {
      const data = await res.json();
      detail = data.detail || JSON.stringify(data);
    } catch {
      detail = await res.text();
    }
    throw new Error(detail);
  }
  const ct = res.headers.get("content-type") || "";
  if (ct.includes("application/json")) return res.json();
  return res.text();
}

function setHidden(el, hidden) {
  el.classList.toggle("hidden", hidden);
}

function renderDataPreview(dfRows) {
  if (!dfRows || dfRows.length === 0) return "";
  const cols = Object.keys(dfRows[0]);
  let html = '<table class="table"><thead><tr>';
  for (const c of cols) html += `<th>${escapeHtml(c)}</th>`;
  html += "</tr></thead><tbody>";
  for (const r of dfRows) {
    html += "<tr>";
    for (const c of cols) html += `<td>${escapeHtml(String(r[c] ?? ""))}</td>`;
    html += "</tr>";
  }
  html += "</tbody></table>";
  return html;
}

function escapeHtml(s) {
  return s
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

let state = null;
let emailsAll = [];
let selectedSet = new Set();
let dfPreviewRows = [];
let currentJobId = null;
let jobPollTimer = null;
let schedulePollTimer = null;

function updateMetric() {
  $("selectedMetric").textContent = `${selectedSet.size}/${emailsAll.length}`;
}

function renderEmailsGrid() {
  const q = $("search").value.trim().toLowerCase();
  const filtered = q ? emailsAll.filter((e) => e.toLowerCase().includes(q)) : emailsAll;

  const grid = $("emailsGrid");
  grid.innerHTML = "";

  for (const email of filtered) {
    const id = `email_${btoa(email).replaceAll("=", "")}`;
    const div = document.createElement("div");
    div.className = "email-item";
    div.innerHTML = `
      <input type="checkbox" id="${id}" ${selectedSet.has(email) ? "checked" : ""} />
      <label for="${id}">${escapeHtml(email)}</label>
    `;

    const cb = div.querySelector("input");
    cb.addEventListener("change", async () => {
      const checked = cb.checked;
      if (checked) selectedSet.add(email);
      else selectedSet.delete(email);
      updateMetric();
      try {
        await api("/api/recipients/selection", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email, checked }),
        });
      } catch (e) {
        // revert
        if (checked) selectedSet.delete(email);
        else selectedSet.add(email);
        cb.checked = !checked;
        updateMetric();
        alert(e.message);
      }
    });

    grid.appendChild(div);
  }
}

async function saveConfig() {
  const fd = new FormData();
  fd.append("from_email", $("fromEmail").value);
  fd.append("app_password", $("appPassword").value);
  fd.append("send_delay", $("sendDelay").value);
  fd.append("max_emails", $("maxEmails").value);
  fd.append("enable_dedup", $("enableDedup").checked ? "true" : "false");
  fd.append("is_html", $("isHtml").checked ? "true" : "false");
  fd.append("signature", $("signature").value);
  fd.append("subject", $("subject").value);
  fd.append("body", $("body").value);
  fd.append("enable_personalize", $("enablePersonalize").checked ? "true" : "false");
  fd.append("email_column", $("emailColumn").value || "");

  await api("/api/config", { method: "POST", body: fd });
}

async function uploadExcel(file) {
  const fd = new FormData();
  fd.append("file", file);
  const data = await api("/api/upload/excel", { method: "POST", body: fd });

  $("excelStatus").textContent = `Loaded ${data.rows} rows`;

  const columns = data.columns || [];
  const detected = data.detected_email_column;

  if (!detected) {
    setHidden($("emailColumnBlock"), false);
    $("emailColumn").innerHTML = columns.map((c) => `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`).join("");
  } else {
    setHidden($("emailColumnBlock"), true);
  }

  if ((data.personalization_columns || []).length > 0) {
    setHidden($("personalizeBlock"), false);
    $("personalizeLabel").textContent = `Personalize greeting (found: ${(data.personalization_columns || []).join(", ")})`;
  } else {
    setHidden($("personalizeBlock"), true);
  }

  emailsAll = data.unique_emails || [];
  selectedSet = new Set(emailsAll);
  updateMetric();

  if (emailsAll.length > 0) {
    setHidden($("recipientSelection"), false);
    renderEmailsGrid();
  } else {
    setHidden($("recipientSelection"), true);
  }

  // fetch fresh state to populate preview table
  await refreshState();

  try {
    const p = await api("/api/recipients/preview5");
    const rows = p.rows || [];
    $("dataPreview").innerHTML = renderDataPreview(rows);
  } catch {
    $("dataPreview").innerHTML = "";
  }
}

async function setEmailColumn() {
  const col = $("emailColumn").value;
  const data = await api("/api/recipients/set-email-column", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email_column: col }),
  });

  emailsAll = data.unique_emails || [];
  selectedSet = new Set(emailsAll);
  updateMetric();

  setHidden($("recipientSelection"), false);
  setHidden($("emailColumnBlock"), true);
  renderEmailsGrid();
  await refreshState();

  try {
    const p = await api("/api/recipients/preview5");
    const rows = p.rows || [];
    $("dataPreview").innerHTML = renderDataPreview(rows);
  } catch {
    $("dataPreview").innerHTML = "";
  }
}

async function uploadAttachments(files) {
  await saveConfig();
  const fd = new FormData();
  for (const f of files) fd.append("files", f);
  const data = await api("/api/upload/attachments", { method: "POST", body: fd });
  $("attachmentsList").textContent = data.files && data.files.length ? `Attachments: ${data.files.join(", ")}` : "";
}

function renderPreviewSection(data) {
  const sec = $("previewSection");
  sec.innerHTML = "";

  const title = document.createElement("h2");
  title.className = "h2";
  title.textContent = `Preview: First ${data.items.length} of ${data.total_selected} Selected Recipients`;
  sec.appendChild(title);

  for (let i = 0; i < data.items.length; i++) {
    const it = data.items[i];
    const details = document.createElement("details");
    details.className = "expander";
    details.style.marginTop = "10px";
    details.innerHTML = `
      <summary>Email ${i + 1}: ${escapeHtml(it.to)}</summary>
      <div style="margin-top: 10px;">
        <div><strong>To:</strong> ${escapeHtml(it.to)}</div>
        <div><strong>Subject:</strong> ${escapeHtml(it.subject)}</div>
        <div style="margin-top: 8px;"><strong>Body:</strong></div>
        <pre style="white-space: pre-wrap; margin: 8px 0 0;">${escapeHtml(it.body)}</pre>
      </div>
    `;
    sec.appendChild(details);
  }

  if (data.attachments && data.attachments.length) {
    const p = document.createElement("div");
    p.style.marginTop = "12px";
    p.innerHTML = `<strong>Attachments:</strong> ${escapeHtml(data.attachments.join(", "))}`;
    sec.appendChild(p);
  }

  setHidden(sec, false);
}

function renderResults(results) {
  const sec = $("resultsSection");
  sec.innerHTML = "";

  const title = document.createElement("h2");
  title.className = "h2";
  title.textContent = "Send Results";
  sec.appendChild(title);

  const sent = results.filter((r) => r.status === "Sent").length;
  const failed = results.filter((r) => r.status === "Failed").length;
  const invalid = results.filter((r) => r.status === "Invalid Email").length;

  const metrics = document.createElement("div");
  metrics.className = "grid-3";
  metrics.style.marginTop = "10px";
  metrics.innerHTML = `
    <div class="metric"><div class="metric-label">Sent</div><div class="metric-value">${sent}</div></div>
    <div class="metric"><div class="metric-label">Failed</div><div class="metric-value">${failed}</div></div>
    <div class="metric"><div class="metric-label">Invalid</div><div class="metric-value">${invalid}</div></div>
  `;
  sec.appendChild(metrics);

  const tableWrap = document.createElement("div");
  tableWrap.className = "table-wrap";
  tableWrap.style.marginTop = "12px";

  let table = '<table class="table"><thead><tr><th>email</th><th>status</th><th>error_message</th></tr></thead><tbody>';
  for (const r of results) {
    table += `<tr><td>${escapeHtml(r.email)}</td><td>${escapeHtml(r.status)}</td><td>${escapeHtml(r.error_message || "")}</td></tr>`;
  }
  table += "</tbody></table>";
  tableWrap.innerHTML = table;
  sec.appendChild(tableWrap);

  const dl = document.createElement("a");
  dl.href = "/api/results/csv";
  dl.className = "btn";
  dl.style.display = "inline-block";
  dl.style.marginTop = "12px";
  dl.textContent = "Download Results (CSV)";
  sec.appendChild(dl);

  setHidden(sec, false);
}

function appendLogLine(level, message) {
  const area = $("logArea");
  const div = document.createElement("div");
  div.className = `log-line ${level || ""}`.trim();
  div.textContent = message;
  area.appendChild(div);
  area.scrollTop = area.scrollHeight;
}

async function startSend() {
  await saveConfig();

  setHidden($("previewSection"), true);
  setHidden($("resultsSection"), true);

  $("logArea").innerHTML = "";
  $("progressBar").style.width = "0%";
  setHidden($("sendProgress"), false);

  syncStopButton({ status: "running" });

  const data = await api("/api/send", { method: "POST" });
  currentJobId = data.job_id;

  if (jobPollTimer) clearInterval(jobPollTimer);
  jobPollTimer = setInterval(pollJob, 800);
}

function syncStopButton(job) {
  const btn = $("stopBtn");
  if (!btn) return;

  if (!job) {
    btn.textContent = "Stop";
    btn.disabled = true;
    return;
  }

  if (job.status === "running") {
    btn.textContent = "Stop";
    btn.disabled = false;
    return;
  }

  if (job.status === "done" && job.cancelled) {
    btn.textContent = "Continue";
    btn.disabled = false;
    return;
  }

  btn.textContent = "Stop";
  btn.disabled = true;
}

async function resumeSend() {
  await saveConfig();

  syncStopButton({ status: "running" });

  const data = await api("/api/send/resume", { method: "POST" });
  currentJobId = data.job_id;

  if (jobPollTimer) clearInterval(jobPollTimer);
  jobPollTimer = setInterval(pollJob, 800);
}

let lastLogCount = 0;
async function pollJob() {
  if (!currentJobId) return;

  const data = await api(`/api/jobs/${currentJobId}`);
  $("progressBar").style.width = `${Math.round((data.progress || 0) * 100)}%`;

  syncStopButton(data);

  const logs = data.logs || [];
  if (logs.length > lastLogCount) {
    for (let i = lastLogCount; i < logs.length; i++) {
      appendLogLine(logs[i].level, logs[i].message);
    }
    lastLogCount = logs.length;
  }

  if (data.status === "failed") {
    clearInterval(jobPollTimer);
    jobPollTimer = null;
    syncStopButton(data);
    alert(data.error || "Send failed");
    return;
  }

  if (data.status === "done" && data.results) {
    clearInterval(jobPollTimer);
    jobPollTimer = null;

    syncStopButton(data);

    await api(`/api/jobs/${currentJobId}/commit`, { method: "POST" });

    if (data.cancelled) {
      appendLogLine("warning", "Sending cancelled.");
    }

    renderResults(data.results);
  }
}

async function stopCurrentSend() {
  if (!currentJobId) return;
  try {
    await api(`/api/jobs/${currentJobId}/cancel`, { method: "POST" });
    syncStopButton({ status: "running" });
  } catch (e) {
    alert(e.message);
  }
}

async function refreshState() {
  state = await api("/api/state");

  if (!hasLocalEdits) {
    $("fromEmail").value = state.gmail.from_email || "";
  }
  $("sendDelay").value = state.settings.send_delay;
  $("sendDelayValue").textContent = state.settings.send_delay;
  $("maxEmails").value = state.settings.max_emails;
  $("enableDedup").checked = !!state.settings.enable_dedup;
  $("isHtml").checked = !!state.settings.is_html;
  if (!hasLocalEdits) {
    $("signature").value = state.settings.signature || "";
    $("subject").value = state.compose.subject || "";
    $("body").value = state.compose.body || "";
  }

  const recipients = state.recipients;
  if (recipients.loaded) {
    emailsAll = recipients.unique_emails || [];
    selectedSet = new Set(recipients.selected_emails || []);
    updateMetric();

    if (recipients.email_column) {
      setHidden($("emailColumnBlock"), true);
      setHidden($("recipientSelection"), false);
      renderEmailsGrid();
    } else {
      setHidden($("emailColumnBlock"), false);
      $("emailColumn").innerHTML = (recipients.columns || []).map((c) => `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`).join("");
    }

    if ((recipients.personalization_columns || []).length) {
      setHidden($("personalizeBlock"), false);
      $("personalizeLabel").textContent = `Personalize greeting (found: ${(recipients.personalization_columns || []).join(", ")})`;
      $("enablePersonalize").checked = !!recipients.enable_personalize;
    } else {
      setHidden($("personalizeBlock"), true);
    }

    // data preview: show first 5 rows in HTML
    if (state.recipients && state.recipients.loaded) {
      try {
        const p = await api("/api/recipients/preview5");
        const rows = p.rows || [];
        $("dataPreview").innerHTML = renderDataPreview(rows);
      } catch {
        $("dataPreview").innerHTML = "";
      }
    }
  }

  if (state.attachments.files && state.attachments.files.length) {
    $("attachmentsList").textContent = `Attachments: ${state.attachments.files.join(", ")}`;
  }

  if (state.schedule) {
    $("scheduleStatus").textContent = formatScheduleStatus(state.schedule);
    if (state.schedule.status === "scheduled" && !schedulePollTimer) {
      schedulePollTimer = setInterval(refreshSchedule, 1000);
    }
    if (["cancelled", "done", "failed"].includes(state.schedule.status) && schedulePollTimer) {
      clearInterval(schedulePollTimer);
      schedulePollTimer = null;
    }
  }

  if (state.last_send_results) {
    renderResults(state.last_send_results);
  }
}

async function preview() {
  await saveConfig();
  const data = await api("/api/preview", { method: "POST" });
  renderPreviewSection(data);
}

async function bulkSelect(action) {
  const data = await api("/api/recipients/bulk", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action }),
  });
  selectedSet = new Set(data.selected_emails || []);
  updateMetric();
  renderEmailsGrid();
}

window.addEventListener("DOMContentLoaded", async () => {
  const initialTheme = getStoredTheme();
  applyTheme(initialTheme);
  const dm = $("darkMode");
  if (dm) dm.checked = initialTheme === "dark";

  if (dm) {
    dm.addEventListener("change", () => {
      const theme = dm.checked ? "dark" : "light";
      setStoredTheme(theme);
      applyTheme(theme);
    });
  }

  $("sendDelay").addEventListener("input", () => {
    $("sendDelayValue").textContent = $("sendDelay").value;
    markDirtyAndSaveDraft();
  });

  restoreDraftIfAny();

  $("fromEmail").addEventListener("input", markDirtyAndSaveDraft);
  $("maxEmails").addEventListener("input", markDirtyAndSaveDraft);
  $("enableDedup").addEventListener("change", markDirtyAndSaveDraft);
  $("isHtml").addEventListener("change", markDirtyAndSaveDraft);
  $("signature").addEventListener("input", markDirtyAndSaveDraft);
  $("subject").addEventListener("input", markDirtyAndSaveDraft);
  $("body").addEventListener("input", markDirtyAndSaveDraft);
  $("enablePersonalize").addEventListener("change", markDirtyAndSaveDraft);

  $("saveConfig").addEventListener("click", async () => {
    try {
      await saveConfig();
    } catch (e) {
      alert(e.message);
    }
  });

  $("excel").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    try {
      await uploadExcel(file);
      setHidden($("recipientSelection"), false);
    } catch (err) {
      alert(err.message);
    }
  });

  $("setEmailColumn").addEventListener("click", async () => {
    try {
      await setEmailColumn();
    } catch (e) {
      alert(e.message);
    }
  });

  $("attachments").addEventListener("change", async (e) => {
    try {
      await uploadAttachments(e.target.files);
    } catch (err) {
      alert(err.message);
    }
  });

  $("search").addEventListener("input", () => {
    renderEmailsGrid();
  });

  $("selectAll").addEventListener("click", async () => {
    try {
      await bulkSelect("select_all");
    } catch (e) {
      alert(e.message);
    }
  });

  $("deselectAll").addEventListener("click", async () => {
    try {
      await bulkSelect("deselect_all");
    } catch (e) {
      alert(e.message);
    }
  });

  $("previewBtn").addEventListener("click", async () => {
    try {
      await preview();
    } catch (e) {
      alert(e.message);
    }
  });

  $("sendBtn").addEventListener("click", async () => {
    try {
      lastLogCount = 0;
      await startSend();
    } catch (e) {
      alert(e.message);
    }
  });

  $("stopBtn").addEventListener("click", async () => {
    if ($("stopBtn").textContent.trim().toLowerCase() === "continue") {
      try {
        lastLogCount = 0;
        $("stopBtn").textContent = "Stop";
        await resumeSend();
      } catch (e) {
        alert(e.message);
      }
      return;
    }

    await stopCurrentSend();
  });

  $("scheduleBtn").addEventListener("click", async () => {
    try {
      await createSchedule();
    } catch (e) {
      alert(e.message);
    }
  });

  $("cancelScheduleBtn").addEventListener("click", async () => {
    try {
      await cancelSchedule();
    } catch (e) {
      alert(e.message);
    }
  });

  await refreshState();

  // After first server sync, re-apply draft if user has already typed or draft exists.
  // This prevents late-arriving /api/state from wiping in-progress typing.
  restoreDraftIfAny();

  await refreshSchedule();
});
