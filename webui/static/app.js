/* ------------
   Dubbing web UI: renders workspace state, config and job progress.
   ------------ */

const byId = (id) => document.getElementById(id);

function el(tag, attrs, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key === "value") node.value = String(value);
    else if (key.startsWith("on")) node.addEventListener(key.slice(2).toLowerCase(), value);
    else node.setAttribute(key, value === true ? "" : String(value));
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child);
  }
  return node;
}

function replace(host, ...children) {
  host.replaceChildren(...children.flat().filter(Boolean));
}

async function api(path, options) {
  const res = await fetch(path, options);
  const text = await res.text();
  let data = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = null;
    }
  }
  if (!res.ok) throw new Error((data && data.detail) || res.statusText);
  return data;
}

const sendJSON = (path, method, body) =>
  api(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body === undefined ? {} : body),
  });

function dismissToast(node) {
  if (!node.isConnected || node.classList.contains("is-leaving")) return;
  node.classList.add("is-leaving");
  setTimeout(() => node.remove(), 200);
}

function toast(message, kind) {
  const node = el(
    "div",
    { class: kind === "error" ? "toast toast-error" : "toast" },
    el("span", { class: "toast-text", text: message }),
    el("button", {
      class: "toast-close",
      type: "button",
      "aria-label": "关闭提示",
      text: "×",
      onclick: () => dismissToast(node),
    })
  );
  byId("toasts").append(node);
  const life = kind === "error" ? 9000 : 4000;
  let timer = setTimeout(() => dismissToast(node), life);
  node.addEventListener("mouseenter", () => clearTimeout(timer));
  node.addEventListener("mouseleave", () => {
    timer = setTimeout(() => dismissToast(node), 1500);
  });
}

// ------------
// Modal dialog, replacing blocking prompt() and confirm()
// ------------

const modal = { node: null, resolve: null, submitted: false, wantsInput: false };

function setupModal() {
  modal.node = byId("modal");
  byId("modal-form").addEventListener("submit", () => {
    modal.submitted = true;
  });
  byId("modal-cancel").addEventListener("click", () => modal.node.close());
  modal.node.addEventListener("close", () => {
    const resolve = modal.resolve;
    const submitted = modal.submitted;
    modal.resolve = null;
    modal.submitted = false;
    if (!resolve) return;
    if (!submitted) return resolve(null);
    resolve(modal.wantsInput ? byId("modal-input").value.trim() || null : true);
  });
}

function askModal(options) {
  const note = options.note || "";
  const input = byId("modal-input");
  modal.wantsInput = options.input !== undefined;

  byId("modal-title").textContent = options.title;
  byId("modal-note").textContent = note;
  byId("modal-note").hidden = !note;
  input.hidden = !modal.wantsInput;
  input.required = modal.wantsInput;
  input.value = modal.wantsInput ? options.input : "";
  input.placeholder = options.placeholder || "";

  const confirmBtn = byId("modal-confirm");
  confirmBtn.textContent = options.confirmText || "确定";
  confirmBtn.className = options.danger ? "btn btn-danger" : "btn btn-primary";

  return new Promise((resolve) => {
    modal.resolve = resolve;
    modal.node.showModal();
    if (modal.wantsInput) input.select();
    else confirmBtn.focus();
  });
}

// ------------
// Async button feedback
// ------------

async function withBusy(button, run) {
  if (button.dataset.busy) return;
  button.dataset.busy = "1";
  button.disabled = true;
  try {
    return await run();
  } finally {
    delete button.dataset.busy;
    button.disabled = false;
  }
}

function skeletonCards(hostId, count) {
  const widths = ["40%", "72%", "56%"];
  replace(
    byId(hostId),
    Array.from({ length: count }, () =>
      el(
        "div",
        { class: "skeleton-card", "aria-hidden": "true" },
        widths.map((width) => el("div", { class: "skeleton-line", style: `width:${width}` }))
      )
    )
  );
}

// ------------
// Formatting
// ------------

