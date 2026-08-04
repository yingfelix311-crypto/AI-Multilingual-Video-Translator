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

function toast(message, kind) {
  const node = el("div", { class: kind === "error" ? "toast toast-error" : "toast", text: message });
  byId("toasts").append(node);
  setTimeout(() => node.remove(), kind === "error" ? 9000 : 4000);
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
  loudness: null,
  loudnessBusy: false,
  lastJobKey: null,
};

const cfg = (key) => (state.config ? state.config.values[key] : undefined);

// ------------
// Section 01: uploads
// ------------

const UPLOADS = [
  {
    id: "media",
    eyebrow: "SOURCE MEDIA",
    title: "原视频 / 音频",
    hint: "拖入或点击选择。上传新文件会替换掉工作区里的旧素材。",
    accept: "video/*,audio/*",
    url: "/api/upload/media",
  },
  {
    id: "trans",
    eyebrow: "TRANSLATED SRT",
    title: "译文字幕",
    hint: "配音用的目标语言字幕，必填。",
    accept: ".srt",
    url: "/api/upload/srt?kind=trans",
    removable: "/api/upload/srt?kind=trans",
  },
  {
    id: "src",
    eyebrow: "SOURCE SRT",
    title: "原文字幕",
    hint: "可选。缺省时用译文镜像，只影响日志里的对照文本。",
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
        ws.media.duration ? `时长 ${fmtClock(ws.media.duration)}` : null,
        fmtBytes(ws.media.size),
      ],
    };
  }
  const upload = ws.uploads[card.id];
  if (!upload) return null;
  return {
    name: card.id === "trans" ? "译文 SRT 已就绪" : "原文 SRT 已就绪",
    meta: [`${upload.cue_count} 条字幕`, upload.last_end ? `末条 ${shortTime(upload.last_end)}` : null],
  };
}

function renderUploads() {
  replace(
    byId("upload-grid"),
    UPLOADS.map((card) => {
      const summary = uploadSummary(card);
      const input = el("input", {
        type: "file",
        accept: card.accept,
        onchange: (event) => {
          const file = event.target.files[0];
          if (file) doUpload(card, file);
          event.target.value = "";
        },
      });

      const node = el(
        "div",
        {
          class: "card drop",
          ondragover: (event) => {
            event.preventDefault();
            node.classList.add("is-over");
          },
          ondragleave: () => node.classList.remove("is-over"),
          ondrop: (event) => {
            event.preventDefault();
            node.classList.remove("is-over");
            const file = event.dataTransfer.files[0];
            if (file) doUpload(card, file);
          },
        },
        el("p", { class: "eyebrow", text: card.eyebrow }),
        el(
          "div",
          { class: "drop-body" },
          el("p", { class: "card-title", text: card.title }),
          summary
            ? el(
                "div",
                {},
                el("p", { class: "drop-name", text: summary.name }),
                el("p", { class: "drop-meta", text: summary.meta.filter(Boolean).join(" · ") })
              )
            : el("p", { class: "drop-empty", text: card.hint })
        ),
        el(
          "div",
          { class: "btn-row" },
          el("button", { class: "btn btn-ghost", text: summary ? "更换文件" : "选择文件", onclick: () => input.click() }),
          summary && card.removable
            ? el("button", { class: "btn btn-danger", text: "移除", onclick: () => doRemove(card) })
            : null,
          input
        )
      );
      return node;
    })
  );
}

async function doUpload(card, file) {
  const form = new FormData();
  form.append("file", file);
  try {
    toast(`正在上传 ${file.name}…`);
    await api(card.url, { method: "POST", body: form });
    await refreshStatus();
    toast(`${file.name} 上传完成`);
  } catch (error) {
    toast(error.message, "error");
  }
}

async function doRemove(card) {
  try {
    await api(card.removable, { method: "DELETE" });
    await refreshStatus();
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
      const input = el("input", { type: "password", placeholder: secret.configured ? "已配置，可覆盖" : "粘贴密钥" });
      const save = async () => {
        if (!input.value.trim()) return;
        try {
          await sendJSON("/api/secrets", "POST", { name: secret.name, value: input.value });
          input.value = "";
          await refreshConfig();
          toast(`${secret.label} 已写入 ${secret.key_file}`);
        } catch (error) {
          toast(error.message, "error");
        }
      };
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
        el("div", { class: "btn-row", style: "margin-top:16px" }, input, el("button", { class: "btn btn-primary", text: "保存", onclick: save })
        )
      );
    })
  );
}

// ------------
// Section 03: config
// ------------

