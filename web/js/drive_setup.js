// "Connect a drive" panel on Save to Cloud Drive: when the chosen drive is not connected yet,
// the node shows the fields it needs (or a Connect button for Google Drive). Values are sent to
// the ComfyUI server (nodes/routes.py) and stored on that machine only: the panel is never saved
// in the workflow, and secrets are never sent back to the page.
import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";

const NODE = "SnackSaveToCloudDrive";
const WIDGET = "drive_setup";
// Dropdown label -> provider id (same as cloud_drive.NODE_PROVIDERS)
const PROVIDERS = { "Google Drive": "google_drive", WebDAV: "webdav", "Cloudflare R2": "r2" };

const zh = () => {
  const locale = app.ui?.settings?.getSettingValue?.("Comfy.Locale") || navigator.language || "";
  return locale.toLowerCase().startsWith("zh");
};
const t = (pair) => (pair ? (zh() ? pair.zh : pair.en) || pair.en || "" : "");
const T = (z, e) => (zh() ? z : e);

const CSS = `
.snack-setup{font:12px/1.45 sans-serif;color:var(--input-text,#ddd);padding:6px 8px;border-radius:6px;
  border:1px solid var(--border-color,#444);background:var(--comfy-input-bg,#222);box-sizing:border-box;
  display:flex;flex-direction:column;gap:6px;width:100%;overflow:hidden}
.snack-setup .row{display:flex;gap:6px;align-items:center;flex-wrap:wrap}
.snack-setup label{display:flex;flex-direction:column;gap:2px}
.snack-setup input{background:var(--comfy-menu-bg,#111);color:inherit;border:1px solid var(--border-color,#555);
  border-radius:4px;padding:4px 6px;font:inherit;width:100%;box-sizing:border-box}
.snack-setup button{background:var(--comfy-menu-bg,#333);color:inherit;border:1px solid var(--border-color,#666);
  border-radius:4px;padding:3px 10px;font:inherit;cursor:pointer}
.snack-setup button.primary{background:#2f6fde;border-color:#2f6fde;color:#fff}
.snack-setup button:disabled{opacity:.6;cursor:wait}
.snack-setup .muted{opacity:.7}
.snack-setup .err{color:#ff8a80;white-space:pre-wrap;word-break:break-word}
.snack-setup .ok{color:#7ddc8a}
.snack-setup .code{font:bold 16px monospace;letter-spacing:2px;user-select:all}
.snack-setup a{color:#6fa8ff}
`;

function addStyle() {
  if (document.getElementById("snack-setup-style")) return;
  const style = document.createElement("style");
  style.id = "snack-setup-style";
  style.textContent = CSS;
  document.head.appendChild(style);
}

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (v !== undefined && v !== null && v !== false) node.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) if (c !== null && c !== undefined) node.append(c);
  return node;
}

async function call(provider, action, body) {
  const url = `/snacknodes/drive/${provider}` + (action ? `/${action}` : "");
  const resp = await api.fetchApi(url, body === undefined && !action ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body ?? {}),
  });
  let data = {};
  try { data = await resp.json(); } catch { /* not JSON */ }
  if (!resp.ok) throw data.error || { zh: `请求失败（HTTP ${resp.status}）`, en: `Request failed (HTTP ${resp.status})` };
  return data;
}

class Panel {
  constructor(node) {
    this.node = node;
    this.root = el("div", { class: "snack-setup" });
    this.editing = false;
    this.timer = null;
    this.widget = node.addDOMWidget(WIDGET, "snack_drive_setup", this.root, {
      serialize: false, hideOnZoom: false,
      getMinHeight: () => (this.root.style.display === "none" ? 0 : this.root.scrollHeight + 6),
      getMaxHeight: () => (this.root.style.display === "none" ? 0 : this.root.scrollHeight + 6),
    });
    this.widget.serialize = false; // display only: never part of widgets_values
  }

  provider() {
    const label = this.node.widgets?.find((w) => w.name === "provider")?.value;
    return PROVIDERS[label];
  }

  resize() {
    requestAnimationFrame(() => {
      const size = this.node.computeSize?.();
      if (size) this.node.setSize([this.node.size[0], Math.max(size[1], 0)]);
      this.node.graph?.setDirtyCanvas(true, true);
    });
  }

  show(...items) {
    const children = items.filter((c) => c !== null && c !== undefined && c !== false);
    this.root.replaceChildren(...children);
    this.root.style.display = children.length ? "flex" : "none";
    this.resize();
  }

  async refresh() {
    clearTimeout(this.timer);
    const provider = this.provider();
    if (!provider) return this.show();
    const asked = provider;
    this.show(el("div", { class: "muted" }, T("正在检查连接…", "Checking connection…")));
    try {
      const status = await call(provider);
      if (this.provider() === asked) this.render(status);
    } catch (e) {
      if (this.provider() === asked) this.show(el("div", { class: "err" }, t(e)), this.retryRow());
    }
  }

  retryRow() {
    return el("div", { class: "row" }, el("button", { onclick: () => this.refresh() }, T("重试", "Retry")));
  }

  render(status, note) {
    const form = status.form;
    if (status.connected && !this.editing && status.oauth?.state !== "pending") {
      const summary = t(status.summary);
      return this.show(
        el("div", { class: "row" },
          el("span", { class: "ok" }, "✓ " + T("已连接", "Connected")),
          summary ? el("span", { class: "muted" }, summary) : null),
        note && t(note) ? el("div", { class: "muted" }, t(note)) : null,
        el("div", { class: "row" },
          el("button", { onclick: () => { this.editing = true; this.render(status); } },
            form.kind === "oauth" ? T("重新登录", "Sign in again") : T("修改", "Change")),
          el("button", { onclick: (ev) => this.disconnect(ev.target) }, T("断开", "Disconnect"))),
      );
    }
    if (form.kind === "oauth") return this.renderOAuth(status);
    return this.renderForm(status);
  }