function fmtBytes(bytes) {
  if (!bytes) return "—";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(value >= 100 || unit === 0 ? 0 : 1)} ${units[unit]}`;
}

function fmtSecs(seconds) {
  if (seconds === null || seconds === undefined) return "—";
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
}

function fmtClock(seconds) {
  if (seconds === null || seconds === undefined) return "—";
  const total = Math.round(seconds);
  return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
}

const shortTime = (value) => (value ? String(value).slice(0, 8) : "—");

// ------------
// State
// ------------

const state = {
  stages: [],
  config: null,
  workspace: null,
  job: null,
  speakers: null,
  tasks: null,
  alignment: null,
  loudness: null,
  loudnessBusy: false,
  lastJobKey: null,
  speakerDraft: null,
  speakerSelected: new Set(),
  taskSelected: new Set(),
  customSpeakers: [],
  transfers: {},
  savedKey: null,
  speakerUI: null,
  taskUI: null,
  candidateChoice: {},
  cueCaret: null,
  cueSplitting: null,
  usage: null,
  pendingKeepOriginal: [],
};

const cfg = (key) => (state.config ? state.config.values[key] : undefined);

function jobBusy() {
  return state.job && (state.job.state === "running" || state.job.state === "paused");
}

function renderMiniJob(hostId, names) {
  const host = byId(hostId);
  const job = state.job;
  if (!job || !names.includes(job.name) || job.state === "idle") {
    host.hidden = true;
    replace(host);
    return;
  }
  host.hidden = false;
  const controls = [];
  if (job.state === "running" || job.state === "paused") {
    controls.push(
      el("button", {
        class: "btn btn-ghost",
        text: job.state === "paused" ? "继续" : "暂停",
        onclick: () => control(job.state === "paused" ? "resume" : "pause"),
      }),
      el("button", { class: "btn btn-danger", text: "停止", onclick: () => control("stop") })
    );
  }
  const headings = {
    rebuild_speakers: "重建配音任务",
    regenerate: "批量重生成",
    candidate: "生成候选配音",
    remaster: "重新合片",
    dub: "生成配音",
  };
  const heading = headings[job.name] || "任务";
  replace(
    host,
    el("p", {
      class: "card-title",
      style: "margin-bottom:12px",
      text: job.state === "error" ? `${heading}失败` : `${heading}中`,
    }),
    el("div", { class: "progress" }, el("span", { style: `width:${Math.round(job.progress * 100)}%` })),
    el(
      "div",
      { class: "stage-steps", style: "margin-top:12px" },
      (job.steps || []).map((step, index) =>
        el(
          "div",
          { class: `stage-step ${step.status}` },
          el("span", { class: "idx", text: step.status === "done" ? "✓" : String(index + 1) }),
          el("span", { class: "label", text: step.label }),
          el("span", { class: "time", text: step.elapsed !== null ? fmtSecs(step.elapsed) : "" })
        )
      )
    ),
    job.error ? el("p", { class: "notice notice-error", style: "margin-top:12px", text: job.error }) : null,
    el("p", { class: "card-note", style: "margin-top:8px", text: `耗时 ${fmtSecs(job.elapsed)}` }),
    el("div", { class: "btn-row", style: "margin-top:12px" }, controls)
  );
}

// ------------
// Section 01: uploads
// ------------

const UPLOADS = [
  {
    id: "media",
    title: "原视频 / 音频",
    hint: "拖入或点击选择。上传新文件会替换掉工作区里的旧素材。",
    accept: "video/*,audio/*",
    url: "/api/upload/media",
    required: true,
  },
  {
    id: "trans",
    title: "译文字幕（可选）",
    hint: "有译文走导入模式；不上传则视频直入（Qwen 转写+翻译）。",
    accept: ".srt",
    url: "/api/upload/srt?kind=trans",
    removable: "/api/upload/srt?kind=trans",
  },
  {
    id: "src",
    title: "原文字幕",
    hint: "缺省时用译文镜像，只影响日志里的对照文本。",
    accept: ".srt",
    url: "/api/upload/srt?kind=src",
    removable: "/api/upload/srt?kind=src",
  },
];

function uploadSummary(card) {
  const ws = state.workspace;
  if (!ws) return null;
  if (card.id === "media") {
    if (!ws.media) return null;
    return {
      name: ws.media.name,
      meta: [
        ws.media.type === "video" ? "视频" : "音频",
        ws.media.duration ? fmtClock(ws.media.duration) : null,
        fmtBytes(ws.media.size),
      ],
    };
  }
  const upload = ws.uploads[card.id];
  if (!upload) return null;
  return {
    name: `${upload.cue_count} 条字幕`,
    meta: [upload.last_end ? `末条 ${shortTime(upload.last_end)}` : null],
  };
}

function uploadBody(card, summary) {
  const transfer = state.transfers[card.id];
  if (transfer) {
    const pct = Math.round(transfer.progress * 100);
    return el(
      "div",
      { class: "drop-progress" },
      el("p", { class: "drop-name", text: transfer.name }),
      el(
        "div",
        { class: "drop-progress-meta" },
        el("span", { id: `upload-state-${card.id}`, text: pct >= 100 ? "服务端处理中…" : "上传中" }),
        el("span", { id: `upload-pct-${card.id}`, text: `${pct}%` })
      ),
      el(
        "div",
        {
          class: "progress",
          id: `upload-track-${card.id}`,
          role: "progressbar",
          "aria-label": `${transfer.name} 上传进度`,
          "aria-valuemin": "0",
          "aria-valuemax": "100",
          "aria-valuenow": String(pct),
        },
        el("span", { id: `upload-bar-${card.id}`, style: `width:${pct}%` })
      )
    );
  }
  if (summary) {
    const meta = summary.meta.filter(Boolean).join(" · ");
    return el(
      "div",
      {},
      el("p", { class: "drop-name", text: summary.name }),
      meta ? el("p", { class: "drop-meta", text: meta }) : null
    );
  }
  return el("p", { class: "drop-empty", text: card.hint });
}

function uploadChip(card, summary) {
  if (summary) return el("span", { class: "chip chip-ok" }, el("span", { class: "chip-dot" }), "已就绪");
  if (card.required) return el("span", { class: "chip chip-warn" }, el("span", { class: "chip-dot" }), "必填");
  return el("span", { class: "chip" }, el("span", { class: "chip-dot" }), "可选");
}

function renderPrepareModeChip() {
  const host = byId("prepare-mode-chip");
  if (!host) return;
  const ws = state.workspace;
  if (!ws || !ws.media) {
    replace(host, el("span", { class: "chip" }, el("span", { class: "chip-dot" }), "上传视频后选择模式"));
    return;
  }
  const mode = ws.prepare_mode || (ws.uploads && ws.uploads.trans ? "import" : "video_only");
  if (mode === "import") {
    replace(
      host,
      el("span", { class: "chip chip-ok" }, el("span", { class: "chip-dot" }), "导入字幕模式"),
      el("span", { class: "chip" }, el("span", { class: "chip-dot" }), "准备后可选修复时间轴")
    );
  } else {
    replace(
      host,
      el("span", { class: "chip chip-ok" }, el("span", { class: "chip-dot" }), "视频直入模式"),
      el("span", { class: "chip" }, el("span", { class: "chip-dot" }), "Qwen 转写 · 自动对齐")
    );
  }
}

function renderUploads() {
  renderPrepareModeChip();
  replace(
    byId("upload-grid"),
    UPLOADS.map((card) => {
      const summary = uploadSummary(card);
      const transfer = state.transfers[card.id];
      const input = el("input", {
        type: "file",
        accept: card.accept,
        tabindex: "-1",
        "aria-hidden": "true",
        onchange: (event) => {
          const file = event.target.files[0];
          if (file) doUpload(card, file);
          event.target.value = "";
        },
      });

      // Depth counter: dragleave also fires when the pointer crosses child nodes.
      let depth = 0;
      const node = el(
        "div",
        {
          class: "card drop",
          ondragenter: (event) => {
            event.preventDefault();
            depth += 1;
            node.classList.add("is-over");
          },
          ondragover: (event) => event.preventDefault(),
          ondragleave: () => {
            depth = Math.max(0, depth - 1);
            if (!depth) node.classList.remove("is-over");
          },
          ondrop: (event) => {
            event.preventDefault();
            depth = 0;
            node.classList.remove("is-over");
            const file = event.dataTransfer.files[0];
            if (file) doUpload(card, file);
          },
        },
        el(
          "div",
          { class: "card-head" },
          el("p", { class: "card-title", text: card.title }),
          uploadChip(card, summary)
        ),
        el("div", { class: "drop-body" }, uploadBody(card, summary)),
        transfer
          ? el(
              "div",
              { class: "btn-row" },
              el("button", { class: "btn btn-danger", text: "取消上传", onclick: () => transfer.xhr.abort() })
            )
          : el(
              "div",
              { class: "btn-row" },
              el("button", {
                class: "btn btn-ghost",
                text: summary ? "更换文件" : "选择文件",
                onclick: () => input.click(),
              }),
              summary && card.removable
                ? el("button", { class: "btn btn-danger", text: "移除", onclick: (event) => withBusy(event.currentTarget, () => doRemove(card)) })
                : null
            ),
        input
      );
      return node;
    })
  );
}

function sendFile(url, file, onProgress) {
  const xhr = new XMLHttpRequest();
  const done = new Promise((resolve, reject) => {
    xhr.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable) onProgress(event.loaded / event.total);
    });
    xhr.addEventListener("load", () => {
      let data = null;
      try {
        data = JSON.parse(xhr.responseText);
      } catch {
        data = null;
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(data);
      else reject(new Error((data && data.detail) || xhr.statusText || `上传失败（${xhr.status}）`));
    });
    xhr.addEventListener("error", () => reject(new Error("网络中断，上传失败")));
    xhr.addEventListener("abort", () => reject(new Error("上传已取消")));
  });
  const form = new FormData();
  form.append("file", file);
  xhr.open("POST", url);
  xhr.send(form);
  return { xhr, done };
}

// Patch the progress nodes in place: a full re-render per progress event is wasteful.
function paintUploadProgress(cardId) {
  const transfer = state.transfers[cardId];
  const bar = byId(`upload-bar-${cardId}`);
  if (!transfer || !bar) return;
  const pct = Math.round(transfer.progress * 100);
  bar.style.width = `${pct}%`;
  byId(`upload-track-${cardId}`).setAttribute("aria-valuenow", String(pct));
  byId(`upload-pct-${cardId}`).textContent = `${pct}%`;
  byId(`upload-state-${cardId}`).textContent = pct >= 100 ? "服务端处理中…" : "上传中";
}

async function doUpload(card, file) {
  if (state.transfers[card.id]) return toast("该素材还有上传未完成", "error");
  const transfer = { name: file.name, progress: 0, xhr: null };
  state.transfers[card.id] = transfer;
  const request = sendFile(card.url, file, (progress) => {
    transfer.progress = progress;
    paintUploadProgress(card.id);
  });
  transfer.xhr = request.xhr;
  renderUploads();
  try {
    await request.done;
    delete state.transfers[card.id];
    await refreshStatus();
    await refreshStages();
    toast(`${file.name} 上传完成`);
  } catch (error) {
    delete state.transfers[card.id];
    renderUploads();
    toast(error.message, "error");
  }
}

async function doRemove(card) {
  try {
    await api(card.removable, { method: "DELETE" });
    await refreshStatus();
    await refreshStages();
    toast("已移除");
  } catch (error) {
    toast(error.message, "error");
  }
}

// ------------
// Section 02: secrets
// ------------

function renderSecrets() {
  if (!state.config) return;
  replace(
    byId("secret-grid"),
    state.config.secrets.map((secret) => {
      const input = el("input", {
        type: "password",
        autocomplete: "off",
        "aria-label": secret.label,
        placeholder: secret.configured ? "已配置，可覆盖" : "粘贴密钥",
      });
      const saveBtn = el("button", { class: "btn btn-primary", text: "保存" });
      const save = () =>
        withBusy(saveBtn, async () => {
          if (!input.value.trim()) return toast("请先粘贴密钥", "error");
          try {
            await sendJSON("/api/secrets", "POST", { name: secret.name, value: input.value });
            input.value = "";
            await refreshConfig();
            toast(`${secret.label} 已写入 ${secret.key_file}`);
          } catch (error) {
            toast(error.message, "error");
          }
        });
      saveBtn.addEventListener("click", save);
      input.addEventListener("keydown", (event) => {
        if (event.key === "Enter") save();
      });

      return el(
        "div",
        { class: "card" },
        el(
          "div",
          { class: "card-head" },
          el("p", { class: "card-title", text: secret.label }),
          el(
            "span",
            { class: secret.configured ? "chip chip-ok" : "chip chip-warn" },
            el("span", { class: "chip-dot" }),
            secret.configured ? (secret.source === "file" ? "密钥文件" : "config.yaml") : "未配置"
          )
        ),
        el("p", { class: "card-note", text: secret.hint }),
        el("div", { class: "secret-row" }, input, saveBtn)
      );
    })
  );
}

// ------------
// Section 03: config
// ------------

let savedFlashTimer = null;

function flashSaved(key) {
  state.savedKey = key;
  clearTimeout(savedFlashTimer);
  savedFlashTimer = setTimeout(() => {
    state.savedKey = null;
    renderConfig();
  }, 1600);
}

function fieldControl(field) {
  const value = cfg(field.key);
  const commit = async (next) => {
    try {
      const result = await sendJSON("/api/config", "PATCH", { [field.key]: next });
      state.config = result;
      flashSaved(field.key);
      renderConfig();
      renderFooter();
    } catch (error) {
      toast(error.message, "error");
      renderConfig();
    }
  };

  if (field.type === "bool") {
    return el("div", {
      class: "switch",
      role: "switch",
      tabindex: "0",
      "data-key": field.key,
      "aria-label": field.label,
      "aria-checked": value ? "true" : "false",
      onclick: () => commit(!value),
      onkeydown: (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          commit(!value);
        }
      },
    });
  }

  if (field.type === "select") {
    const select = el(
      "select",
      { "data-key": field.key, "aria-label": field.label, onchange: (event) => commit(event.target.value) },
      field.options.map(([optValue, label]) =>
        el("option", { value: optValue, selected: String(value) === optValue }, label)
      )
    );
    return select;
  }

  if (field.type === "number") {
    return el("input", {
      type: "number",
      value: value ?? "",
      min: field.min,
      max: field.max,
      step: field.step,
      "data-key": field.key,
      "aria-label": field.label,
      onchange: (event) => {
        const next = Number(event.target.value);
        if (Number.isNaN(next)) return renderConfig();
        commit(field.step === 1 ? Math.round(next) : next);
      },
    });
  }

  if (field.type === "intervals") {
    const rows = Array.isArray(value) ? value : [];
    const submit = (next) => commit(next);
    return el(
      "div",
      { class: "intervals" },
      rows.map((pair, index) =>
        el(
          "div",
          { class: "interval-row" },
          el("input", {
            type: "number",
            step: 0.01,
            min: 0,
            value: pair[0],
            "aria-label": `${field.label} 第 ${index + 1} 段起点`,
            onchange: (event) => {
              const next = rows.map((row) => [...row]);
              next[index][0] = Number(event.target.value);
              submit(next);
            },
          }),
          el("span", { class: "interval-sep", text: "→", "aria-hidden": "true" }),
          el("input", {
            type: "number",
            step: 0.01,
            min: 0,
            value: pair[1],
            "aria-label": `${field.label} 第 ${index + 1} 段终点`,
            onchange: (event) => {
              const next = rows.map((row) => [...row]);
              next[index][1] = Number(event.target.value);
              submit(next);
            },
          }),
          el("button", {
            class: "btn btn-danger btn-sm",
            text: "删除",
            "aria-label": `删除第 ${index + 1} 段区间`,
            onclick: () => submit(rows.filter((_, i) => i !== index)),
          })
        )
      ),
      el("button", {
        class: "btn btn-ghost btn-sm",
        text: "添加区间",
        onclick: () => {
          const last = rows.length ? rows[rows.length - 1][1] : 0;
          submit([...rows, [Number(last), Number(last) + 1]]);
        },
      })
    );
  }

  return el("input", {
    type: "text",
    value: value ?? "",
    "data-key": field.key,
    "aria-label": field.label,
    onchange: (event) => commit(event.target.value),
  });
}

function renderConfig() {
  if (!state.config) return;
  const visible = state.config.groups.filter(
    (group) => !group.when || String(cfg(group.when[0])) === group.when[1]
  );
  // Config commits rebuild the whole grid; remember which control had focus.
  const active = document.activeElement;
  const activeKey = active && active.dataset ? active.dataset.key : null;

  replace(
    byId("config-grid"),
    visible.map((group) =>
      el(
        "div",
        { class: "card" },
        el("p", { class: "card-title", text: group.title }),
        group.desc ? el("p", { class: "card-note", style: "margin-top:6px", text: group.desc }) : null,
        el(
          "div",
          { class: "field-list" },
          group.fields.map((field) =>
            el(
              "div",
              { class: "field" },
              el(
                "span",
                { class: "field-label" },
                field.label,
                state.savedKey === field.key ? el("span", { class: "field-saved", text: "已保存" }) : null
              ),
              el("span", { class: "field-control" }, fieldControl(field))
            )
          )
        )
      )
    )
  );

  if (activeKey) {
    const restored = byId("config-grid").querySelector(`[data-key="${CSS.escape(activeKey)}"]`);
    if (restored) restored.focus();
  }
}

// ------------
// Section 04: stages
// ------------

function stageReadiness(stage) {
  const ws = state.workspace;
  if (!ws) return { ready: false, reason: "读取工作区…", done: false };
  if (stage.name === "prepare") {
    if (!ws.media) return { ready: false, reason: "先上传原视频", done: false };
    if (ws.prepare_mode === "import") {
      const alignedReady = ws.prepared.alignment_ready;
      const decided = ws.alignment && ws.alignment.mode;
      return {
        ready: true,
        done: Boolean(alignedReady && (decided || ws.prepared.tasks_ready)),
      };
    }
    return { ready: true, done: ws.prepared.tasks_ready && ws.prepared.refer_count > 0 };
  }
  if (ws.alignment && ws.alignment.decision_pending) {
    return { ready: false, reason: "先完成时间轴决策", done: false };
  }
  if (!ws.prepared.tasks_ready) return { ready: false, reason: "先完成准备阶段", done: false };
  return { ready: true, done: ws.dubbed.done && ws.dubbed.video_ready };
}

function stageSteps(stage, readiness) {
  const live = state.job && state.job.name === stage.name ? state.job.steps : null;
  return stage.steps.map((label, index) => {
    const step = live && live[index];
    const status = step ? step.status : readiness.done ? "done" : "pending";
    return el(
      "div",
      { class: `stage-step ${status}` },
      el("span", { class: "idx", text: status === "done" ? "✓" : String(index + 1) }),
      el("span", { class: "label", text: label }),
      el("span", { class: "time", text: step && step.elapsed !== null ? fmtSecs(step.elapsed) : "" })
    );
  });
}

function renderStages() {
  const job = state.job;
  const busy = jobBusy();

  replace(
    byId("stage-grid"),
    state.stages.map((stage, index) => {
      const readiness = stageReadiness(stage);
      const isCurrent = job && job.name === stage.name;
      const controls = [];

      if (isCurrent && busy) {
        controls.push(
          el("button", {
            class: "btn btn-ghost",
            text: job.state === "paused" ? "继续" : "暂停",
            onclick: () => control(job.state === "paused" ? "resume" : "pause"),
          }),
          el("button", { class: "btn btn-danger", text: "停止", onclick: () => control("stop") })
        );
      } else {
        controls.push(
          el("button", {
            class: "btn btn-primary btn-lg",
            text: readiness.done ? `重跑${stage.title}` : stage.action,
            disabled: !readiness.ready || busy,
            onclick: () => startStage(stage.name),
          })
        );
      }

      const notices = [];
      if (!readiness.ready && readiness.reason) {
        notices.push(el("p", { class: "notice", text: readiness.reason }));
      }
      if (isCurrent && job.state === "error") {
        notices.push(el("p", { class: "notice notice-error", text: job.error }));
      }
      if (isCurrent && job.state === "stopped") {
        notices.push(el("p", { class: "notice notice-warn", text: "任务已停止，产物可能不完整。" }));
      }

      return el(
        "div",
        { class: "card stage" },
        el(
          "div",
          { class: "card-head" },
          el(
            "p",
            { class: "card-title" },
            el("span", { class: "band-step", "aria-hidden": "true", text: String(index + 1).padStart(2, "0") }),
            stage.title
          ),
          stageChip(stage, readiness, isCurrent)
        ),
        el("p", { class: "card-note", text: stage.desc }),
        isCurrent
          ? el("div", { class: "progress" }, el("span", { style: `width:${Math.round(job.progress * 100)}%` }))
          : null,
        el("div", { class: "stage-steps" }, stageSteps(stage, readiness)),
        isCurrent && job.elapsed !== null
          ? el("p", { class: "card-note", text: `本次运行耗时 ${fmtSecs(job.elapsed)}` })
          : null,
        notices,
        el("div", { class: "btn-row" }, controls)
      );
    })
  );
}

function stageChip(stage, readiness, isCurrent) {
  if (isCurrent && state.job.state === "running") {
    return el("span", { class: "chip chip-run" }, el("span", { class: "chip-dot" }), "运行中");
  }
  if (isCurrent && state.job.state === "paused") {
    return el("span", { class: "chip chip-warn" }, el("span", { class: "chip-dot" }), "已暂停");
  }
  if (isCurrent && state.job.state === "error") {
    return el("span", { class: "chip chip-err" }, el("span", { class: "chip-dot" }), "失败");
  }
  if (readiness.done) {
    const ws = state.workspace;
    const detail =
      stage.name === "prepare"
        ? `${ws.prepared.cue_count} 条字幕 · ${ws.prepared.refer_count} 段参考`
        : `${ws.dubbed.segment_count} 段配音`;
    return el("span", { class: "chip chip-ok" }, el("span", { class: "chip-dot" }), detail);
  }
  return el("span", { class: "chip" }, el("span", { class: "chip-dot" }), "待运行");
}

async function startStage(name) {
  try {
    const snapshot = await sendJSON(`/api/jobs/${name}`, "POST", name === "dub" ? { force: true } : {});
    state.job = snapshot;
    renderStages();
    schedulePoll(true);
  } catch (error) {
    toast(error.message, "error");
  }
}

async function control(action) {
  try {
    state.job = await sendJSON("/api/jobs/control", "POST", { action });
    renderStages();
  } catch (error) {
    toast(error.message, "error");
  }
}

// ------------
// Section 05: speakers
// ------------

function mergeMaxGapSeconds() {
  const value = Number(cfg("speaker_tagging.tts_merge_max_gap"));
  return Number.isFinite(value) ? value : 1;
}

function autoSuggestDraftMerges() {
  const draft = state.speakerDraft || [];
  if (draft.length < 2) return;
  const maxGap = mergeMaxGapSeconds();
  draft[0].merge_with_previous = false;
  draft[0].force_unmerge = false;
  for (let index = 1; index < draft.length; index += 1) {
    const item = draft[index];
    const previous = draft[index - 1];
    if (item.force_unmerge) {
      item.merge_with_previous = false;
      continue;
    }
    const start = parseSrtTime(item.start);
    const prevEnd = parseSrtTime(previous.end);
    const sameSpeaker = !!(item.speaker && item.speaker === previous.speaker);
    const gapOk =
      start !== null && prevEnd !== null && start - prevEnd >= -0.5 && start - prevEnd <= maxGap;
    item.merge_with_previous = sameSpeaker && gapOk;
  }
}

function ensureSpeakerDraft() {
  if (!state.speakers || !state.speakers.cues.length) {
    state.speakerDraft = null;
    return;
  }
  if (state.speakerDraft) return;
  state.speakerDraft = state.speakers.cues.map((cue) => ({
    _id: `cue-${cue.cue}`,
    source_id: String(cue.cue),
    cue: cue.cue,
    start: cue.start,
    end: cue.end,
    text: cue.text || "",
    origin: cue.origin || "",
    speaker: cue.speaker || "",
    merge_with_previous: !!cue.merge_with_previous,
    force_unmerge: !!cue.force_unmerge,
    confidence: cue.confidence,
    reason: cue.reason || "",
    manual_override: !!cue.manual_override,
  }));
  state.pendingKeepOriginal = [];
  autoSuggestDraftMerges();
  state.speakerSelected = new Set();
}

function speakerNameOptions() {
  const names = new Set([
    ...(state.speakers?.speaker_names || []),
    ...state.customSpeakers,
    ...((state.speakerDraft || []).map((item) => item.speaker).filter(Boolean)),
  ]);
  return [...names].sort((a, b) => a.localeCompare(b, "zh"));
}

function cueComparable(cue) {
  return [
    cue.start,
    cue.end,
    (cue.text || "").trim(),
    (cue.origin || "").trim(),
    (cue.speaker || "").trim(),
    !!cue.merge_with_previous,
  ];
}

function cueDraftSummary() {
  if (!state.speakerDraft || !state.speakers) {
    return { added: 0, modified: 0, deleted: 0, keep_original: 0, total: 0 };
  }
  const originals = new Map(state.speakers.cues.map((cue) => [String(cue.cue), cue]));
  const present = new Set();
  let added = 0;
  let modified = 0;
  for (const item of state.speakerDraft) {
    const original = originals.get(item.source_id);
    if (!original) {
      added += 1;
      continue;
    }
    present.add(item.source_id);
    if (JSON.stringify(cueComparable(item)) !== JSON.stringify(cueComparable(original))) modified += 1;
  }
  const keepOriginal = (state.pendingKeepOriginal || []).length;
  // Pending keep-original cues are removed from the draft, so they already count
  // as deleted relative to the original set; surface them separately in the chip.
  const deleted = Math.max(
    0,
    [...originals.keys()].filter((id) => !present.has(id)).length - keepOriginal
  );
  return {
    added,
    modified,
    deleted,
    keep_original: keepOriginal,
    total: added + modified + deleted + keepOriginal,
  };
}

function parseSrtTime(value) {
  const match = String(value || "").trim().match(/^(\d{1,2}):([0-5]\d):([0-5]\d)[,.](\d{1,3})$/);
  if (!match) return null;
  return Number(match[1]) * 3600 + Number(match[2]) * 60 + Number(match[3]) + Number(match[4].padEnd(3, "0")) / 1000;
}

function formatSrtTime(seconds) {
  const total = Math.max(0, Math.round(Number(seconds || 0) * 1000));
  const hours = Math.floor(total / 3600000);
  const minutes = Math.floor((total % 3600000) / 60000);
  const secs = Math.floor((total % 60000) / 1000);
  const millis = total % 1000;
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")},${String(millis).padStart(3, "0")}`;
}

