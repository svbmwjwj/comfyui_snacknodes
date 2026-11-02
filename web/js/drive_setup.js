// "Connect a drive" rows on Save to Cloud Drive: when the chosen drive is not connected yet, native
// widgets for what it needs (or a Connect button for Google Drive) appear right below the drive
// dropdown, styled like every other row. Values go to the ComfyUI server (nodes/routes.py) and are
// stored on that machine only: these rows are never saved in the workflow (serialize: false), and
// secrets are never sent back to the page.
//
// Frontend notes (checked against comfyui_frontend_package 1.57):
// - node.widgets is a tracked array: splice() also updates the Nodes 2.0 (Vue) widget order.
// - addCustomWidget restores a saved value by position only for widgets with serialize !== false,
//   so each row is created with serialize: false already set.
// - Rows are only added after an async status request, i.e. after the node was configured from a
//   workflow, so they never shift the positions of the saved widget values.
import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";

const NODE = "SnackSaveToCloudDrive";
const ANCHOR = "provider";
// Dropdown label -> provider id (same as cloud_drive.NODE_PROVIDERS)
const PROVIDERS = { "Google Drive": "google_drive", WebDAV: "webdav", "Cloudflare R2": "r2" };

const zh = () => {
  const locale = app.ui?.settings?.getSettingValue?.("Comfy.Locale") || navigator.language || "";
  return locale.toLowerCase().startsWith("zh");
};
const t = (pair) => (pair ? (zh() ? pair.zh : pair.en) || pair.en || "" : "");
const T = (z, e) => (zh() ? z : e);

function toast(severity, summary, detail) {
  const add = app.extensionManager?.toast?.add;
  if (add) {
    add.call(app.extensionManager.toast, { severity, summary, detail, life: severity === "error" ? 10000 : 4000 });
  } else if (severity === "error") {
    alert([summary, detail].filter(Boolean).join("\n\n"));
  }
}

async function confirmDialog(title, message) {
  const dialog = app.extensionManager?.dialog;
  if (dialog?.confirm) {
    try { return !!(await dialog.confirm({ title, message, type: "default" })); } catch { /* fall back */ }
  }
  return confirm(message);
}

async function call(provider, action, body) {
  const url = `/snacknodes/drive/${provider}` + (action ? `/${action}` : "");
  const resp = await api.fetchApi(url, body === undefined && !action ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body ?? {}),
  });
  let data = {};
  try { data = await resp.json(); } catch { /* not JSON */ }
  if (resp.status === 404 && !data.error) {
    // The page has the new rows but the server is still running older Python code.
    throw { zh: "ComfyUI 后端还没加载新版本的 SnackNodes：请完全重启 ComfyUI 后再刷新网页。如果重启后仍然这样，请查看启动日志里 SnackNodes 的报错。",
            en: "The ComfyUI server has not loaded the new SnackNodes yet: fully restart ComfyUI, then reload the page. If it persists, check the startup log for SnackNodes errors." };
  }
  if (!resp.ok) throw data.error || { zh: `请求失败（HTTP ${resp.status}）`, en: `Request failed (HTTP ${resp.status})` };
  return data;
}

const shorten = (text, max = 48) => (text.length > max ? text.slice(0, max - 1) + "…" : text);

class DriveRows {
  constructor(node) {
    this.node = node;
    this.rows = [];        // widgets this class added
    this.drafts = {};      // non-secret values typed so far, kept across re-renders
    this.editing = false;
    this.busy = false;
    this.timer = null;
    this.seq = 0;
    this.status = null;
  }

  provider() {
    return PROVIDERS[this.node.widgets?.find((w) => w.name === ANCHOR)?.value];
  }

  // ---- widgets -------------------------------------------------------------------------------

  text(key, label, { value = "", tooltip = "", placeholder = "", secret = false } = {}) {
    return { kind: "text", key, label, value, tooltip, placeholder, secret };
  }

  button(key, label, onClick, tooltip = "") {
    return { kind: "button", key, label, onClick, tooltip };
  }

  make(spec) {
    const name = `snack_${spec.key}`;
    const options = { serialize: false };
    if (spec.placeholder) options.placeholder = spec.placeholder;
    const widget = this.node.addCustomWidget(spec.kind === "button"
      ? { type: "button", name, label: spec.label, value: null, serialize: false, options,
          callback: () => { if (!this.busy) spec.onClick(); } }
      : { type: "text", name, label: spec.label, value: spec.value ?? "", serialize: false, options,
          callback: () => {} });
    widget.serialize = false;
    widget.options = { ...(widget.options || {}), serialize: false };
    if (spec.kind === "text") widget.value = spec.value ?? "";
    if (spec.tooltip) widget.tooltip = spec.tooltip;
    widget.snackKey = spec.key;
    widget.snackSecret = !!spec.secret;
    return widget;
  }