function fieldControl(field) {
  const value = cfg(field.key);
  const commit = async (next) => {
    try {
      const result = await sendJSON("/api/config", "PATCH", { [field.key]: next });
      state.config = result;
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
      { onchange: (event) => commit(event.target.value) },
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
            onchange: (event) => {
              const next = rows.map((row) => [...row]);
              next[index][0] = Number(event.target.value);
              submit(next);
            },
          }),
          el("span", { class: "interval-sep", text: "→" }),
          el("input", {
            type: "number",
            step: 0.01,
            min: 0,
            value: pair[1],
            onchange: (event) => {
              const next = rows.map((row) => [...row]);
              next[index][1] = Number(event.target.value);
              submit(next);
            },
          }),
          el("button", {
            class: "btn btn-danger",
            text: "删除",
            onclick: () => submit(rows.filter((_, i) => i !== index)),
          })
        )
      ),
      el("button", {
        class: "btn btn-ghost",
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
    onchange: (event) => commit(event.target.value),
  });
}

function renderConfig() {
  if (!state.config) return;
  const visible = state.config.groups.filter(
    (group) => !group.when || String(cfg(group.when[0])) === group.when[1]
  );
  replace(
    byId("config-grid"),
    visible.map((group) =>
      el(
        "div",
        { class: "card" },
        el("p", { class: "eyebrow", text: group.eyebrow }),
        el("p", { class: "card-title", style: "margin-top:8px", text: group.title }),
        group.desc ? el("p", { class: "card-note", style: "margin:8px 0 8px", text: group.desc }) : null,
        el(
          "div",
          { style: "margin-top:8px" },
          group.fields.map((field) =>
            el(
              "div",
              { class: "field" },
              el("span", { class: "field-label", text: field.label }),
              el("span", { class: "field-control" }, fieldControl(field))
            )
          )
        )
      )
    )
  );
}

// ------------
// Section 04: stages
// ------------

