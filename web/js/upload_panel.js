// "Uploads" button in ComfyUI's top action bar (the official actionBarButtons extension API): a badge
// shows how many files are left and the overall progress; clicking opens a popup with every
// background upload, whichever workflow is open and even if its node was deleted. Data:
// GET /snacknodes/uploads and the "snacknodes.upload" websocket events of the upload queue
// (cloud_drive/uploads.py).
//
// The registered button object is not reactive (extensions are markRaw), so the badge is a small
// element added to the rendered button and refreshed on every event and every few seconds.
import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";


const zh = () => {
  const locale = app.ui?.settings?.getSettingValue?.("Comfy.Locale") || navigator.language || "";
  return locale.toLowerCase().startsWith("zh");
};
const T = (z, e) => (zh() ? z : e);
const tr = (pair) => (pair ? (zh() ? pair.zh : pair.en) || pair.en || "" : "");

const CSS = `
.snack-up-pop{position:fixed;z-index:3000;width:min(390px,calc(100vw - 16px));max-height:72vh;display:flex;
  background:var(--comfy-menu-bg,#1e1e1e);border:1px solid var(--border-color,#444);border-radius:10px;
  box-shadow:0 12px 40px rgba(0,0,0,.45);overflow:hidden}
.snack-up-pop .snack-up{max-height:72vh;width:100%}
.snack-up-badge{margin-left:6px;font-size:11px;padding:0 6px;border-radius:999px;background:#2f6fde;color:#fff;line-height:16px}
.snack-up-badge.failed{background:#d9534f}
.snack-up{display:flex;flex-direction:column;height:100%;font:13px/1.45 sans-serif;color:var(--fg-color,#ddd)}
.snack-up-head{padding:12px 14px;border-bottom:1px solid var(--border-color,#444);display:flex;flex-direction:column;gap:8px}
.snack-up-head h3{margin:0;font-size:15px;font-weight:600}
.snack-up-sum{display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap}
.snack-up-list{flex:1;overflow:auto;padding:8px 10px;display:flex;flex-direction:column;gap:8px}
.snack-up-empty{opacity:.65;padding:24px 8px;text-align:center}
.snack-up-job{border:1px solid var(--border-color,#444);border-radius:8px;padding:9px 10px;display:flex;flex-direction:column;gap:6px;
  background:var(--comfy-input-bg,rgba(255,255,255,.03))}
.snack-up-row{display:flex;align-items:center;justify-content:space-between;gap:8px}
.snack-up-where{font-weight:600;word-break:break-all}
.snack-up-chip{font-size:11px;padding:1px 7px;border-radius:999px;white-space:nowrap;border:1px solid currentColor}
.snack-up-chip.running{color:#4ea1ff}.snack-up-chip.queued{color:#a0a0a0}.snack-up-chip.waiting{color:#e0a030}
.snack-up-chip.failed{color:#ff6b6b}.snack-up-chip.done{color:#4cc38a}
.snack-up-bar{height:6px;border-radius:3px;background:rgba(128,128,128,.25);overflow:hidden}
.snack-up-bar>div{height:100%;background:#4ea1ff;transition:width .3s}
.snack-up-bar.failed>div{background:#ff6b6b}.snack-up-bar.done>div{background:#4cc38a}
.snack-up-meta{opacity:.75;font-size:12px}
.snack-up-err{color:#ff8a80;font-size:12px;white-space:pre-wrap;word-break:break-word}
.snack-up-files{display:flex;flex-direction:column;gap:3px;font-size:12px}
.snack-up-file{display:flex;align-items:center;gap:6px;min-width:0}
.snack-up-file span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1;min-width:0}
.snack-up-file a{color:#4ea1ff}
.snack-up button{background:transparent;color:inherit;border:1px solid var(--border-color,#666);border-radius:6px;
  padding:3px 10px;font:inherit;font-size:12px;cursor:pointer}
.snack-up button:hover{background:rgba(128,128,128,.15)}
.snack-up button.link{border:none;padding:0 4px;color:#4ea1ff}
.snack-up-actions{display:flex;gap:6px;flex-wrap:wrap}
`;

function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") el.className = v;
    else if (k === "style") el.style.cssText = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (v !== false && v !== null && v !== undefined) el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) if (c !== null && c !== undefined && c !== false) el.append(c);
  return el;
}