  value(key) {
    const w = this.rows.find((r) => r.snackKey === key);
    return w ? String(w.value ?? "").trim() : "";
  }

  setRows(specs) {
    const node = this.node;
    for (const w of this.rows) {
      if (w.type === "text" && !w.snackSecret) this.drafts[w.snackKey] = w.value;
    }
    const before = node.computeSize?.()[1] ?? 0;
    for (const w of this.rows) {
      if (!node.widgets?.includes(w)) continue;
      if (node.removeWidget) node.removeWidget(w);
      else { w.onRemove?.(); node.widgets.splice(node.widgets.indexOf(w), 1); }
    }
    this.rows = specs.filter(Boolean).map((s) => this.make(s));
    if (this.rows.length && node.widgets) {
      // addCustomWidget appends: move the new rows right below the drive dropdown
      const moved = node.widgets.filter((w) => this.rows.includes(w));
      for (const w of moved) node.widgets.splice(node.widgets.indexOf(w), 1);
      const at = node.widgets.findIndex((w) => w.name === ANCHOR) + 1 || node.widgets.length;
      node.widgets.splice(at, 0, ...moved);
    }
    // grow or shrink by what changed, so a preview image below keeps its space
    const after = node.computeSize?.()[1] ?? 0;
    if (node.size && after) node.setSize([node.size[0], Math.max(after, node.size[1] + after - before)]);
    node.graph?.setDirtyCanvas(true, true);
  }

  clear() {
    clearTimeout(this.timer);
    if (this.rows.length) this.setRows([]);
  }

  // ---- state ---------------------------------------------------------------------------------

  async refresh() {
    clearTimeout(this.timer);
    const provider = this.provider();
    const seq = ++this.seq;
    if (!provider) return this.clear();
    try {
      const status = await call(provider);
      if (seq === this.seq && this.node.graph) this.render(status);
    } catch (e) {
      if (seq !== this.seq || !this.node.graph) return;
      this.setRows([
        this.button("error", "⚠ " + shorten(t(e)), () => toast("error", T("连接网盘", "Connect drive"), t(e)), t(e)),
        this.button("retry", T("重试", "Retry"), () => this.refresh()),
      ]);
    }
  }

  render(status) {
    this.status = status;
    clearTimeout(this.timer);
    const form = status.form;
    const flow = status.oauth;
    if (flow?.state === "pending") return this.renderPending(status);
    if (status.connected && !this.editing) {
      const summary = t(status.summary);
      const head = "✓ " + T("已连接", "Connected") + (summary ? T("：", ": ") + summary : "");
      return this.setRows([
        this.button("status", shorten(head, 60), () => this.refresh(),
          head + "\n" + T("点击重新检查", "Click to check again")),
        this.button("change", form.kind === "oauth" ? T("重新登录", "Sign in again") : T("修改连接", "Change connection"),
          () => { this.editing = true; this.render(this.status); }),
        this.button("disconnect", T("断开连接", "Disconnect"), () => this.disconnect()),
      ]);
    }
    const cancel = status.connected
      ? this.button("cancel", T("取消修改", "Cancel"), () => { this.editing = false; this.render(this.status); })
      : null;
    const intro = t(form.intro) + (form.help ? "\n" + T("图文教程：", "Guide: ") + form.help : "");
    if (form.kind === "oauth") {
      const error = flow?.state === "error" ? flow.error : null;
      return this.setRows([
        this.button("oauth", T("连接 Google Drive", "Connect Google Drive"), () => this.startOAuth(), intro),
        error ? this.errorRow(error) : null,
        cancel,
      ]);
    }
    const prefix = `${status.provider}_`;
    this.setRows([
      ...form.fields.map((f) => this.text(prefix + f.key,
        t(f.label) + (f.optional ? T("（可选）", " (optional)") : ""), {
          value: f.secret ? "" : (this.drafts[prefix + f.key] ?? f.default ?? ""),
          placeholder: f.placeholder || "",
          secret: f.secret,
          tooltip: [t(f.hint), f.placeholder ? T("例如 ", "e.g. ") + f.placeholder : "",
            f.secret ? T("输入后会在连接成功时清空，不会保存到工作流", "Cleared after connecting; never saved in the workflow") : ""]
            .filter(Boolean).join("\n") || intro,
        })),
      this.button("connect", T("连接", "Connect"), () => this.connect(),
        intro + "\n" + T("只保存在运行 ComfyUI 的机器上，不写进工作流", "Stored on the ComfyUI machine only, never in the workflow")),
      cancel,
    ]);
  }

  renderPending(status) {
    const flow = status.oauth;
    this.setRows([
      this.button("oauth_open", T("① 打开 ", "① Open ") + flow.url, () => window.open(flow.url, "_blank", "noopener"),
        T("可以在任意设备上打开", "Open it on any device")),
      this.button("oauth_code", T(`② 输入验证码 ${flow.code}（点击复制）`, `② Enter code ${flow.code} (click to copy)`),
        () => this.copy(flow.code)),
      this.button("oauth_wait", T("③ 登录 Google 并允许访问，完成后自动更新…", "③ Sign in and allow access; updates by itself…"),
        () => this.refresh()),
    ]);
    this.timer = setTimeout(() => this.poll(), 3000);
  }