function localSpeakerErrors() {
  const errors = {};
  const draft = state.speakerDraft || [];
  if (!draft.length) return errors;
  const duration = state.workspace?.media?.duration;
  for (const item of draft) {
    const fields = {};
    const start = parseSrtTime(item.start);
    const end = parseSrtTime(item.end);
    if (start === null) fields.start = "时间格式应为 HH:MM:SS,mmm";
    if (end === null) fields.end = "时间格式应为 HH:MM:SS,mmm";
    // end <= start is auto-repaired on apply (merge into same-speaker neighbor or drop).
    if (end !== null && duration && end > duration + 0.001) fields.end = "超出媒体时长";
    if (!(item.text || "").trim()) fields.text = "译文不能为空";
    if (!(item.speaker || "").trim()) fields.speaker = "人物不能为空";
    if (Object.keys(fields).length) errors[item._id] = fields;
  }
  if (draft[0].merge_with_previous) {
    errors[draft[0]._id] = { ...(errors[draft[0]._id] || {}), merge: "第一条不能并入上一条" };
  }
  for (let index = 1; index < draft.length; index += 1) {
    const item = draft[index];
    if (item.merge_with_previous && item.speaker !== draft[index - 1].speaker) {
      errors[item._id] = {
        ...(errors[item._id] || {}),
        merge: `与上一条人物不同（${draft[index - 1].speaker || "空"}）`,
      };
    }
  }
  return errors;
}

function isFillerCueText(text) {
  const cleaned = String(text || "")
    .replace(/[^\p{L}\p{N}]/gu, "")
    .trim()
    .toLowerCase();
  if (!cleaned) return false;
  return /^(?:嗯+|啊+|哼+|哦+|噢+|呃+|嘿+|唉+|咦+|哇+|嗨+|哈+|m+h*m*|u+h+|u+m+|a+h+|o+h+|h+m+|huh|hmph|hah?|heh|meh)$/u.test(
    cleaned
  );
}

function localCueWarnings() {
  const warnings = {};
  const draft = state.speakerDraft || [];
  for (const item of draft) {
    const start = parseSrtTime(item.start);
    const end = parseSrtTime(item.end);
    if (start !== null && end !== null && start >= end) {
      warnings[item._id] = "时长无效：应用时将并入相邻同角色字幕，否则删除";
      continue;
    }
    if (
      start !== null &&
      end !== null &&
      end - start > 0 &&
      end - start <= 0.35 &&
      (isFillerCueText(item.origin) || isFillerCueText(item.text))
    ) {
      warnings[item._id] = "短语气词：应用时能并入相邻同角色则合并，否则删除并保留原人声";
    }
  }
  for (let index = 1; index < draft.length; index += 1) {
    if (warnings[draft[index]._id]) continue;
    const start = parseSrtTime(draft[index].start);
    const previousEnd = parseSrtTime(draft[index - 1].end);
    if (start !== null && previousEnd !== null && start < previousEnd) {
      warnings[draft[index]._id] = "与上一条时间重叠（允许应用）";
    }
  }
  return warnings;
}

function setDraftSpeaker(ids, speaker) {
  const name = (speaker || "").trim();
  if (!name) return;
  if (!speakerNameOptions().includes(name)) state.customSpeakers.push(name);
  for (const draft of state.speakerDraft) {
    if (!ids.has(draft._id)) continue;
    draft.speaker = name;
    draft.manual_override = true;
    draft.confidence = 1;
    // Speaker change re-enables automatic merge suggestion for this cue.
    draft.force_unmerge = false;
  }
  autoSuggestDraftMerges();
  renderSpeakers();
}

function setDraftMerge(ids, merge) {
  for (const draft of state.speakerDraft) {
    if (!ids.has(draft._id)) continue;
    draft.merge_with_previous = !!merge;
    draft.force_unmerge = !merge;
    draft.manual_override = true;
    draft.confidence = 1;
  }
  autoSuggestDraftMerges();
  renderSpeakers();
}

function discardSpeakerDraft() {
  state.speakerDraft = null;
  state.pendingKeepOriginal = [];
  ensureSpeakerDraft();
  renderSpeakers();
}

function sortSpeakerDraft() {
  state.speakerDraft.sort((a, b) => {
    const aTime = parseSrtTime(a.start);
    const bTime = parseSrtTime(b.start);
    return (aTime === null ? Infinity : aTime) - (bTime === null ? Infinity : bTime);
  });
}

function addSpeakerCue(afterId) {
  const draft = state.speakerDraft;
  const index = afterId ? draft.findIndex((item) => item._id === afterId) : draft.length - 1;
  const previous = index >= 0 ? draft[index] : null;
  const next = draft[index + 1] || null;
  const duration = state.workspace?.media?.duration;
  let start = previous ? parseSrtTime(previous.end) : 0;
  if (start === null) start = previous ? parseSrtTime(previous.start) || 0 : 0;
  let end = next ? parseSrtTime(next.start) : null;
  if (end === null || end <= start + 0.1) end = start + 1;
  if (duration && end > duration) {
    end = duration;
    if (end <= start) start = Math.max(0, end - 1);
  }
  const id = `new-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  draft.splice(index + 1, 0, {
    _id: id,
    source_id: id,
    cue: null,
    start: formatSrtTime(start),
    end: formatSrtTime(end),
    text: "",
    origin: "",
    speaker: previous?.speaker || next?.speaker || "",
    merge_with_previous: false,
    force_unmerge: false,
    confidence: 1,
    reason: "",
    manual_override: true,
  });
  autoSuggestDraftMerges();
  renderSpeakers();
  requestAnimationFrame(() => document.querySelector(`[data-cue-id="${id}"][data-field="text"]`)?.focus());
}

async function splitSpeakerCue(id) {
  const draft = state.speakerDraft || [];
  const index = draft.findIndex((item) => item._id === id);
  if (index < 0) return;
  const item = draft[index];
  if (state.cueCaret?.id !== id) {
    toast("请先在该条的「原」文本中点击要分句的位置", "error");
    return;
  }

  state.cueSplitting = id;
  renderSpeakers();
  try {
    const result = await sendJSON("/api/cues/split", "POST", {
      start: item.start,
      end: item.end,
      text: item.text,
      origin: item.origin || item.text,
      split_index: state.cueCaret.index,
    });
    const rightId = `new-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    draft.splice(
      index,
      1,
      { ...item, ...result.left, manual_override: true, confidence: 1 },
      {
        ...item,
        ...result.right,
        _id: rightId,
        source_id: rightId,
        cue: null,
        merge_with_previous: false,
        force_unmerge: false,
        manual_override: true,
        confidence: 1,
      }
    );
    state.cueCaret = null;
    sortSpeakerDraft();
    autoSuggestDraftMerges();
    (result.warnings || []).forEach((message) => toast(message, "error"));
    if (!(result.warnings || []).length) toast("已分句，时间戳按字级对齐推算");
  } catch (error) {
    toast(error.message, "error");
  } finally {
    state.cueSplitting = null;
    renderSpeakers();
  }
}