const mb = (n) => (n >= 1073741824 ? `${(n / 1073741824).toFixed(2)} GB` : `${(n / 1048576).toFixed(1)} MB`);

function duration(seconds) {
  if (!isFinite(seconds) || seconds <= 0) return "";
  if (seconds < 60) return T(`${Math.ceil(seconds)} 秒`, `${Math.ceil(seconds)}s`);
  if (seconds < 3600) return T(`${Math.ceil(seconds / 60)} 分钟`, `${Math.ceil(seconds / 60)} min`);
  const hrs = Math.floor(seconds / 3600);
  const min = Math.round((seconds % 3600) / 60);
  return T(`${hrs} 小时 ${min} 分`, `${hrs} h ${min} min`);
}

const STATE = {
  queued: ["排队中", "Queued"], running: ["上传中", "Uploading"], waiting: ["等待重试", "Retrying soon"],
  failed: ["失败", "Failed"], done: ["已完成", "Done"],
};

class Panel {
  constructor() {
    this.jobs = new Map();      // id -> snapshot
    this.speed = new Map();     // id -> [{t, sent}] samples for speed / time left
    this.summary = null;
    this.root = null;
    this.frame = 0;
  }

  // ---- data ----------------------------------------------------------------------------------
  async load() {
    try {
      const resp = await api.fetchApi("/snacknodes/uploads");
      if (!resp.ok) return;
      const data = await resp.json();
      this.jobs = new Map((data.jobs || []).map((j) => [j.id, j]));
      this.summary = data.summary;
      this.update();
    } catch { /* server without the upload queue */ }
  }

  onEvent(detail) {
    const job = detail?.job;
    if (!job) return;
    if (detail.type === "cancelled") this.jobs.delete(job.id);
    else this.jobs.set(job.id, job);
    if (detail.summary) this.summary = detail.summary;
    const samples = this.speed.get(job.id) || [];
    samples.push({ t: Date.now() / 1000, sent: job.sent });
    while (samples.length > 2 && samples[samples.length - 1].t - samples[0].t > 15) samples.shift();
    this.speed.set(job.id, samples);
    this.update();
  }

  rate(job) {
    const s = this.speed.get(job.id) || [];
    if (job.state !== "running" || s.length < 2) return 0;
    const dt = s[s.length - 1].t - s[0].t;
    return dt > 0 ? Math.max(0, (s[s.length - 1].sent - s[0].sent) / dt) : 0;
  }

  active() {
    return [...this.jobs.values()].filter((j) => ["queued", "running", "waiting"].includes(j.state));
  }

  update() {
    this.updateBadge();
    if (!this.root || this.frame) return;
    this.frame = requestAnimationFrame(() => { this.frame = 0; this.draw(); });
  }

  updateBadge() {
    const active = this.active();
    const left = active.reduce((n, j) => n + j.files.filter((f) => f.state !== "done").length, 0);
    const total = active.reduce((n, j) => n + j.total, 0);
    const sent = active.reduce((n, j) => n + j.sent, 0);
    const failed = [...this.jobs.values()].some((j) => j.state === "failed");
    const text = left ? `${left} · ${total ? Math.floor((100 * sent) / total) : 0}%` : failed ? "!" : "";
    const button = findButton();
    if (!button) return;
    let badge = button.querySelector(".snack-up-badge");
    if (!badge) {
      badge = h("span", { class: "snack-up-badge" });
      button.append(badge);
    }
    badge.textContent = text;
    badge.className = "snack-up-badge" + (!left && failed ? " failed" : "");
    badge.style.display = text ? "" : "none";
  }

  toggle(event) {
    if (this.pop) return this.close();
    const anchor = event?.currentTarget instanceof Element ? event.currentTarget : findButton();
    const rect = anchor?.getBoundingClientRect?.() || { left: window.innerWidth - 400, bottom: 48, right: window.innerWidth - 8 };
    const width = Math.min(390, window.innerWidth - 16);
    const left = Math.max(8, Math.min(rect.right - width, window.innerWidth - width - 8));
    this.pop = h("div", { class: "snack-up-pop", style: `top:${Math.round(rect.bottom + 8)}px;left:${Math.round(left)}px` });
    document.body.append(this.pop);
    this.mount(this.pop);
    this.outside = (ev) => {
      if (this.pop && !this.pop.contains(ev.target) && !findButton()?.contains(ev.target)) this.close();
    };
    this.escape = (ev) => { if (ev.key === "Escape") this.close(); };
    setTimeout(() => {
      document.addEventListener("mousedown", this.outside, true);
      document.addEventListener("keydown", this.escape, true);
    }, 0);
  }

