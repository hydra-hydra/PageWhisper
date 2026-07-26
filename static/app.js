const $ = (s) => document.querySelector(s);
const fileInput = $("#file");
const pick = $("#pick");
const drop = $("#drop");
const fname = $("#fname");
const go = $("#go");
const status = $("#status");
const viewer = $("#viewer");
const toolbar = $("#toolbar");
const toolbarInfo = $("#toolbar-info");
const empty = $("#empty");

const progressCard = $("#progress-card");
const progressFill = $("#progress-fill");
const stageText = $("#stage-text");
const percentText = $("#percent-text");
const elapsedText = $("#elapsed-text");
const tokenCard = $("#token-card");
const tokenDetail = $("#token-detail");

let jobId = null;
let pollTimer = null;

// ---- saved settings ----
const SAVE_KEYS = ["api_key", "base_url", "model", "engine", "translate_refs", "keep_original", "smart_mode", "translate_mode"];
function loadSaved() {
  try {
    const saved = JSON.parse(localStorage.getItem("pw_settings") || "{}");
    for (const k of SAVE_KEYS) {
      const el = document.getElementById(k);
      if (!el) continue;
      if (el.type === "checkbox") el.checked = saved[k] != null ? !!saved[k] : (k === "keep_original" ? true : false);
      else if (saved[k] != null) el.value = saved[k];
    }
  } catch (e) {}
}
function saveSettings() {
  const obj = {};
  for (const k of SAVE_KEYS) {
    const el = document.getElementById(k);
    if (!el) continue;
    obj[k] = el.type === "checkbox" ? el.checked : el.value;
  }
  localStorage.setItem("pw_settings", JSON.stringify(obj));
}
loadSaved();
for (const k of SAVE_KEYS) {
  const el = document.getElementById(k);
  if (el) el.addEventListener("input", saveSettings);
  if (el && el.type === "checkbox") el.addEventListener("change", saveSettings);
}

// ---- key toggle ----
const keyInput = $("#api_key");
const toggleKey = $("#toggle-key");
toggleKey.onclick = () => {
  const show = keyInput.type === "password";
  keyInput.type = show ? "text" : "password";
  toggleKey.textContent = show ? "隐藏" : "显示";
};

// ---- file pick ----
pick.onclick = () => fileInput.click();
fileInput.onchange = update;
drop.ondragover = (e) => { e.preventDefault(); drop.classList.add("over"); };
drop.ondragleave = () => drop.classList.remove("over");
drop.ondrop = (e) => {
  e.preventDefault();
  drop.classList.remove("over");
  fileInput.files = e.dataTransfer.files;
  update();
};
function update() {
  const f = fileInput.files[0];
  fname.textContent = f ? f.name : "";
  go.disabled = !f;
}

function stopPoll() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
}

function fmtElapsed(s) {
  if (s < 60) return s.toFixed(0) + "秒";
  const m = Math.floor(s / 60);
  return m + "分" + Math.floor(s % 60) + "秒";
}

function fmtTokens(ti) {
  if (!ti || !ti.total_tokens) return "";
  const t = Number(ti.total_tokens).toLocaleString();
  return "Token 用量：" + t + "（prompt: " + Number(ti.prompt_tokens).toLocaleString() + ", completion: " + Number(ti.completion_tokens).toLocaleString() + "）";
}

// ---- translate ----
go.onclick = async () => {
  const f = fileInput.files[0];
  if (!f) return;

  stopPoll();
  const fd = new FormData();
  fd.append("file", f);
  fd.append("engine", $("#engine").value);
  fd.append("api_key", $("#api_key").value);
  fd.append("base_url", $("#base_url").value);
  fd.append("model", $("#model").value);
  fd.append("translate_refs", $("#translate_refs").checked);
  fd.append("keep_original", $("#keep_original").checked);
  fd.append("smart_mode", $("#smart_mode").checked);
  fd.append("translate_mode", $("#translate_mode").value || "pipeline");

  go.disabled = true;
  status.textContent = "";
  empty.hidden = true;
  tokenCard.hidden = true;

  progressCard.hidden = false;
  progressFill.style.width = "0%";
  stageText.textContent = "上传中...";
  percentText.textContent = "0%";
  elapsedText.textContent = "";

  try {
    const r = await fetch("/api/translate", { method: "POST", body: fd });
    const d = await r.json();
    if (d.error) {
      progressCard.hidden = true;
      status.textContent = "错误：" + d.error;
      go.disabled = false;
      return;
    }
    jobId = d.job_id;
    pollTimer = setInterval(pollStatus, 500);
  } catch (e) {
    progressCard.hidden = true;
    status.textContent = "请求失败：" + e.message;
    go.disabled = false;
  }
};

async function pollStatus() {
  if (!jobId) { stopPoll(); return; }
  try {
    const r = await fetch("/api/status/" + jobId);
    if (!r.ok) return;
    const j = await r.json();

    progressFill.style.width = j.percent + "%";
    stageText.textContent = j.stage || "";
    percentText.textContent = j.percent + "%";
    if (j.elapsed > 0) {
      elapsedText.textContent = "已耗时 " + fmtElapsed(j.elapsed);
    }

    if (j.status === "done") {
      stopPoll();
      progressCard.hidden = true;
      go.disabled = false;

      viewer.src = j.view_url;
      $("#dl-html").href = "/api/download/" + jobId;
      toolbar.hidden = false;

      const s = j.stats || {};
      toolbarInfo.textContent = "引擎：" + j.engine + " | " + (s.pages || "?") + " 页 " + (s.text_blocks || "?") + " 段 " + (s.figures || "?") + " 图";
      status.textContent = "完成，耗时 " + fmtElapsed(j.elapsed);

      if (j.token_info && j.token_info.total_tokens) {
        tokenDetail.textContent = fmtTokens(j.token_info);
        tokenCard.hidden = false;
      }
    } else if (j.status === "error") {
      stopPoll();
      progressCard.hidden = true;
      go.disabled = false;
      status.textContent = "错误：" + j.stage;
    }
  } catch (e) {}
}

// ---- toolbar ----
$("#print").onclick = () => {
  viewer.contentWindow.focus();
  viewer.contentWindow.print();
};

$("#dl-html").onclick = () => {
  if (!jobId) return;
  this.href = "/api/download/" + jobId;
};