  errorRow(error) {
    const text = [t(error), error.detail].filter(Boolean).join("\n\n");
    return this.button("error", "⚠ " + shorten(t(error) || T("连接失败", "Could not connect")),
      () => toast("error", T("连接失败", "Could not connect"), text), text);
  }

  // ---- actions -------------------------------------------------------------------------------

  async withBusy(key, label, fn) {
    const w = this.rows.find((r) => r.snackKey === key);
    const old = w?.label;
    this.busy = true;
    if (w) { w.label = label; this.node.graph?.setDirtyCanvas(true, true); }
    try { return await fn(); } finally {
      this.busy = false;
      if (w && this.rows.includes(w)) { w.label = old; this.node.graph?.setDirtyCanvas(true, true); }
    }
  }

  async connect() {
    const status = this.status;
    const prefix = `${status.provider}_`;
    const values = Object.fromEntries(status.form.fields.map((f) => [f.key, this.value(prefix + f.key)]));
    const missing = status.form.fields.find((f) => !f.optional && !values[f.key]);
    if (missing) return toast("warn", T(`请填写：${t(missing.label)}`, `Please fill in: ${t(missing.label)}`));
    await this.withBusy("connect", T("正在连接…", "Connecting…"), async () => {
      try {
        const result = await call(status.provider, "connect", values);
        this.editing = false;
        this.render(result);
        toast("success", T("已连接", "Connected"), [t(result.summary), t(result.note)].filter(Boolean).join(T("，", ", ")));
      } catch (e) {
        toast("error", T("连接失败", "Could not connect"), [t(e), e.detail].filter(Boolean).join("\n\n"));
      }
    });
  }

  async startOAuth() {
    await this.withBusy("oauth", T("正在获取验证码…", "Getting a code…"), async () => {
      try {
        this.editing = false;
        this.render(await call(this.status.provider, "oauth"));
      } catch (e) {
        toast("error", T("连接失败", "Could not connect"), [t(e), e.detail].filter(Boolean).join("\n\n"));
      }
    });
  }

  async poll() {
    const provider = this.provider();
    if (!provider || !this.node.graph) return;
    try {
      const status = await call(provider);
      if (this.provider() !== provider) return;
      if (status.oauth?.state === "pending") { this.status = status; this.timer = setTimeout(() => this.poll(), 3000); return; }
      this.render(status);
      if (status.connected) toast("success", T("Google Drive 已连接", "Google Drive connected"));
    } catch {
      this.timer = setTimeout(() => this.poll(), 5000);
    }
  }

  async copy(code) {
    try {
      await navigator.clipboard.writeText(code);
      toast("info", T(`已复制验证码 ${code}`, `Copied ${code}`));
    } catch {
      toast("info", T(`验证码：${code}`, `Code: ${code}`));
    }
  }

  async disconnect() {
    const ok = await confirmDialog(T("断开连接", "Disconnect"),
      T("断开后会删除这台机器上保存的连接信息（以及这个网盘的保险库密钥）。继续？",
        "This removes the saved connection (and this drive's vault keys) from this machine. Continue?"));
    if (!ok) return;
    await this.withBusy("disconnect", T("正在断开…", "Disconnecting…"), async () => {
      try {
        this.editing = false;
        this.render(await call(this.provider(), "disconnect"));
      } catch (e) {
        toast("error", T("断开失败", "Could not disconnect"), t(e));
      }
    });
  }
}

app.registerExtension({
  name: "SnackNodes.DriveSetup",
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== NODE) return;

    const onNodeCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const r = onNodeCreated?.apply(this, arguments);
      const rows = new DriveRows(this);
      this.snackSetup = rows;
      const providerWidget = this.widgets?.find((w) => w.name === ANCHOR);
      if (providerWidget) {
        const callback = providerWidget.callback;
        providerWidget.callback = function () {
          const out = callback?.apply(this, arguments);
          rows.editing = false;
          rows.refresh();
          return out;
        };
      }
      // after a workflow is loaded the dropdown value is set without its callback: check again then
      setTimeout(() => rows.refresh(), 0);
      return r;
    };

    const onConfigure = nodeType.prototype.onConfigure;
    nodeType.prototype.onConfigure = function () {
      const r = onConfigure?.apply(this, arguments);
      setTimeout(() => this.snackSetup?.refresh(), 0);
      return r;
    };

    const onRemoved = nodeType.prototype.onRemoved;
    nodeType.prototype.onRemoved = function () {
      clearTimeout(this.snackSetup?.timer);
      return onRemoved?.apply(this, arguments);
    };
  },
});