function deleteSpeakerCue(id) {
  if (state.speakerDraft.length === 1) {
    toast("至少需要保留一条字幕", "error");
    return;
  }
  state.speakerDraft = state.speakerDraft.filter((item) => item._id !== id);
  state.speakerSelected.delete(id);
  autoSuggestDraftMerges();
  renderSpeakers();
}

async function keepOriginalTasks(numbers) {
  const selected = [...new Set((numbers || []).map((n) => Number(n)).filter(Boolean))];
  if (!selected.length) return toast("请先选择任务", "error");
  const confirmed = await askModal({
    title: selected.length === 1 ? `任务 ${selected[0]} 保留原人声？` : `保留 ${selected.length} 条任务的原人声？`,
    note: "这些任务将从配音列表移除，合片时对应时段播放原人声，不再生成 TTS。字幕文本不会删除。",
    confirmText: "保留原人声",
    danger: true,
  });
  if (!confirmed) return;
  try {
    const result = await sendJSON("/api/tasks/keep-original", "POST", { numbers: selected });
    for (const number of selected) state.taskSelected.delete(number);
    await refreshTables();
    await refreshStatus();
    toast(
      `已保留原人声 ${result.removed_numbers?.length || selected.length} 条；请点「重新合片」`
    );
  } catch (error) {
    toast(error.message, "error");
  }
}

function syncCueDraftControls() {
  const summary = cueDraftSummary();
  const hasErrors = Object.keys(localSpeakerErrors()).length > 0;
  const apply = byId("speaker-apply-btn");
  const discard = byId("speaker-discard-btn");
  const chip = byId("speaker-draft-chip");
  if (apply) {
    apply.disabled = jobBusy() || !summary.total || hasErrors;
    apply.textContent = summary.total
      ? `应用并重建任务（${summary.total}）`
      : "应用并重建任务";
  }
  if (discard) discard.disabled = jobBusy() || !summary.total;
  if (chip) {
    chip.textContent =
      `草稿：新增 ${summary.added} · 修改 ${summary.modified} · 删除 ${summary.deleted}` +
      (summary.keep_original ? ` · 保留原人声 ${summary.keep_original}` : "");
    chip.hidden = !summary.total;
  }
}

async function applySpeakerDraft() {
  const errors = localSpeakerErrors();
  if (Object.keys(errors).length) {
    toast("存在无效时间、文本、人物或合并关系，请先修正标红字段", "error");
    renderSpeakers();
    return;
  }
  const summary = cueDraftSummary();
  const confirmed = await askModal({
    title: "应用字幕校正并重建任务？",
    note:
      `新增 ${summary.added}、修改 ${summary.modified}、删除 ${summary.deleted}` +
      (summary.keep_original ? `、保留原人声 ${summary.keep_original}` : "") +
      "。现有任务音频、候选和手工参考将被清理；旧成片会保留并标记为过期。",
    confirmText: "应用并重建",
    danger: true,
  });
  if (!confirmed) return;
  try {
    const snapshot = await sendJSON("/api/speakers/apply", "POST", {
      cues: state.speakerDraft,
      keep_original: state.pendingKeepOriginal || [],
    });
    state.job = snapshot;
    state.speakerSelected = new Set();
    state.pendingKeepOriginal = [];
    renderSpeakers();
    renderStages();
    schedulePoll(true);
    toast("已提交人物修改，正在重建任务…");
  } catch (error) {
    toast(error.message, "error");
    renderSpeakers();
  }
}