  header(status, form) {
    return [
      el("div", {}, el("b", {}, status.connected ? T("修改连接", "Change connection") : T("连接这个网盘", "Connect this drive"))),
      el("div", { class: "muted" }, t(form.intro),
        form.help ? [" ", el("a", { href: form.help, target: "_blank", rel: "noopener" }, T("图文教程", "Guide"))] : null),
    ];
  }

  renderForm(status) {
    const form = status.form;
    const inputs = {};
    const error = el("div", { class: "err" });
    const fields = form.fields.map((f) => {
      const input = el("input", {
        type: f.secret ? "password" : "text", placeholder: f.placeholder || "", value: f.default || "",
        autocomplete: f.secret ? "new-password" : "off", spellcheck: "false",
      });
      input.addEventListener("keydown", (ev) => { ev.stopPropagation(); if (ev.key === "Enter") submit(); });
      inputs[f.key] = input;
      return el("label", {},
        el("span", {}, t(f.label) + (f.optional ? T("（可选）", " (optional)") : "")),
        input,
        t(f.hint) ? el("span", { class: "muted" }, t(f.hint)) : null);
    });
    const button = el("button", { class: "primary", onclick: () => submit() }, T("连接", "Connect"));
    const submit = async () => {
      const values = Object.fromEntries(Object.entries(inputs).map(([k, i]) => [k, i.value.trim()]));
      const missing = form.fields.find((f) => !f.optional && !values[f.key]);
      if (missing) { error.textContent = T(`请填写：${t(missing.label)}`, `Please fill in: ${t(missing.label)}`); return this.resize(); }
      button.disabled = true;
      button.textContent = T("正在连接…", "Connecting…");
      error.textContent = "";
      try {
        const result = await call(status.provider, "connect", values);
        this.editing = false;
        this.render(result, result.note);
      } catch (e) {
        error.textContent = [t(e), e.detail].filter(Boolean).join("\n");
        button.disabled = false;
        button.textContent = T("连接", "Connect");
        this.resize();
      }
    };
    const actions = el("div", { class: "row" }, button,
      status.connected ? el("button", { onclick: () => { this.editing = false; this.render(status); } }, T("取消", "Cancel")) : null,
      el("span", { class: "muted" }, T("只保存在运行 ComfyUI 的机器上，不写进工作流", "Stored on the ComfyUI machine only, never in the workflow")));
    this.show(...this.header(status, form), ...fields, actions, error);
  }

  renderOAuth(status) {
    const form = status.form;
    const flow = status.oauth;
    const error = el("div", { class: "err" });
    if (flow?.state === "pending") {
      this.timer = setTimeout(() => this.poll(), 3000);
      return this.show(
        el("div", {}, el("b", {}, T("在任意设备上完成登录", "Finish signing in on any device"))),
        el("div", {}, "1. ", T("打开 ", "Open "), el("a", { href: flow.url, target: "_blank", rel: "noopener" }, flow.url)),
        el("div", { class: "row" }, "2. " + T("输入验证码：", "Enter the code:"), el("span", { class: "code" }, flow.code)),
        el("div", { class: "muted" }, T("3. 登录你的 Google 账号并允许访问。完成后这里会自动更新。",
          "3. Sign in to your Google account and allow access. This panel updates by itself.")),
      );
    }
    if (flow?.state === "error") {
      error.textContent = [t(flow.error), flow.error?.detail].filter(Boolean).join("\n");
    }
    const button = el("button", {
      class: "primary",
      onclick: async () => {
        button.disabled = true;
        try {
          this.editing = false;
          this.render(await call(status.provider, "oauth"));
        } catch (e) {
          error.textContent = [t(e), e.detail].filter(Boolean).join("\n");
          button.disabled = false;
          this.resize();
        }
      },
    }, T("连接 Google Drive", "Connect Google Drive"));
    this.show(...this.header(status, form), el("div", { class: "row" }, button,
      status.connected ? el("button", { onclick: () => { this.editing = false; this.render(status); } }, T("取消", "Cancel")) : null),
    error);
  }

  async poll() {
    const provider = this.provider();
    if (!provider || !this.node.graph) return;
    try {
      const status = await call(provider);
      if (this.provider() === provider) this.render(status);
    } catch {
      this.timer = setTimeout(() => this.poll(), 5000);
    }
  }

  async disconnect(button) {
    if (!confirm(T("断开后会删除这台机器上保存的连接信息（以及这个网盘的保险库密钥）。继续？",
      "This removes the saved connection (and this drive's vault keys) from this machine. Continue?"))) return;
    button.disabled = true;
    try {
      this.editing = false;
      this.render(await call(this.provider(), "disconnect"));
    } catch (e) {
      this.show(el("div", { class: "err" }, t(e)), this.retryRow());
    }
  }
}

app.registerExtension({
  name: "SnackNodes.DriveSetup",
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== NODE) return;
    addStyle();

    const onNodeCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const r = onNodeCreated?.apply(this, arguments);
      const panel = new Panel(this);
      this.snackSetup = panel;
      const providerWidget = this.widgets?.find((w) => w.name === "provider");
      if (providerWidget) {
        const callback = providerWidget.callback;
        providerWidget.callback = function () {
          const out = callback?.apply(this, arguments);
          panel.editing = false;
          panel.refresh();
          return out;
        };
      }
      // after a workflow is loaded the dropdown value is set without its callback: check again then
      setTimeout(() => panel.refresh(), 0);
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