function stageReadiness(stage) {
  const ws = state.workspace;
  if (!ws) return { ready: false, reason: "读取工作区…", done: false };
  if (stage.name === "prepare") {
    if (!ws.media) return { ready: false, reason: "先上传原视频", done: false };
    if (!ws.uploads.trans) return { ready: false, reason: "先上传译文 SRT", done: false };
    return { ready: true, done: ws.prepared.tasks_ready && ws.prepared.refer_count > 0 };
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
  const busy = job && (job.state === "running" || job.state === "paused");

  replace(
    byId("stage-grid"),
    state.stages.map((stage) => {
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
            "div",
            {},
            el("p", { class: "eyebrow", text: stage.eyebrow }),
            el("p", { class: "card-title", style: "margin-top:8px", text: stage.title })
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

function renderSpeakers() {
  const data = state.speakers;
  const section = byId("section-speakers");
  if (!data || !data.cues.length) {
    section.hidden = true;
    return;
  }
  section.hidden = false;

  const chips = [
    el(
      "span",
      { class: "chip chip-ok" },
      el("span", { class: "chip-dot" }),
      `${data.cues.length} 条字幕 → ${data.groups} 次 TTS`
    ),
    ...data.speakers.map((speaker) =>
      el("span", { class: "chip" }, el("span", { class: "chip-dot" }), `${speaker.name} · ${speaker.cues}`)
    ),
  ];
  if (data.stale) {
    chips.push(el("span", { class: "chip chip-warn" }, el("span", { class: "chip-dot" }), "标记与当前字幕不匹配"));
  }
  if (!data.speakers.length) {
    chips.push(el("span", { class: "chip chip-warn" }, el("span", { class: "chip-dot" }), "未启用人物标记"));
  }
  replace(byId("speaker-summary"), chips);

  const head = el(
    "thead",
    {},
    el(
      "tr",
      {},
      ["#", "时间", "人物", "置信度", "合并", "字幕"].map((label) => el("th", { text: label }))
    )
  );

  const body = el(
    "tbody",
    {},
    data.cues.map((cue) =>
      el(
        "tr",
        { class: cue.merge_with_previous ? "merged" : "" },
        el("td", { class: "num", text: cue.cue }),
        el("td", { class: "num", text: `${shortTime(cue.start)} → ${shortTime(cue.end)}` }),
        el("td", { text: cue.speaker || "—" }),
        el("td", { class: "num", text: cue.confidence === null || cue.confidence === undefined ? "—" : cue.confidence.toFixed(2) }),
        el("td", { class: "num", text: cue.merge_with_previous ? "并入上一条" : "—" }),
        el(
          "td",
          { class: "text" },
          el("div", { text: cue.text }),
          cue.origin && cue.origin !== cue.text ? el("div", { class: "sub", text: cue.origin }) : null
        )
      )
    )
  );

  replace(byId("speaker-table"), head, body);
}

// ------------
// Section 06: tasks
// ------------

function audioCell(entry) {
  if (!entry) return el("span", { class: "skeleton", text: "—" });
  return el("audio", { controls: true, preload: "none", src: entry.url });
}

function renderTasks() {
  const data = state.tasks;
  const section = byId("section-tasks");
  if (!data || !data.tasks.length) {
    section.hidden = true;
    return;
  }
  section.hidden = false;

  const head = el(
    "thead",
    {},
    el(
      "tr",
      {},
      ["#", "来源", "人物", "时间", "字幕/实际", "文本", "参考音频", "配音片段"].map((label) =>
        el("th", { text: label })
      )
    )
  );

  const body = el(
    "tbody",
    {},
    data.tasks.map((task) =>
      el(
        "tr",
        {},
        el("td", { class: "num", text: task.number }),
        el("td", { class: "num", text: task.source_numbers.join("+") }),
        el("td", { text: task.speaker || "—" }),
        el("td", { class: "num", text: `${shortTime(task.start_time)} → ${shortTime(task.end_time)}` }),
        el("td", {
          class: "num",
          text: `${task.duration === null ? "—" : task.duration.toFixed(1)}s / ${
            task.real_dur ? `${task.real_dur.toFixed(1)}s` : "—"
          }`,
        }),
        el(
          "td",
          { class: "text" },
          el("div", { text: task.text }),
          task.origin && task.origin !== task.text ? el("div", { class: "sub", text: task.origin }) : null
        ),
        el("td", {}, audioCell(task.refer)),
        el("td", {}, task.segments.length ? task.segments.map(audioCell) : audioCell(null))
      )
    )
  );

  replace(byId("task-table"), head, body);
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
  replace(
    byId("output-player"),
    video
      ? el("video", { controls: true, src: `${video.url}?v=${video.size}` })
      : el("div", { style: "padding:24px" }, el("p", { class: "skeleton", text: "还没有成片。" }))
  );

  renderLoudness();

  replace(
    byId("artifact-card"),
    el("p", { class: "eyebrow", text: "ARTIFACTS" }),
    el("p", { class: "card-title", style: "margin:8px 0 12px", text: "产物文件" }),
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
    el("p", { class: "eyebrow", text: "LOUDNESS" }),
    el("p", { class: "card-title", style: "margin:8px 0 12px", text: "成片响度" }),
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

function renderHero() {
  const ws = state.workspace;
  if (!ws) return;
  const stats = [
    ["MEDIA", ws.media ? fmtClock(ws.media.duration) : "—"],
    ["CUES", ws.prepared.cue_count || (ws.uploads.trans ? ws.uploads.trans.cue_count : 0) || "—"],
    ["TTS TASKS", ws.dubbed.segment_count || ws.prepared.refer_count || "—"],
    ["ENGINE", engineLabel()],
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

function renderNav() {
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

async function refreshTables() {
  try {
    [state.speakers, state.tasks] = await Promise.all([api("/api/speakers"), api("/api/tasks")]);
  } catch (error) {
    toast(error.message, "error");
    return;
  }
  renderSpeakers();
  renderTasks();
}

async function refreshStatus() {
  const payload = await api("/api/status");
  const previous = state.job;
  state.workspace = payload.workspace;
  state.job = payload.job;

  renderHero();
  renderNav();
  renderUploads();
  renderStages();
  renderOutput();

  const jobKey = `${state.job.name}:${state.job.state}`;
  if (jobKey !== state.lastJobKey) {
    state.lastJobKey = jobKey;
    if (previous && previous.state === "running" && state.job.state !== "running") {
      await refreshTables();
      await refreshConfig();
      if (state.job.name === "dub" && state.job.state === "completed") {
        state.loudness = null;
        measureLoudness();
        toast(`配音完成，耗时 ${fmtSecs(state.job.elapsed)}`);
      }
      if (state.job.state === "completed" && state.job.name === "prepare") {
        toast(`准备完成，耗时 ${fmtSecs(state.job.elapsed)}`);
      }
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

byId("reset-btn").addEventListener("click", async () => {
  if (!confirm("把当前 output/ 归档到 history/ 并清空工作区？")) return;
  try {
    await sendJSON("/api/reset", "POST");
    state.speakers = null;
    state.tasks = null;
    state.loudness = null;
    renderSpeakers();
    renderTasks();
    await refreshStatus();
    toast("工作区已归档");
  } catch (error) {
    toast(error.message, "error");
  }
});

(async function boot() {
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