function fmtDelta(seconds) {
  const value = Number(seconds) || 0;
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}s`;
}

async function refreshAlignment() {
  try {
    state.alignment = await api("/api/alignment");
  } catch (error) {
    state.alignment = null;
  }
  renderAlignment();
}

async function applyAlignmentRepair() {
  const ok = await askModal({
    title: "按字级对齐修复时间轴？",
    body: "将改写字幕起止时间并重建全部配音任务与参考音频；文本不会改变。",
    confirm: "修复并重建",
    danger: true,
  });
  if (!ok) return;
  try {
    const snapshot = await sendJSON("/api/alignment/apply", "POST", {});
    state.job = snapshot;
    renderAlignment();
    renderStages();
    schedulePoll(true);
    toast("开始按对齐修复时间轴…");
  } catch (error) {
    toast(error.message, "error");
  }
}

async function skipAlignmentRepair() {
  const ok = await askModal({
    title: "保持原时间轴？",
    body: "不改字幕时间，空档原人声将使用保守静音余量，随后生成配音任务。",
    confirm: "保持原时间轴",
  });
  if (!ok) return;
  try {
    const snapshot = await sendJSON("/api/alignment/skip", "POST", {});
    state.job = snapshot;
    renderAlignment();
    renderStages();
    schedulePoll(true);
    toast("保持原时间轴，开始生成任务…");
  } catch (error) {
    toast(error.message, "error");
  }
}

function renderAlignment() {
  const section = byId("section-alignment");
  if (!section) return;
  const data = state.alignment;
  const ws = state.workspace;
  const proposal = data && data.proposal;
  const pending = ws && ws.alignment && ws.alignment.decision_pending;
  const modeHint = (data && data.mode) || (ws && ws.alignment && ws.alignment.mode);
  // Show whenever a proposal exists and the import gate still needs a choice,
  // or after a choice so the user can see what was applied.
  const show = Boolean(proposal && (pending || modeHint || (data && data.mode)));
  if (!show) {
    section.hidden = true;
    syncNavAvailability();
    return;
  }
  section.hidden = false;
  syncNavAvailability();

  const mode = (data && data.mode) || (ws.alignment && ws.alignment.mode);
  const items = (proposal && proposal.items) || [];
  const changed = items.filter((item) => item.changed);

  replace(
    byId("alignment-summary"),
    el("span", { class: "chip" }, el("span", { class: "chip-dot" }), `${proposal.cue_count || items.length} 条字幕`),
    el(
      "span",
      { class: changed.length ? "chip chip-warn" : "chip chip-ok" },
      el("span", { class: "chip-dot" }),
      `${proposal.changed_count || changed.length} 条建议调整`
    ),
    mode
      ? el(
          "span",
          { class: "chip chip-ok" },
          el("span", { class: "chip-dot" }),
          mode === "aligned" ? "已选：最佳对齐" : "已选：保守方案"
        )
      : el("span", { class: "chip chip-warn" }, el("span", { class: "chip-dot" }), "待选择")
  );

  const busy = jobBusy() && state.job && ["alignment_apply", "alignment_skip"].includes(state.job.name);
  replace(
    byId("alignment-toolbar"),
    el("button", {
      class: "btn",
      text: "按对齐修复（最佳）",
      disabled: busy || Boolean(mode),
      onclick: () => applyAlignmentRepair(),
    }),
    el("button", {
      class: "btn btn-ghost",
      text: "保持原时间轴（保守）",
      disabled: busy || Boolean(mode),
      onclick: () => skipAlignmentRepair(),
    })
  );

  renderMiniJob("alignment-job", ["alignment_apply", "alignment_skip"]);

  const rows = (changed.length ? changed : items).slice(0, 80).map((item) =>
    el(
      "tr",
      {},
      el("td", { text: String(item.cue) }),
      el("td", { text: item.text || "" }),
      el(
        "td",
        { class: "mono", text: `${item.old_start.toFixed(2)} → ${item.old_end.toFixed(2)}` }
      ),
      el(
        "td",
        { class: "mono", text: `${item.new_start.toFixed(2)} → ${item.new_end.toFixed(2)}` }
      ),
      el(
        "td",
        {
          class: item.changed ? "mono warn" : "mono",
          text: `${fmtDelta(item.start_delta)} / ${fmtDelta(item.end_delta)}`,
        }
      )
    )
  );

  replace(
    byId("alignment-table"),
    el(
      "thead",
      {},
      el(
        "tr",
        {},
        el("th", { text: "#" }),
        el("th", { text: "文本" }),
        el("th", { text: "当前时间" }),
        el("th", { text: "建议时间" }),
        el("th", { text: "偏移（起/止）" })
      )
    ),
    el("tbody", {}, rows.length ? rows : el("tr", {}, el("td", { colspan: "5", text: "无需调整" })))
  );
}

function renderSpeakers() {
  const data = state.speakers;
  const section = byId("section-speakers");
  if (!data || !data.cues.length) {
    section.hidden = true;
    state.speakerUI = null;
    syncNavAvailability();
    return;
  }
  section.hidden = false;
  syncNavAvailability();
  ensureSpeakerDraft();
  const draft = state.speakerDraft;
  const errors = localSpeakerErrors();
  const warnings = localCueWarnings();
  const summary = cueDraftSummary();
  const dirty = summary.total;
  const busy = jobBusy() || !!state.cueSplitting;
  const names = speakerNameOptions();

  const chips = [
    el(
      "span",
      { class: "chip chip-ok" },
      el("span", { class: "chip-dot" }),
      `${data.cues.length} 条字幕 · ${data.groups} 组参考音频`
    ),
    ...data.speakers.map((speaker) =>
      el("span", { class: "chip" }, el("span", { class: "chip-dot" }), `${speaker.name} · ${speaker.cues}`)
    ),
  ];
  if (dirty) {
    chips.push(
      el(
        "span",
        { class: "chip chip-warn", id: "speaker-draft-chip" },
        el("span", { class: "chip-dot" }),
        `草稿：新增 ${summary.added} · 修改 ${summary.modified} · 删除 ${summary.deleted}`
      )
    );
  }
  if (data.stale) chips.push(el("span", { class: "chip chip-warn" }, el("span", { class: "chip-dot" }), "标记与当前字幕不匹配"));
  replace(byId("speaker-summary"), chips);
  renderMiniJob("speaker-job", ["rebuild_speakers"]);

  const selected = state.speakerSelected;
  const speakerSelect = el(
    "select",
    { id: "batch-speaker-select", "aria-label": "批量设置的人物" },
    el("option", { value: "" }, "选择人物…"),
    names.map((name) => el("option", { value: name }, name)),
    el("option", { value: "__custom__" }, "自定义…")
  );
  const customInput = el("input", {
    type: "text",
    id: "batch-speaker-custom",
    "aria-label": "自定义人物名",
    placeholder: "自定义人物名",
    style: "display:none",
  });
  speakerSelect.addEventListener("change", () => {
    customInput.style.display = speakerSelect.value === "__custom__" ? "" : "none";
  });

  const countNode = el("span", { class: "toolbar-count" });
  const headCheck = el("input", {
    type: "checkbox",
    "aria-label": "全选字幕",
    disabled: busy,
    onchange: (event) => {
      state.speakerSelected = event.target.checked ? new Set(draft.map((item) => item._id)) : new Set();
      paintSelection(state.speakerUI, state.speakerSelected);
      syncSpeakerToolbar();
    },
  });

  const batchSpeakerBtn = el("button", {
    class: "btn btn-ghost",
    text: "批量设人物",
    onclick: () => {
      const value = speakerSelect.value === "__custom__" ? customInput.value : speakerSelect.value;
      if (!value.trim()) return toast("请选择或输入人物名", "error");
      setDraftSpeaker(selected, value);
    },
  });
  const mergeBtn = el("button", {
    class: "btn btn-ghost",
    text: "批量合并上一条",
    onclick: () => setDraftMerge(selected, true),
  });
  const unmergeBtn = el("button", { class: "btn btn-ghost", text: "取消并入", onclick: () => setDraftMerge(selected, false) });
  const discardBtn = el("button", {
    id: "speaker-discard-btn",
    class: "btn btn-danger",
    text: "撤销修改",
    disabled: busy || !dirty,
    onclick: discardSpeakerDraft,
  });
  const addBtn = el("button", {
    class: "btn btn-ghost",
    text: "末尾新增",
    disabled: busy,
    onclick: () => addSpeakerCue(),
  });
  const applyBtn = el("button", {
    id: "speaker-apply-btn",
    class: "btn btn-primary",
    text: dirty ? `应用并重建任务（${dirty}）` : "应用并重建任务",
    disabled: busy || !dirty || Object.keys(errors).length > 0,
    onclick: applySpeakerDraft,
  });

  state.speakerUI = {
    count: countNode,
    headCheck,
    needsSelection: [batchSpeakerBtn, mergeBtn, unmergeBtn],
    rows: [],
    total: draft.length,
  };

  replace(
    byId("speaker-toolbar"),
    countNode,
    speakerSelect,
    customInput,
    batchSpeakerBtn,
    el("span", { class: "sep" }),
    mergeBtn,
    unmergeBtn,
    el("span", { class: "sep" }),
    addBtn,
    discardBtn,
    applyBtn
  );

  const head = el(
    "thead",
    {},
    el(
      "tr",
      {},
      el("th", { class: "check", scope: "col" }, headCheck),
      ...["#", "时间", "人物", "并入上条", "字幕文本", "操作"].map((label) =>
        el("th", { scope: "col", text: label })
      )
    )
  );

  const body = el(
    "tbody",
    {},
    draft.map((item, index) => {
      const original = data.cues.find((cue) => String(cue.cue) === item.source_id);
      const isDirty =
        !original || JSON.stringify(cueComparable(item)) !== JSON.stringify(cueComparable(original));
      const error = errors[item._id] || {};
      const warning = warnings[item._id];
      const hasError = Object.keys(error).length > 0;
      const select = el(
        "select",
        {
          disabled: busy,
          class: error.speaker ? "field-error" : "",
          "aria-label": `第 ${index + 1} 条字幕的人物`,
          onchange: async (event) => {
            if (event.target.value !== "__custom__") {
              setDraftSpeaker(new Set([item._id]), event.target.value);
              return;
            }
            const name = await askModal({
              title: "自定义人物名",
              note: `将应用到第 ${index + 1} 条字幕。`,
              input: "",
              placeholder: "例如：旁白",
              confirmText: "设为该人物",
            });
            if (!name) return renderSpeakers();
            setDraftSpeaker(new Set([item._id]), name);
          },
        },
        el("option", { value: "" }, "未标记"),
        names.map((name) =>
          el("option", { value: name, selected: item.speaker === name }, name)
        ),
        item.speaker && !names.includes(item.speaker)
          ? el("option", { value: item.speaker, selected: true }, item.speaker)
          : null,
        el("option", { value: "__custom__" }, "自定义…")
      );

      const check = el("input", {
        type: "checkbox",
        checked: selected.has(item._id),
        disabled: busy,
        "aria-label": `选择第 ${index + 1} 条字幕`,
        onchange: (event) => {
          if (event.target.checked) selected.add(item._id);
          else selected.delete(item._id);
          row.classList.toggle("selected", event.target.checked);
          syncSpeakerToolbar();
        },
      });

      const timeInput = (field, label) =>
        el(
          "label",
          { class: "cue-time-field" },
          el("span", { class: "sr-only", text: `${label}时间` }),
          el("input", {
            type: "text",
            value: item[field],
            disabled: busy,
            class: error[field] ? "field-error" : "",
            "aria-label": `第 ${index + 1} 条字幕${label}时间`,
            "data-cue-id": item._id,
            "data-field": field,
            oninput: (event) => {
              item[field] = event.target.value;
              syncCueDraftControls();
            },
            onchange: () => {
              sortSpeakerDraft();
              autoSuggestDraftMerges();
              renderSpeakers();
            },
          }),
          error[field] ? el("span", { class: "field-error-text", text: error[field] }) : null
        );

      const textInput = (field, label, placeholder) => {
        // Track the caret while it moves: clicking the split button blurs the
        // textarea and triggers a re-render, so reading it on click is too late.
        const trackCaret =
          field === "origin"
            ? (event) => {
                state.cueCaret = { id: item._id, index: event.target.selectionStart };
              }
            : null;
        return el(
          "label",
          { class: "cue-text-field" },
          el("span", { class: "cue-field-label", text: label }),
          el("textarea", {
            value: item[field],
            disabled: busy,
            class: error[field] ? "field-error" : "",
            placeholder,
            rows: 2,
            "data-cue-id": item._id,
            "data-field": field,
            oninput: (event) => {
              item[field] = event.target.value;
              event.target.classList.toggle("is-dirty", true);
              if (trackCaret) trackCaret(event);
              syncCueDraftControls();
            },
            onclick: trackCaret,
            onkeyup: trackCaret,
            onselect: trackCaret,
            onblur: () => setTimeout(renderSpeakers, 0),
          }),
          error[field] ? el("span", { class: "field-error-text", text: error[field] }) : null
        );
      };

      const row = el(
        "tr",
        {
          class: [
            item.merge_with_previous ? "merged" : "",
            isDirty ? "dirty" : "",
            !original ? "cue-added" : "",
            hasError ? "row-error" : "",
            warning ? "row-warning" : "",
            selected.has(item._id) ? "selected" : "",
          ]
            .filter(Boolean)
            .join(" "),
        },
        el("td", { class: "check" }, check),
        el("td", { class: "num", text: !original ? `${index + 1} · 新增` : index + 1 }),
        el(
          "td",
          { class: "cue-times" },
          timeInput("start", "开始"),
          timeInput("end", "结束"),
          warning ? el("div", { class: "field-warning-text", text: warning }) : null
        ),
        el(
          "td",
          {},
          select,
          error.speaker ? el("div", { class: "row-error-text", text: error.speaker }) : null
        ),
        el(
          "td",
          { class: "check" },
          index === 0
            ? el("span", { class: "skeleton", text: "—" })
            : el(
                "div",
                {},
                el("input", {
                  type: "checkbox",
                  checked: !!item.merge_with_previous,
                  disabled: busy,
                  "aria-label": `第 ${index + 1} 条并入上一条（参考与 TTS）`,
                  onchange: (event) => setDraftMerge(new Set([item._id]), event.target.checked),
                }),
                error.merge ? el("div", { class: "row-error-text", text: error.merge }) : null
              )
        ),
        el(
          "td",
          { class: "cue-texts" },
          textInput("text", "译", "译文字幕"),
          textInput("origin", "原", "可留空，应用时使用译文")
        ),
        el(
          "td",
          { class: "actions cue-actions" },
          el("button", {
            class: "btn btn-ghost",
            type: "button",
            text: "在光标处分句",
            title: "在「原」文本中点击分句位置，时间戳按字级对齐自动推算",
            disabled: busy,
            // Keep focus in the textarea so blurring does not re-render the row
            // out from under this click and drop the caret.
            onmousedown: (event) => event.preventDefault(),
            onclick: () => splitSpeakerCue(item._id),
          }),
          el("button", {
            class: "btn btn-ghost",
            type: "button",
            text: "在后面新增",
            disabled: busy,
            onclick: () => addSpeakerCue(item._id),
          }),
          el("button", {
            class: "btn btn-danger",
            type: "button",
            text: "删除",
            disabled: busy,
            onclick: () => deleteSpeakerCue(item._id),
          })
        )
      );

      state.speakerUI.rows.push({ cue: item._id, row, check });
      return row;
    })
  );

  replace(
    byId("speaker-table"),
    el("caption", { class: "sr-only", text: "字幕人物标记与参考音频分组" }),
    head,
    body
  );
  syncSpeakerToolbar();
}

// Selection changes only touch the affected rows; rebuilding a few hundred
// rows on every checkbox click made long SRTs feel laggy.
function paintSelection(ui, selected) {
  if (!ui) return;
  for (const entry of ui.rows) {
    const on = selected.has(entry.cue);
    entry.check.checked = on;
    entry.row.classList.toggle("selected", on);
  }
}

function syncSelectionCount(ui, selected, label) {
  if (!ui) return;
  const size = selected.size;
  ui.count.textContent = label(size);
  ui.headCheck.checked = ui.total > 0 && size === ui.total;
  ui.headCheck.indeterminate = size > 0 && size < ui.total;
  const busy = jobBusy();
  for (const button of ui.needsSelection) button.disabled = busy || !size;
}

function syncSpeakerToolbar() {
  const ui = state.speakerUI;
  if (!ui) return;
  syncSelectionCount(ui, state.speakerSelected, (size) => `已选 ${size} / ${ui.total}`);
}

// ------------
// Section 06: tasks
// ------------

function audioCell(entry, label) {
  if (!entry) return el("span", { class: "skeleton", text: "—" });
  return el("audio", { controls: true, preload: "none", src: entry.url, "aria-label": label });
}

function pickFiles(accept, multiple = false) {
  return new Promise((resolve) => {
    const input = el("input", { type: "file", accept, multiple: multiple || undefined });
    input.addEventListener("change", () => resolve([...input.files]));
    input.click();
  });
}

async function uploadTaskReference(numbers, files, mode) {
  if (!files.length) return;
  const form = new FormData();
  form.append("mode", mode);
  form.append("numbers", numbers.join(","));
  for (const file of files) form.append("files", file);
  try {
    const result = await api("/api/tasks/reference", { method: "POST", body: form });
    await refreshTables();
    toast(`已覆盖参考音频：${result.overridden.join(", ")}`);
    return result;
  } catch (error) {
    toast(error.message, "error");
  }
}

async function clearTaskReference(numbers) {
  try {
    const result = await sendJSON("/api/tasks/reference/clear", "POST", { numbers });
    await refreshTables();
    toast(result.cleared.length ? `已恢复自动参考：${result.cleared.join(", ")}` : "没有可恢复的覆盖");
  } catch (error) {
    toast(error.message, "error");
  }
}

async function copyTaskReference(source, numbers) {
  try {
    const result = await sendJSON("/api/tasks/reference/copy", "POST", { source, numbers });
    await refreshTables();
    toast(`已用任务 ${source} 的参考覆盖：${result.overridden.join(", ")}`);
    return result;
  } catch (error) {
    toast(error.message, "error");
  }
}

// ------------
// Reference picker: same-speaker clips or upload
// ------------

const refPicker = {
  targets: [],
  preferredSpeaker: "",
  library: null,
};

function setupRefPicker() {
  const dialog = byId("ref-picker");
  byId("ref-picker-close").addEventListener("click", () => dialog.close());
  byId("ref-picker-speaker").addEventListener("change", () => paintRefPickerList());
  byId("ref-picker-upload").addEventListener("click", async () => {
    const files = await pickFiles("audio/*,.wav,.mp3,.m4a,.flac", false);
    if (!files.length) return;
    const result = await uploadTaskReference(refPicker.targets, files, "broadcast");
    if (result) dialog.close();
  });
}

async function openRefPicker(targets, preferredSpeaker) {
  const numbers = [...new Set((targets || []).map((n) => Number(n)).filter(Boolean))];
  if (!numbers.length) return toast("请先选择任务", "error");
  refPicker.targets = numbers;
  refPicker.preferredSpeaker = preferredSpeaker || "";
  try {
    refPicker.library = await api("/api/tasks/reference/library");
  } catch (error) {
    toast(error.message, "error");
    return;
  }

  const title =
    numbers.length === 1 ? `更换任务 ${numbers[0]} 的参考音频` : `为 ${numbers.length} 条任务更换参考音频`;
  byId("ref-picker-title").textContent = title;
  byId("ref-picker-note").textContent = "可选用同角色已有参考，或上传新文件。";

  const select = byId("ref-picker-speaker");
  const speakers = refPicker.library.speakers || [];
  replace(
    select,
    speakers.length
      ? speakers.map((speaker) =>
          el(
            "option",
            {
              value: speaker.name,
              selected: speaker.name === refPicker.preferredSpeaker,
            },
            `${speaker.name}（${speaker.count}）`
          )
        )
      : el("option", { value: "" }, "暂无角色参考")
  );
  if (
    refPicker.preferredSpeaker &&
    speakers.some((speaker) => speaker.name === refPicker.preferredSpeaker)
  ) {
    select.value = refPicker.preferredSpeaker;
  } else if (speakers.length) {
    select.value = speakers[0].name;
  }

  paintRefPickerList();
  byId("ref-picker").showModal();
}

function paintRefPickerList() {
  const host = byId("ref-picker-list");
  const speakers = (refPicker.library && refPicker.library.speakers) || [];
  const selected = byId("ref-picker-speaker").value;
  const group = speakers.find((speaker) => speaker.name === selected);
  const clips = group ? group.clips : [];
  const targetSet = new Set(refPicker.targets);

  if (!clips.length) {
    replace(host, el("p", { class: "ref-picker-empty", text: "该角色还没有可选用的参考音频，请上传文件。" }));
    return;
  }

  replace(
    host,
    clips.map((clip) => {
      const isSelf = targetSet.size === 1 && targetSet.has(clip.number);
      return el(
        "div",
        { class: "ref-clip" },
        el(
          "div",
          { class: "ref-clip-meta" },
          el("div", { class: "ref-clip-title", text: `#${clip.number}${isSelf ? "（当前任务）" : ""}` }),
          el(
            "div",
            { class: "ref-clip-sub", text: `${shortTime(clip.start_time)} → ${shortTime(clip.end_time)}${
              clip.has_override ? " · 手工参考" : ""
            }` }
          ),
          el("div", { class: "ref-clip-text", text: clip.text || "—" })
        ),
        el(
          "div",
          { class: "ref-clip-side" },
          audioCell(clip.refer, `角色参考 #${clip.number}`),
          el("button", {
            class: "btn btn-primary btn-sm",
            text: isSelf ? "已是当前" : "使用此音频",
            disabled: isSelf || jobBusy(),
            onclick: async (event) => {
              await withBusy(event.currentTarget, async () => {
                const result = await copyTaskReference(clip.number, refPicker.targets);
                if (result) byId("ref-picker").close();
              });
            },
          })
        )
      );
    })
  );
}