  close() {
    document.removeEventListener("mousedown", this.outside, true);
    document.removeEventListener("keydown", this.escape, true);
    this.pop?.remove();
    this.pop = null;
    this.unmount();
  }

  async post(path, okText) {
    try {
      const resp = await api.fetchApi(`/snacknodes/uploads/${path}`, { method: "POST" });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) throw data.error || { zh: `HTTP ${resp.status}`, en: `HTTP ${resp.status}` };
      if (okText) app.extensionManager?.toast?.add?.({ severity: "info", summary: okText, life: 2500 });
      if (data.job?.state === "cancelled") this.jobs.delete(data.job.id);
      else if (data.job) this.jobs.set(data.job.id, data.job);
      if (path === "clear") await this.load();
      this.update();
    } catch (e) {
      app.extensionManager?.toast?.add?.({ severity: "error", summary: T("操作失败", "Failed"), detail: tr(e), life: 6000 });
    }
  }

  // ---- view ----------------------------------------------------------------------------------
  mount(el) {
    addStyle();
    this.root = h("div", { class: "snack-up" });
    el.replaceChildren(this.root);
    this.draw();
    this.load();
  }

  unmount() {
    this.root = null;
  }

  draw() {
    if (!this.root) return;
    const jobs = [...this.jobs.values()].sort((a, b) => (b.created || 0) - (a.created || 0));
    const active = this.active();
    const left = active.reduce((n, j) => n + j.files.filter((f) => f.state !== "done").length, 0);
    const bytes = active.reduce((n, j) => n + Math.max(0, j.total - j.sent), 0);
    const speed = active.reduce((n, j) => n + this.rate(j), 0);
    const anyDone = jobs.some((j) => j.state === "done");
    const head = h("div", { class: "snack-up-head" },
      h("h3", {}, T("上传队列", "Uploads")),
      h("div", { class: "snack-up-sum" },
        h("span", {}, left
          ? T(`还剩 ${left} 个文件 · ${mb(bytes)}`, `${left} file(s) left · ${mb(bytes)}`) +
            (speed ? ` · ${mb(speed)}/s` + (bytes ? T(` · 约 ${duration(bytes / speed)}`, ` · ~${duration(bytes / speed)}`) : "") : "")
          : T("没有进行中的上传", "Nothing uploading")),
        anyDone ? h("button", { onclick: () => this.post("clear") }, T("清除已完成", "Clear finished")) : null),
      this.summary && active.length && !this.summary.worker_alive
        ? h("div", { class: "snack-up-err" }, T("后台上传没有在运行，ComfyUI 重启后会继续。", "Background uploads are not running; they continue when ComfyUI restarts."))
        : null);
    const list = h("div", { class: "snack-up-list" },
      jobs.length ? jobs.map((j) => this.jobCard(j))
        : h("div", { class: "snack-up-empty" }, T("「保存到网盘」节点在后台上传的文件会显示在这里。",
          "Files that Save to Cloud Drive uploads in the background show up here.")));
    this.root.replaceChildren(head, list);
  }

  jobCard(job) {
    const files = job.files || [];
    const doneFiles = files.filter((f) => f.state === "done").length;
    const pct = job.total ? Math.min(100, Math.floor((100 * job.sent) / job.total)) : 0;
    const rate = this.rate(job);
    const meta = [T(`${doneFiles}/${files.length} 个文件`, `${doneFiles}/${files.length} file(s)`),
      `${mb(job.sent)} / ${mb(job.total)}`];
    if (rate) meta.push(`${mb(rate)}/s`, T(`剩余约 ${duration((job.total - job.sent) / rate)}`, `~${duration((job.total - job.sent) / rate)} left`));
    if (job.state === "waiting" && job.next_try) {
      meta.push(T(`${new Date(job.next_try * 1000).toLocaleTimeString(zh() ? "zh-CN" : undefined)} 自动重试（第 ${job.attempts} 次）`,
        `retrying at ${new Date(job.next_try * 1000).toLocaleTimeString(zh() ? "zh-CN" : undefined)} (attempt ${job.attempts})`));
    }
    if (job.created) meta.push(new Date(job.created * 1000).toLocaleString(zh() ? "zh-CN" : undefined));
    const running = files.find((f) => f.state === "running");
    const [stateZh, stateEn] = STATE[job.state] || [job.state, job.state];
    const actions = [];
    if (job.state === "failed") actions.push(h("button", { onclick: () => this.post(`${job.id}/retry`, T("已重新加入队列", "Queued again")) }, T("重试", "Retry")));
    if (["failed", "queued", "waiting"].includes(job.state)) {
      actions.push(h("button", { onclick: () => {
        if (confirm(T("取消这次上传？为上传保留的临时文件会被删除（「保留本地副本」的文件不受影响）。",
          "Cancel this upload? Files kept only for uploading are deleted (kept local copies stay)."))) this.post(`${job.id}/cancel`);
      } }, T("取消", "Cancel")));
    }
    return h("div", { class: "snack-up-job" },
      h("div", { class: "snack-up-row" },
        h("span", { class: "snack-up-where" }, `${job.encrypt ? "🔒 " : ""}${job.provider_label} / ${job.remote_folder}`),
        h("span", { class: `snack-up-chip ${job.state}` }, T(stateZh, stateEn))),
      h("div", { class: `snack-up-bar ${job.state}` }, h("div", { style: `width:${job.state === "done" ? 100 : pct}%` })),
      h("div", { class: "snack-up-meta" }, meta.join(" · ")),
      running ? h("div", { class: "snack-up-meta" }, `⬆ ${running.name} · ${mb(running.sent)}/${mb(running.size)}`) : null,
      job.error && job.state !== "done" ? h("div", { class: "snack-up-err" }, tr(job.error)) : null,
      job.state === "done" ? h("div", { class: "snack-up-files" }, files.map((f) => this.fileRow(f))) : null,
      actions.length ? h("div", { class: "snack-up-actions" }, actions) : null);
  }

  fileRow(f) {
    const result = f.result || f.name;
    const link = /^https?:\/\//.test(result);
    const shown = result.replace(/ \[encrypted\]$/, " 🔒");
    return h("div", { class: "snack-up-file" },
      h("span", { title: shown }, "✓ " + (link ? f.name : shown)),
      link ? h("a", { href: result, target: "_blank", rel: "noopener" }, T("打开", "Open")) : null,
      h("button", {
        class: "link",
        onclick: async () => {
          try {
            await navigator.clipboard.writeText(result.replace(/ \[encrypted\]$/, ""));
            app.extensionManager?.toast?.add?.({ severity: "info", summary: T("已复制", "Copied"), life: 1500 });
          } catch { /* clipboard blocked */ }
        },
      }, T("复制", "Copy")));
  }
}

function addStyle() {
  if (!document.getElementById("snack-up-style")) document.head.append(h("style", { id: "snack-up-style" }, CSS));
}

// fixed once at load: findButton() matches the rendered button by this exact aria-label
const TOOLTIP = T("SnackNodes 上传队列", "SnackNodes uploads");

function findButton() {
  const label = TOOLTIP;
  return [...document.querySelectorAll('[data-testid="action-bar-buttons"] button, button[aria-label]')]
    .find((b) => b.getAttribute("aria-label") === label) || null;
}

const panel = new Panel();

app.registerExtension({
  name: "SnackNodes.UploadPanel",
  actionBarButtons: [{
    icon: "pi pi-cloud-upload",
    label: T("上传", "Uploads"),
    tooltip: TOOLTIP,
    onClick: (event) => panel.toggle(event),
  }],
  setup() {
    addStyle();
    api.addEventListener("snacknodes.upload", ({ detail }) => panel.onEvent(detail));
    api.addEventListener("reconnected", () => panel.load());
    panel.load();
    // the action bar may be re-rendered (layout or size changes): put the badge back
    setInterval(() => panel.updateBadge(), 2000);
  },
});