async function regenerateSelectedTasks(numbers) {
  if (!numbers.length) return toast("请先选择任务", "error");
  const ok = await askModal({
    title: "批量重生成并直接应用",
    note: `将直接覆盖选中的 ${numbers.length} 条任务的当前配音，并立即重新合片。单条试听请用行内「生成候选」。`,
    confirmText: "直接应用",
    danger: true,
  });
  if (!ok) return;
  try {
    const snapshot = await sendJSON("/api/jobs/regenerate", "POST", { numbers });
    state.job = snapshot;
    renderTasks();
    renderStages();
    schedulePoll(true);
    toast(`开始批量重生成 ${numbers.length} 条任务…`);
  } catch (error) {
    toast(error.message, "error");
  }
}

async function generateTaskCandidate(number) {
  const raw = await askModal({
    title: `生成任务 ${number} 的候选配音`,
    note: "一次可生成 1–5 个独立候选，生成时间和 TTS 用量会随数量增加。",
    input: "2",
    placeholder: "候选数量（1–5）",
    confirmText: "开始生成",
  });
  if (raw === null) return;
  const count = Number(raw);
  if (!Number.isInteger(count) || count < 1 || count > 5) {
    toast("候选数量必须是 1 到 5 的整数", "error");
    return;
  }
  try {
    const snapshot = await sendJSON("/api/jobs/candidate", "POST", { number, count });
    state.job = snapshot;
    renderTasks();
    renderStages();
    schedulePoll(true);
    toast(`开始生成任务 ${number} 的 ${count} 个候选配音…`);
  } catch (error) {
    toast(error.message, "error");
  }
}

async function generateOptimizedCandidate(number) {
  const confirmed = await askModal({
    title: "LLM 缩短并重新生成候选？",
    note: "LLM 会主动精简该任务对应的字幕句子，再生成一个独立候选。正式字幕和当前音频不会改变，只有点击“采用候选”后才会写回。",
    confirmText: "缩短并生成",
  });
  if (!confirmed) return;
  try {
    const snapshot = await sendJSON("/api/jobs/candidate", "POST", {
      number,
      count: 1,
      force_shorten: true,
    });
    state.job = snapshot;
    renderTasks();
    renderStages();
    schedulePoll(true);
    toast(`开始用 LLM 缩短任务 ${number} 并生成新候选…`);
  } catch (error) {
    toast(error.message, "error");
  }
}

async function acceptTaskCandidate(number, candidateId) {
  try {
    const result = await sendJSON("/api/tasks/candidate/accept", "POST", {
      number,
      candidate_id: candidateId,
    });
    delete state.candidateChoice[number];
    if (result.text_changed) state.speakerDraft = null;
    await refreshTables();
    await refreshStatus();
    toast(
      result.text_changed
        ? `已采用任务 ${number} 的候选并写回缩写字幕，记得重新合片`
        : `已采用任务 ${number} 的候选，记得重新合片`
    );
  } catch (error) {
    toast(error.message, "error");
  }
}

async function discardTaskCandidate(number, candidateId) {
  try {
    await sendJSON("/api/tasks/candidate/discard", "POST", {
      number,
      candidate_id: candidateId,
    });
    delete state.candidateChoice[number];
    await refreshTables();
    toast(candidateId ? `已放弃任务 ${number} 的该候选` : `已保留任务 ${number} 的当前配音`);
  } catch (error) {
    toast(error.message, "error");
  }
}

async function remasterPending() {
  try {
    const snapshot = await sendJSON("/api/jobs/remaster", "POST", {});
    state.job = snapshot;
    renderTasks();
    renderStages();
    schedulePoll(true);
    toast("开始重新合片…");
  } catch (error) {
    toast(error.message, "error");
  }
}

async function saveTaskText(number, text, button) {
  const run = async () => {
    const result = await sendJSON("/api/tasks/text", "PATCH", { number, text });
    await refreshTables();
    await refreshStatus();
    if (result.changed) toast(`任务 ${number} 文本已保存，请重新生成候选`);
    return result;
  };
  try {
    if (button) return await withBusy(button, run);
    return await run();
  } catch (error) {
    toast(error.message, "error");
    renderTasks();
  }
}

function taskTextEditor(task, busy) {
  const area = el("textarea", {
    class: "task-text-input",
    rows: "2",
    "aria-label": `任务 ${task.number} 的字幕文本`,
    disabled: busy,
  });
  area.value = task.text || "";

  const saveBtn = el("button", {
    class: "btn btn-ghost btn-sm",
    text: "保存文本",
    disabled: true,
    "aria-label": `保存任务 ${task.number} 的字幕文本`,
  });
  const resetBtn = el("button", {
    class: "btn btn-ghost btn-sm",
    text: "还原",
    disabled: true,
    "aria-label": `还原任务 ${task.number} 的字幕文本`,
  });

  const syncDirty = () => {
    const dirty = area.value.trim() !== (task.text || "").trim();
    saveBtn.disabled = busy || !dirty || !area.value.trim();
    resetBtn.disabled = busy || !dirty;
    area.classList.toggle("is-dirty", dirty);
  };

  area.addEventListener("input", syncDirty);
  area.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
      event.preventDefault();
      if (!saveBtn.disabled) saveBtn.click();
    }
  });
  resetBtn.addEventListener("click", () => {
    area.value = task.text || "";
    syncDirty();
    area.focus();
  });
  saveBtn.addEventListener("click", () => saveTaskText(task.number, area.value, saveBtn));

  return el(
    "div",
    { class: "task-text-edit" },
    area,
    el("div", { class: "btn-row task-text-actions" }, saveBtn, resetBtn)
  );
}

function taskAudioStack(task) {
  return el(
    "div",
    { class: "audio-stack" },
    el(
      "div",
      { class: "audio-row" },
      el("span", { class: "audio-tag", text: "参考" }),
      audioCell(task.refer, `任务 ${task.number} 的参考音频`)
    ),
    (task.segments.length ? task.segments : [null]).map((entry, index) =>
      el(
        "div",
        { class: "audio-row" },
        el("span", { class: "audio-tag", text: index ? "" : "当前" }),
        audioCell(entry, `任务 ${task.number} 当前配音 ${index + 1}`)
      )
    )
  );
}

function candidateCompareRow(task, busy) {
  const candidates = task.candidates?.length
    ? task.candidates
    : task.candidate
      ? [task.candidate]
      : [];
  if (!candidates.length) return null;
  const selectedId = state.candidateChoice[task.number];
  const candidate =
    candidates.find((item) => String(item.candidate_id || "") === String(selectedId || "")) ||
    candidates[0];
  state.candidateChoice[task.number] = candidate.candidate_id || "";
  const currentSegs = task.segments.length ? task.segments : [null];
  const candidatePlay =
    candidate.segments.length
      ? candidate.segments
      : candidate.temps && candidate.temps.length
        ? candidate.temps
        : [null];
  const count = Math.max(currentSegs.length, candidatePlay.length);
  const fits = candidate.fits !== false;
  const forced = !fits || candidate.status === "forced_merge";
  const statusChip = fits
    ? el("span", { class: "chip chip-ok" }, el("span", { class: "chip-dot" }), "候选已适配")
    : el("span", { class: "chip chip-warn" }, el("span", { class: "chip-dot" }), "强制合片");
  const meta = [
    candidate.real_dur
      ? `完整时长 ${Number(candidate.real_dur).toFixed(1)}s`
      : null,
    candidate.available
      ? `窗口 ${Number(candidate.available).toFixed(1)}s`
      : null,
    candidate.required_speed
      ? `需 ${Number(candidate.required_speed).toFixed(2)}x`
      : null,
    candidate.shorten_rounds
      ? `缩写 ${candidate.shorten_rounds} 轮`
      : null,
  ].filter(Boolean);

  return el(
    "tr",
    { class: "candidate-row" },
    el(
      "td",
      { colspan: "5" },
      el(
        "div",
        { class: "candidate-panel" },
        el(
          "div",
          { class: "candidate-head" },
          statusChip,
          candidates.length > 1
            ? el(
                "select",
                {
                  class: "candidate-select",
                  "aria-label": `选择任务 ${task.number} 的候选版本`,
                  onchange: (event) => {
                    state.candidateChoice[task.number] = event.target.value;
                    renderTasks();
                  },
                },
                candidates.map((item, index) =>
                  el(
                    "option",
                    {
                      value: item.candidate_id || "",
                      selected:
                        String(item.candidate_id || "") ===
                        String(candidate.candidate_id || ""),
                    },
                    `候选 ${index + 1}${item.fits === false ? " · 强制合片" : ""}`
                  )
                )
              )
            : null,
          ...meta.map((text) => el("span", { class: "card-note", text }))
        ),
        candidate.text_changed || candidate.candidate_text
          ? el(
              "div",
              { class: "candidate-text-diff" },
              el(
                "div",
                { class: "candidate-col" },
                el("p", { class: "candidate-label", text: "当前文本" }),
                el("p", { class: "candidate-text", text: candidate.original_text || task.text || "—" })
              ),
              el(
                "div",
                { class: "candidate-col" },
                el("p", { class: "candidate-label", text: "候选文本" }),
                el("p", { class: "candidate-text", text: candidate.candidate_text || task.text || "—" })
              )
            )
          : null,
        forced
          ? el(
              "p",
              {
                class: "notice notice-warn",
                text:
                  candidate.failure_reason ||
                  "1 轮自动缩写后仍超时，已按最高加速强制合片（可能压到下一句间隙）。",
              }
            )
          : null,
        el(
          "div",
          { class: "candidate-grid" },
          el(
            "div",
            { class: "candidate-col" },
            el("p", { class: "candidate-label", text: "当前版本" }),
            ...Array.from({ length: count }, (_, index) =>
              el(
                "div",
                { class: "audio-row" },
                el("span", { class: "audio-tag", text: count > 1 ? String(index + 1) : "" }),
                audioCell(currentSegs[index] || null, `任务 ${task.number} 当前版本 ${index + 1}`)
              )
            )
          ),
          el(
            "div",
            { class: "candidate-col" },
            el(
              "p",
              {
                class: "candidate-label",
                text: fits ? "候选版本（适配后）" : "候选版本（强制合片）",
              }
            ),
            ...Array.from({ length: count }, (_, index) =>
              el(
                "div",
                { class: "audio-row" },
                el("span", { class: "audio-tag", text: count > 1 ? String(index + 1) : "" }),
                audioCell(candidatePlay[index] || null, `任务 ${task.number} 候选版本 ${index + 1}`)
              )
            )
          )
        ),
        el(
          "div",
          { class: "btn-row" },
          el("button", {
            class: "btn btn-ghost",
            text: "再生成一次",
            disabled: busy,
            onclick: () => generateTaskCandidate(task.number),
          }),
          el("button", {
            class: "btn btn-ghost",
            text: "LLM 缩短并生成",
            disabled: busy,
            onclick: () => generateOptimizedCandidate(task.number),
          }),
          el("button", {
            class: "btn btn-danger",
            text: candidates.length > 1 ? "放弃此候选" : "保留当前",
            disabled: busy,
            onclick: () => discardTaskCandidate(task.number, candidate.candidate_id),
          }),
          el("button", {
            class: "btn btn-primary",
            text: fits ? "采用候选" : "强制采用",
            disabled: busy,
            onclick: () => acceptTaskCandidate(task.number, candidate.candidate_id),
          })
        )
      )
    )
  );
}

function renderTasks() {
  const data = state.tasks;
  const section = byId("section-tasks");
  if (!data || !data.tasks.length) {
    section.hidden = true;
    state.taskUI = null;
    syncNavAvailability();
    return;
  }
  section.hidden = false;
  syncNavAvailability();

  const tasks = data.tasks;
  const selected = state.taskSelected;
  // Drop selections that no longer exist after rebuild.
  for (const number of [...selected]) {
    if (!tasks.some((task) => task.number === number)) selected.delete(number);
  }
  const busy = jobBusy();
  const overrideCount = tasks.filter((task) => task.has_override).length;
  const regenCount = tasks.filter((task) => task.needs_regen).length;
  const pendingCount = (data.merge_pending || []).length;
  const candidateCount = tasks.reduce(
    (total, task) => total + (task.candidates?.length || (task.candidate ? 1 : 0)),
    0
  );
  const suffix = [
    overrideCount ? `${overrideCount} 手工参考` : null,
    regenCount ? `${regenCount} 缺缓存` : null,
    candidateCount ? `${candidateCount} 候选` : null,
    pendingCount ? `${pendingCount} 待合片` : null,
  ]
    .filter(Boolean)
    .map((part) => ` · ${part}`)
    .join("");

  renderMiniJob("task-job", ["regenerate", "candidate", "remaster", "dub"]);

  const countNode = el("span", { class: "toolbar-count" });
  const headCheck = el("input", {
    type: "checkbox",
    "aria-label": "全选任务",
    disabled: busy,
    onchange: (event) => {
      state.taskSelected = event.target.checked ? new Set(tasks.map((task) => task.number)) : new Set();
      paintSelection(state.taskUI, state.taskSelected);
      syncTaskToolbar();
    },
  });

  const pickRefBtn = el("button", {
    class: "btn btn-ghost",
    text: "批量换参考",
    onclick: () => {
      const selectedTasks = tasks.filter((task) => selected.has(task.number));
      const speakers = [...new Set(selectedTasks.map((task) => task.speaker).filter(Boolean))];
      openRefPicker([...selected], speakers.length === 1 ? speakers[0] : "");
    },
  });
  const restoreBtn = el("button", {
    class: "btn btn-ghost",
    text: "批量恢复参考",
    onclick: () => clearTaskReference([...selected]),
  });
  const regenBtn = el("button", {
    class: "btn btn-ghost",
    onclick: () => regenerateSelectedTasks([...selected]),
  });
  const keepOriginalBtn = el("button", {
    class: "btn btn-ghost",
    text: "批量保留原人声",
    title: "选中任务不走 TTS，合片时该时段播放原人声",
    onclick: () => keepOriginalTasks([...selected]),
  });
  const remasterBtn = el("button", {
    class: "btn btn-primary",
    text: pendingCount ? `重新合片（${pendingCount}）` : "重新合片",
    disabled: busy || !pendingCount,
    onclick: remasterPending,
  });

  state.taskUI = {
    count: countNode,
    headCheck,
    needsSelection: [pickRefBtn, restoreBtn, regenBtn, keepOriginalBtn],
    rows: [],
    total: tasks.length,
    regenBtn,
    remasterBtn,
    pendingCount,
    suffix,
  };

  replace(
    byId("task-toolbar"),
    countNode,
    pickRefBtn,
    el("button", {
      class: "btn btn-ghost",
      text: "按文件名映射上传",
      disabled: busy,
      onclick: async () => {
        const files = await pickFiles("audio/*,.wav,.mp3,.m4a,.flac", true);
        if (files.length) await uploadTaskReference([...selected], files, "mapped");
      },
    }),
    restoreBtn,
    el("span", { class: "sep" }),
    keepOriginalBtn,
    regenBtn,
    remasterBtn
  );

  const head = el(
    "thead",
    {},
    el(
      "tr",
      {},
      el("th", { class: "check", scope: "col" }, headCheck),
      ...["片段", "文本", "音频", "操作"].map((label) =>
        el("th", { scope: "col", text: label })
      )
    )
  );

  const body = el(
    "tbody",
    {},
    tasks.flatMap((task) => {
      const check = el("input", {
        type: "checkbox",
        checked: selected.has(task.number),
        disabled: busy,
        "aria-label": `选择任务 ${task.number}`,
        onchange: (event) => {
          if (event.target.checked) selected.add(task.number);
          else selected.delete(task.number);
          row.classList.toggle("selected", event.target.checked);
          syncTaskToolbar();
        },
      });

      const statusChips = [
        task.has_override
          ? el("span", { class: "chip chip-ok" }, el("span", { class: "chip-dot" }), "手工参考")
          : null,
        task.needs_regen
          ? el("span", { class: "chip chip-warn" }, el("span", { class: "chip-dot" }), "缺缓存")
          : null,
        task.candidate
          ? el(
              "span",
              { class: "chip chip-warn" },
              el("span", { class: "chip-dot" }),
              `${task.candidates?.length || 1} 个候选待审`
            )
          : null,
        task.merge_pending
          ? el("span", { class: "chip chip-ok" }, el("span", { class: "chip-dot" }), "待合片")
          : null,
      ].filter(Boolean);

      const row = el(
        "tr",
        {
          class: [
            selected.has(task.number) ? "selected" : "",
            task.candidate ? "has-candidate" : "",
            task.merge_pending ? "merge-pending" : "",
          ]
            .filter(Boolean)
            .join(" "),
        },
        el("td", { class: "check" }, check),
        el(
          "td",
          { class: "task-meta" },
          el(
            "div",
            { class: "task-meta-id" },
            el("span", { class: "task-meta-num", text: `#${task.number}` }),
            task.source_numbers.length > 1
              ? el("span", { class: "task-meta-src", text: `源 ${task.source_numbers.join("+")}` })
              : null
          ),
          el("div", { class: "task-meta-speaker", text: task.speaker || "未标记" }),
          el("div", {
            class: "task-meta-time",
            text: `${shortTime(task.start_time)} → ${shortTime(task.end_time)}`,
          }),
          el("div", {
            class: "task-meta-dur",
            text: `${task.duration === null ? "—" : task.duration.toFixed(1)}s / ${
              task.real_dur ? `${task.real_dur.toFixed(1)}s` : "—"
            }`,
          })
        ),
        el(
          "td",
          { class: "text" },
          taskTextEditor(task, busy),
          statusChips.length
            ? el("div", { class: "chip-row", style: "margin-top:6px;margin-bottom:0" }, statusChips)
            : null
        ),
        el("td", {}, taskAudioStack(task)),
        el(
          "td",
          { class: "actions" },
          el("button", {
            class: "btn btn-ghost btn-sm",
            text: "换参考",
            disabled: busy,
            "aria-label": `为任务 ${task.number} 更换参考音频`,
            onclick: () => openRefPicker([task.number], task.speaker || ""),
          }),
          el("button", {
            class: "btn btn-ghost btn-sm",
            text: "恢复",
            disabled: busy || !task.has_override,
            "aria-label": `恢复任务 ${task.number} 的自动参考音频`,
            onclick: () => clearTaskReference([task.number]),
          }),
          el("button", {
            class: "btn btn-primary btn-sm",
            text: task.candidate ? "再生成" : "生成候选",
            disabled: busy,
            "aria-label": `为任务 ${task.number} 生成候选配音`,
            onclick: () => generateTaskCandidate(task.number),
          }),
          el("button", {
            class: "btn btn-ghost btn-sm",
            text: "LLM 优化候选",
            disabled: busy,
            "aria-label": `用 LLM 缩短任务 ${task.number} 的字幕并生成候选`,
            onclick: () => generateOptimizedCandidate(task.number),
          }),
          el("button", {
            class: "btn btn-ghost btn-sm",
            text: "保留原人声",
            disabled: busy,
            title: "该任务不走 TTS，合片时播放原人声",
            "aria-label": `任务 ${task.number} 保留原人声`,
            onclick: () => keepOriginalTasks([task.number]),
          })
        )
      );

      state.taskUI.rows.push({ cue: task.number, row, check });
      const detail = candidateCompareRow(task, busy);
      return detail ? [row, detail] : [row];
    })
  );

  replace(
    byId("task-table"),
    el("caption", { class: "sr-only", text: "配音任务清单" }),
    head,
    body
  );
  syncTaskToolbar();
}

function syncTaskToolbar() {
  const ui = state.taskUI;
  if (!ui) return;
  syncSelectionCount(ui, state.taskSelected, (size) => `已选 ${size} / ${ui.total}${ui.suffix}`);
  const size = state.taskSelected.size;
  ui.regenBtn.textContent = size ? `批量重生成并直接应用（${size}）` : "批量重生成并直接应用";
  if (ui.remasterBtn) {
    ui.remasterBtn.textContent = ui.pendingCount ? `重新合片（${ui.pendingCount}）` : "重新合片";
    ui.remasterBtn.disabled = jobBusy() || !ui.pendingCount;
  }
}

// ------------
// Section 07: output
// ------------

function renderOutput() {
  const ws = state.workspace;
  const section = byId("section-output");
  if (!ws || !ws.artifacts.length) {
    section.hidden = true;
    return;
  }
  section.hidden = false;

  const video = ws.artifacts.find((item) => item.label === "配音成片");
  const stale = ws.dubbed && ws.dubbed.stale;
  const subtitleStale = ws.dubbed && ws.dubbed.subtitle_stale;
  const pendingCount = (ws.dubbed && ws.dubbed.merge_pending && ws.dubbed.merge_pending.length) || 0;
  const playerHost = byId("output-player");
  const noticeText = subtitleStale
    ? "字幕结构已修改，当前成片为旧版本。请为新任务生成音频并重新合片。"
    : `成片仍是旧版本（${pendingCount} 条已采用修改尚未合入）。到配音任务区点击「重新合片」。`;

  if (video) {
    const currentPlayer = playerHost.querySelector("video");
    const sameArtifact =
      currentPlayer && currentPlayer.dataset.artifactUrl === video.url;
    if (sameArtifact) {
      const wrapper = currentPlayer.parentElement;
      let notice = wrapper.querySelector(".output-stale-notice");
      if (stale) {
        if (!notice) {
          notice = el("p", {
            class: "notice notice-warn output-stale-notice",
            style: "margin:12px",
          });
          wrapper.insertBefore(notice, currentPlayer);
        }
        notice.textContent = noticeText;
      } else if (notice) {
        notice.remove();
      }
    } else {
      replace(
        playerHost,
        el(
          "div",
          {},
          stale
            ? el("p", {
                class: "notice notice-warn output-stale-notice",
                style: "margin:12px",
                text: noticeText,
              })
            : null,
          el("video", {
            controls: true,
            playsinline: true,
            preload: "metadata",
            src: video.url,
            "data-artifact-url": video.url,
          })
        )
      );
    }
  } else if (!playerHost.querySelector(".empty")) {
    replace(
      playerHost,
      el(
        "div",
        { class: "empty" },
        el("p", { class: "empty-title", text: "还没有成片" }),
        el("p", { class: "empty-note", text: "跑完配音阶段后，合成好的视频会出现在这里。" })
      )
    );
  }

  renderLoudness();

  replace(
    byId("artifact-card"),
    el("p", { class: "card-title", style: "margin-bottom:12px", text: "产物文件" }),
    stale
      ? el("p", { class: "card-note", style: "margin-bottom:12px", text: "下列成片尚未包含最新已采用修改。" })
      : null,
    ...ws.artifacts.map((item) =>
      el(
        "div",
        { class: "artifact" },
        el("span", { class: "artifact-name", text: item.label }),
        el(
          "span",
          { class: "btn-row" },
          el("span", { class: "artifact-size", text: fmtBytes(item.size) }),
          el("a", { class: "btn btn-ghost", href: item.url, download: "" }, "下载")
        )
      )
    )
  );
}

function metric(label, value, target) {
  return el(
    "div",
    { class: "metric" },
    el("span", { class: "metric-label", text: label }),
    el(
      "span",
      {},
      el("span", { class: "metric-value", text: value }),
      target ? el("span", { class: "metric-target", text: ` / 目标 ${target}` }) : null
    )
  );
}

function renderLoudness() {
  const ready = state.workspace && state.workspace.dubbed.video_ready;
  const data = state.loudness;
  replace(
    byId("loudness-card"),
    el("p", { class: "card-title", style: "margin-bottom:12px", text: "成片响度" }),
    data
      ? el(
          "div",
          {},
          metric("整体响度", `${data.integrated_lufs.toFixed(2)} LUFS`, `${data.target_lufs} LUFS`),
          metric("真峰值", `${data.true_peak_dbtp.toFixed(2)} dBTP`, `${data.target_true_peak} dBTP`),
          metric("响度范围", `${data.loudness_range_lu.toFixed(2)} LU`, `${data.target_loudness_range} LU`)
        )
      : el("p", { class: "card-note", text: ready ? "尚未测量。" : "生成成片后可测量。" }),
    el(
      "div",
      { class: "btn-row", style: "margin-top:16px" },
      el("button", {
        class: "btn btn-ghost",
        text: state.loudnessBusy ? "测量中…" : data ? "重新测量" : "测量响度",
        disabled: !ready || state.loudnessBusy,
        onclick: measureLoudness,
      })
    )
  );
}

async function measureLoudness() {
  state.loudnessBusy = true;
  renderLoudness();
  try {
    state.loudness = await api("/api/loudness");
  } catch (error) {
    toast(error.message, "error");
  } finally {
    state.loudnessBusy = false;
    renderLoudness();
  }
}

// ------------
// Hero, nav, footer
// ------------

function fmtMoney(value, currency) {
  const amount = Number(value) || 0;
  if (currency === "USD") return `$${amount.toFixed(amount < 0.01 && amount > 0 ? 4 : 2)}`;
  return `¥${amount.toFixed(amount < 0.01 && amount > 0 ? 4 : 2)}`;
}

function renderUsage() {
  const chip = byId("usage-chip");
  if (!chip) return;
  const usage = state.usage || {};
  const gemini = usage.gemini || {};
  const qwen = usage.qwen || {};
  const geminiUsd = Number(gemini.cost_usd) || 0;
  const qwenCny = Number(qwen.cost_cny) || 0;
  const geminiTokens = Number(gemini.total_tokens) || 0;
  const qwenSeconds = Number(qwen.seconds) || 0;
  chip.title = [
    usage.note || "用量来自 API 返回；金额按官方标价估算",
    `Gemini ${gemini.calls || 0} 次 · ${geminiTokens} tokens`,
    `Qwen ${qwen.calls || 0} 次 · ${qwenSeconds.toFixed(1)}s 音频`,
    `约合 ¥${(Number(usage.total_cny_approx) || 0).toFixed(2)}`,
  ].join("\n");
  chip.textContent = `Gemini ${fmtMoney(geminiUsd, "USD")} · Qwen ${fmtMoney(qwenCny, "CNY")}`;
}

function renderHero() {
  const ws = state.workspace;
  if (!ws) return;
  const usage = state.usage || {};
  const geminiUsd = Number(usage.gemini?.cost_usd) || 0;
  const qwenCny = Number(usage.qwen?.cost_cny) || 0;
  const stats = [
    ["MEDIA", ws.media ? fmtClock(ws.media.duration) : "—"],
    ["CUES", ws.prepared.cue_count || (ws.uploads.trans ? ws.uploads.trans.cue_count : 0) || "—"],
    ["TTS TASKS", ws.dubbed.segment_count || ws.prepared.refer_count || "—"],
    ["ENGINE", engineLabel()],
    ["GEMINI", fmtMoney(geminiUsd, "USD")],
    ["QWEN", fmtMoney(qwenCny, "CNY")],
  ];
  replace(
    byId("hero-stats"),
    stats.map(([label, value]) =>
      el(
        "div",
        {},
        el("p", { class: "hero-stat-label", text: label }),
        el("p", { class: "hero-stat-value", text: String(value) })
      )
    )
  );
}

function engineLabel() {
  const method = state.workspace ? state.workspace.tts_method : null;
  const group = state.config && state.config.groups.find((item) => item.id === "engine");
  const options = group ? group.fields[0].options : [];
  const found = options.find(([value]) => value === method);
  return found ? found[1] : method || "—";
}

// Sections appear as the pipeline progresses; dim the links that lead nowhere.
function syncNavAvailability() {
  for (const link of document.querySelectorAll("#nav-links a")) {
    const target = byId(link.getAttribute("href").slice(1));
    const off = !target || target.hidden;
    link.classList.toggle("is-off", off);
    link.setAttribute("aria-disabled", off ? "true" : "false");
  }
}

function setupScrollSpy() {
  const links = [...document.querySelectorAll("#nav-links a")];
  const sections = links.map((link) => byId(link.getAttribute("href").slice(1))).filter(Boolean);
  const visible = new Set();
  const observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting) visible.add(entry.target.id);
        else visible.delete(entry.target.id);
      }
      const active = sections.find((section) => visible.has(section.id));
      for (const link of links) {
        const on = active && link.getAttribute("href") === `#${active.id}`;
        if (on) link.setAttribute("aria-current", "true");
        else link.removeAttribute("aria-current");
      }
    },
    { rootMargin: "-80px 0px -55% 0px" }
  );
  for (const section of sections) observer.observe(section);
}

function renderNav() {
  syncNavAvailability();
  const chip = byId("nav-chip");
  const job = state.job;
  if (!job || job.state === "idle") {
    chip.hidden = true;
    return;
  }
  const labels = {
    running: ["chip chip-run", "运行中"],
    paused: ["chip chip-warn", "已暂停"],
    completed: ["chip chip-ok", "已完成"],
    stopped: ["chip chip-warn", "已停止"],
    error: ["chip chip-err", "失败"],
  };
  const [cls, text] = labels[job.state] || ["chip", job.state];
  chip.hidden = false;
  chip.className = cls;
  replace(chip, el("span", { class: "chip-dot" }), `${text} · ${fmtSecs(job.elapsed)}`);
}

function renderFooter() {
  byId("footer-engine").textContent = `当前引擎 ${engineLabel()}`;
}

// ------------
// Data flow
// ------------

async function refreshConfig() {
  state.config = await api("/api/config");
  renderConfig();
  renderSecrets();
  renderFooter();
}

async function refreshStages() {
  try {
    state.stages = (await api("/api/stages")).stages;
  } catch (error) {
    toast(error.message, "error");
    return;
  }
  renderStages();
}

async function refreshTables() {
  try {
    [state.speakers, state.tasks] = await Promise.all([api("/api/speakers"), api("/api/tasks")]);
  } catch (error) {
    toast(error.message, "error");
    return;
  }
  // Speaker draft is reset only when cue set changes (handled in ensureSpeakerDraft).
  await refreshAlignment();
  renderSpeakers();
  renderTasks();
}

async function refreshStatus() {
  const payload = await api("/api/status");
  const previous = state.job;
  state.workspace = payload.workspace;
  state.job = payload.job;
  state.usage = payload.usage || null;

  renderHero();
  renderUsage();
  renderNav();
  renderUploads();
  renderStages();
  renderOutput();
  renderFooter();

  const jobKey = `${state.job.name}:${state.job.state}`;
  const jobChanged = jobKey !== state.lastJobKey;
  const taskJobs = [
    "rebuild_speakers",
    "regenerate",
    "candidate",
    "remaster",
    "dub",
    "prepare",
    "alignment_apply",
    "alignment_skip",
  ];
  // Only rebuild editable tables when job activity changes, so inputs keep focus.
  if (jobChanged || (state.job && taskJobs.includes(state.job.name) && jobBusy())) {
    renderMiniJob("speaker-job", ["rebuild_speakers"]);
    renderMiniJob("task-job", ["regenerate", "candidate", "remaster", "dub"]);
    renderMiniJob("alignment-job", ["alignment_apply", "alignment_skip"]);
    renderAlignment();
  }

  if (jobChanged) {
    state.lastJobKey = jobKey;
    const finished =
      previous &&
      (previous.state === "running" || previous.state === "paused") &&
      !["running", "paused"].includes(state.job.state);
    if (finished) {
      if (state.job.name === "rebuild_speakers") {
        state.speakerDraft = null;
        state.pendingKeepOriginal = [];
      }
      await refreshTables();
      await refreshConfig();
      if (state.job.state === "completed") {
        if (state.job.name === "dub" || state.job.name === "regenerate" || state.job.name === "remaster") {
          state.loudness = null;
          measureLoudness();
          const messages = {
            regenerate: `批量重生成完成，耗时 ${fmtSecs(state.job.elapsed)}`,
            remaster: `重新合片完成，耗时 ${fmtSecs(state.job.elapsed)}`,
            dub: `配音完成，耗时 ${fmtSecs(state.job.elapsed)}`,
          };
          toast(messages[state.job.name]);
        } else if (state.job.name === "candidate") {
          toast(`候选配音已就绪，可试听对比（${fmtSecs(state.job.elapsed)}）`);
        } else if (state.job.name === "prepare") {
          await refreshStages();
          const pending = state.workspace && state.workspace.alignment && state.workspace.alignment.decision_pending;
          toast(
            pending
              ? `准备完成，请选择是否修复时间轴（${fmtSecs(state.job.elapsed)}）`
              : `准备完成，耗时 ${fmtSecs(state.job.elapsed)}`
          );
        } else if (state.job.name === "alignment_apply") {
          toast(`时间轴已按对齐修复，任务已重建（${fmtSecs(state.job.elapsed)}）`);
        } else if (state.job.name === "alignment_skip") {
          toast(`已保持原时间轴，任务已生成（${fmtSecs(state.job.elapsed)}）`);
        } else if (state.job.name === "rebuild_speakers") {
          toast(`人物修改已应用，任务已重建（${fmtSecs(state.job.elapsed)}）`);
        }
      }
    } else if (jobBusy()) {
      // Entering a busy state: disable table controls once.
      if (state.speakers) renderSpeakers();
      if (state.tasks) renderTasks();
    }
  }
}

let pollTimer = null;

function schedulePoll(immediate) {
  clearTimeout(pollTimer);
  const active = state.job && (state.job.state === "running" || state.job.state === "paused");
  const delay = immediate ? 200 : active ? 1000 : 5000;
  pollTimer = setTimeout(async () => {
    try {
      await refreshStatus();
    } catch (error) {
      /* transient: keep polling */
    }
    schedulePoll(false);
  }, delay);
}

byId("reset-btn").addEventListener("click", (event) =>
  withBusy(event.currentTarget, async () => {
    const ok = await askModal({
      title: "归档并重置工作区",
      note: "当前 output/ 会被移到 history/，字幕、人物标记和配音产物都会从工作区清空。",
      confirmText: "归档并清空",
      danger: true,
    });
    if (!ok) return;
    try {
      await sendJSON("/api/reset", "POST");
      state.speakers = null;
      state.tasks = null;
      state.loudness = null;
      state.speakerDraft = null;
      state.speakerSelected = new Set();
      state.taskSelected = new Set();
      state.customSpeakers = [];
      renderSpeakers();
      renderTasks();
      await refreshStatus();
      toast("工作区已归档");
    } catch (error) {
      toast(error.message, "error");
    }
  })
);

(async function boot() {
  setupModal();
  setupRefPicker();
  setupScrollSpy();
  skeletonCards("upload-grid", 3);
  skeletonCards("secret-grid", 3);
  skeletonCards("config-grid", 2);
  skeletonCards("stage-grid", 2);
  try {
    state.stages = (await api("/api/stages")).stages;
    await refreshConfig();
    await refreshStatus();
    await refreshTables();
  } catch (error) {
    toast(error.message, "error");
  }
  schedulePoll(false);
})();
