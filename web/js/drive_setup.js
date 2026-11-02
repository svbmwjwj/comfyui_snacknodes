// Setup rows on Save to Cloud Drive, as native widgets styled like every other row:
// - below the drive dropdown: what the chosen drive needs to connect (or a Connect button for Google);
// - below "encrypt" (when it is on): the vault location and buttons to create or open a vault. The
//   vault password is typed in a small masked dialog and only sent to the server once, to derive keys.
// Values go to the ComfyUI server (nodes/routes.py) and are
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
const DRIVE_ANCHOR = "provider";
const VAULT_ANCHOR = "encrypt";
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

const call = (provider, action, body) => request(`/snacknodes/drive/${provider}`, action, body);
const vaultCall = (provider, action, body) => request(`/snacknodes/vault/${provider}`, action, body);

async function request(base, action, body) {
  const url = base + (action ? `/${action}` : "");
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

// A group of rows placed right below one of the node's own widgets (the anchor).
class Rows {
  constructor(node, anchor) {
    this.node = node;
    this.anchor = anchor;
    this.rows = [];        // widgets this class added
    this.drafts = {};      // non-secret values typed so far, kept across re-renders
    this.editing = false;
    this.busy = false;
    this.timer = null;
    this.seq = 0;
    this.status = null;
  }

  provider() {
    return PROVIDERS[this.node.widgets?.find((w) => w.name === DRIVE_ANCHOR)?.value];
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
      // addCustomWidget appends: move the new rows right below the anchor widget
      const moved = node.widgets.filter((w) => this.rows.includes(w));
      for (const w of moved) node.widgets.splice(node.widgets.indexOf(w), 1);
      const at = node.widgets.findIndex((w) => w.name === this.anchor) + 1 || node.widgets.length;
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
}

class DriveRows extends Rows {
  constructor(node, onChange) {
    super(node, DRIVE_ANCHOR);
    this.onChange = onChange; // tells the vault rows that the connection changed
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
    const changed = this.status?.provider !== status.provider || this.status?.connected !== status.connected;
    this.status = status;
    clearTimeout(this.timer);
    if (changed) this.onChange?.();
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


// ---- vault password dialog --------------------------------------------------------------------
// A node widget cannot hide what is typed, so the password goes into this small masked dialog.

// Same alphabet as auth.py (no 0/O, 1/l/I): 6 groups x 5 characters, about 148 bits.
const GEN_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789";
function generatePassword(groups = 6, size = 5) {
  const out = [];
  const bytes = new Uint32Array(groups * size);
  crypto.getRandomValues(bytes);
  for (let g = 0; g < groups; g++) {
    let part = "";
    for (let i = 0; i < size; i++) part += GEN_ALPHABET[bytes[g * size + i] % GEN_ALPHABET.length];
    out.push(part);
  }
  return out.join("-");
}

const DIALOG_CSS = `
.snack-dlg-back{position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:10000;display:flex;
  align-items:center;justify-content:center;padding:16px}
.snack-dlg{background:var(--comfy-menu-bg,#202020);color:var(--input-text,#ddd);border:1px solid var(--border-color,#444);
  border-radius:10px;width:min(440px,100%);padding:18px 20px;font:14px/1.5 sans-serif;box-shadow:0 10px 40px rgba(0,0,0,.5);
  display:flex;flex-direction:column;gap:10px;max-height:90vh;overflow:auto}
.snack-dlg h3{margin:0;font-size:16px}
.snack-dlg .warn{background:rgba(255,170,0,.12);border:1px solid rgba(255,170,0,.4);border-radius:6px;padding:8px 10px;font-size:13px}
.snack-dlg .muted{opacity:.7;font-size:12px}
.snack-dlg label{display:flex;flex-direction:column;gap:4px;font-size:13px}
.snack-dlg label.radio{flex-direction:row;align-items:center;gap:8px;cursor:pointer}
.snack-dlg input[type=password],.snack-dlg input[type=text]{background:var(--comfy-input-bg,#111);color:inherit;
  border:1px solid var(--border-color,#555);border-radius:6px;padding:7px 9px;font:inherit}
.snack-dlg .pw{font:600 15px/1.4 monospace;letter-spacing:.5px;user-select:all;word-break:break-all;
  background:var(--comfy-input-bg,#111);border-radius:6px;padding:8px 10px}
.snack-dlg .row{display:flex;gap:8px;justify-content:flex-end;align-items:center;flex-wrap:wrap}
.snack-dlg button{background:var(--comfy-input-bg,#333);color:inherit;border:1px solid var(--border-color,#666);
  border-radius:6px;padding:6px 14px;font:inherit;cursor:pointer}
.snack-dlg button.primary{background:#2f6fde;border-color:#2f6fde;color:#fff}
.snack-dlg button:disabled{opacity:.6;cursor:wait}
.snack-dlg .err{color:#ff8a80;white-space:pre-wrap;font-size:13px}
`;

function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (v !== false && v !== null && v !== undefined) el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) if (c !== null && c !== undefined && c !== false) el.append(c);
  return el;
}

// mode "create" or "unlock". submit(password) does the work and throws {zh, en, detail} on failure.
function vaultDialog({ mode, path, drive, minLength, submit }) {
  if (!document.getElementById("snack-dlg-style")) {
    document.head.append(h("style", { id: "snack-dlg-style" }, DIALOG_CSS));
  }
  return new Promise((resolve) => {
    const create = mode === "create";
    const error = h("div", { class: "err" });
    const ok = h("button", { class: "primary" }, create ? T("创建保险库", "Create vault") : T("打开保险库", "Open vault"));
    const cancel = h("button", {}, T("取消", "Cancel"));
    const close = (result) => { back.remove(); resolve(result); };
    const pw1 = h("input", { type: "password", autocomplete: "new-password", placeholder: T(`至少 ${minLength} 个字符`, `at least ${minLength} characters`) });
    const pw2 = h("input", { type: "password", autocomplete: "new-password" });
    const generated = generatePassword();
    const confirmTail = h("input", { type: "text", autocomplete: "off", spellcheck: "false" });
    let useGenerated = false;

    const own = h("div", { style: "display:flex;flex-direction:column;gap:8px" },
      h("label", {}, create ? T("保险库密码", "Vault password") : T("密码", "Password"), pw1),
      create ? h("label", {}, T("再输入一次", "Repeat password"), pw2) : null);
    const gen = h("div", { style: "display:none;flex-direction:column;gap:8px" },
      h("div", { class: "pw" }, generated),
      h("div", { class: "row", style: "justify-content:flex-start" },
        h("button", { onclick: async (ev) => {
          try { await navigator.clipboard.writeText(generated); ev.target.textContent = T("已复制", "Copied"); } catch { /* select it by hand */ }
        } }, T("复制密码", "Copy password"))),
      h("label", {}, T("存好后，输入密码的最后一组确认：", "After saving it, type the last group to confirm:"), confirmTail));
    const pick = (generatedMode) => {
      useGenerated = generatedMode;
      own.style.display = generatedMode ? "none" : "flex";
      gen.style.display = generatedMode ? "flex" : "none";
      error.textContent = "";
    };

    const go = async () => {
      let password = pw1.value;
      if (create && useGenerated) {
        if (confirmTail.value.trim() !== generated.split("-").pop()) {
          error.textContent = T("最后一组不对。请先把密码存好（例如密码管理器），再输入最后一组。",
            "That is not the last group. Save the password first (e.g. in a password manager), then type its last group.");
          return;
        }
        password = generated;
      } else if (password.length < (create ? minLength : 1)) {
        error.textContent = create ? T(`密码至少 ${minLength} 个字符。`, `Use at least ${minLength} characters.`)
          : T("请输入密码。", "Enter the password.");
        return;
      } else if (create && pw2.value !== password) {
        error.textContent = T("两次输入的密码不一致。", "The passwords do not match.");
        return;
      }
      ok.disabled = cancel.disabled = true;
      ok.textContent = T("正在生成密钥（需要几秒）…", "Deriving keys (a few seconds)…");
      error.textContent = "";
      try {
        const result = await submit(password);
        close(result);
      } catch (e) {
        error.textContent = [t(e), e?.detail].filter(Boolean).join("\n");
        ok.disabled = cancel.disabled = false;
        ok.textContent = create ? T("创建保险库", "Create vault") : T("打开保险库", "Open vault");
      }
    };
    ok.addEventListener("click", go);
    cancel.addEventListener("click", () => close(null));

    const radio = (checked, text, generatedMode) => h("label", { class: "radio" },
      h("input", { type: "radio", name: "snack-pw-mode", checked, onchange: () => pick(generatedMode) }), text);
    const dialog = h("div", { class: "snack-dlg", role: "dialog", "aria-modal": "true" },
      h("h3", {}, create ? T("新建保险库", "Create a vault") : T("打开已有保险库", "Open an existing vault")),
      h("div", { class: "muted" }, T(`位置：${drive} / ${path}`, `Location: ${drive} / ${path}`)),
      create ? h("div", { class: "warn" }, T(
        "⚠️ 保险库密码是恢复文件的唯一方式：没有找回、重置或恢复密钥。请立即存进密码管理器。本工具不保存密码，也不会写进工作流。",
        "⚠️ The vault password is the ONLY way to recover your files: there is no reset and no recovery key. Save it in a password manager now. The tool never stores it, and it is never put in the workflow.")) : null,
      create ? radio(true, T("自己设置密码", "Enter my own password"), false) : null,
      create ? radio(false, T("自动生成强密码（推荐）", "Generate a strong password (recommended)"), true) : null,
      own, create ? gen : null, error,
      h("div", { class: "row" }, cancel, ok));
    const back = h("div", { class: "snack-dlg-back" }, dialog);
    // keep ComfyUI's canvas shortcuts away from what is typed here
    back.addEventListener("keydown", (ev) => {
      ev.stopPropagation();
      if (ev.key === "Escape" && !cancel.disabled) close(null);
      if (ev.key === "Enter" && !ok.disabled) go();
    });
    back.addEventListener("mousedown", (ev) => { if (ev.target === back && !cancel.disabled) close(null); });
    document.body.append(back);
    pw1.focus();
  });
}

// ---- vault rows below "encrypt" ---------------------------------------------------------------

class VaultRows extends Rows {
  constructor(node) {
    super(node, VAULT_ANCHOR);
    this.status = null;
  }

  encrypting() {
    return !!this.node.widgets?.find((w) => w.name === VAULT_ANCHOR)?.value;
  }

  async refresh() {
    const provider = this.provider();
    const seq = ++this.seq;
    if (!provider || !this.encrypting()) { this.editing = false; return this.clear(); }
    try {
      const status = await vaultCall(provider);
      if (seq === this.seq && this.node.graph) this.render(status);
    } catch (e) {
      if (seq !== this.seq || !this.node.graph) return;
      this.setRows([
        this.button("vault_error", "⚠ " + shorten(t(e)), () => toast("error", T("加密", "Encryption"), t(e)), t(e)),
        this.button("vault_retry", T("重试", "Retry"), () => this.refresh()),
      ]);
    }
  }

  render(status) {
    this.status = status;
    if (!this.encrypting()) return this.clear();
    if (!status.connected) {
      return this.setRows([
        this.button("vault_need_drive", T("🔒 先在上面连接网盘，再设置保险库", "🔒 Connect the drive above, then set up a vault"),
          () => this.refresh()),
      ]);
    }
    if (status.vault && !this.editing) {
      const text = T(`🔒 保险库：${status.vault.path}（已就绪）`, `🔒 Vault: ${status.vault.path} (ready)`);
      return this.setRows([
        this.button("vault_status", shorten(text, 60), () => this.refresh(),
          T("文件会加密后放进这个保险库；「网盘目录」是保险库里面的目录。用 Cryptomator App 打开。",
            "Files are encrypted into this vault; remote_folder is a folder inside it. Open it with the Cryptomator app.")),
        this.button("vault_change", T("更换保险库", "Use another vault"), () => { this.editing = true; this.render(this.status); }),
      ]);
    }
    const location = T("保险库位置", "Vault location");
    this.setRows([
      this.text("vault_path", location, {
        value: this.drafts.vault_path || status.vault?.path || status.default_path,
        placeholder: status.default_path,
        tooltip: T("网盘上的文件夹，保险库放在这里（区分大小写）", "Folder on the drive that holds the vault (case-sensitive)"),
      }),
      this.button("vault_create", T("新建保险库（设置密码）…", "Create vault (set a password)…"), () => this.open("create"),
        T("第一次使用加密时选这个", "Choose this the first time you encrypt")),
      this.button("vault_unlock", T("打开已有保险库（输入密码）…", "Open existing vault (enter password)…"), () => this.open("unlock"),
        T("之前建过保险库，或已经有 Cryptomator App 建的保险库", "A vault created before, or with the Cryptomator app")),
      status.vault ? this.button("vault_cancel", T("取消", "Cancel"), () => { this.editing = false; this.render(this.status); }) : null,
    ]);
  }

  async open(mode) {
    const provider = this.provider();
    const path = this.value("vault_path") || this.status.default_path;
    const drive = Object.keys(PROVIDERS).find((k) => PROVIDERS[k] === provider) || provider;
    const result = await vaultDialog({
      mode, path, drive, minLength: this.status.min_password || 8,
      submit: (password) => vaultCall(provider, mode, { path, password }),
    });
    if (!result) return;
    this.editing = false;
    this.render(result);
    toast("success", mode === "create" ? T("保险库已创建", "Vault created") : T("保险库已打开", "Vault opened"),
      T(`之后上传的文件会加密放进 ${result.vault?.path}`, `Uploads now go into ${result.vault?.path}, encrypted`));
  }
}

app.registerExtension({
  name: "SnackNodes.DriveSetup",
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== NODE) return;

    const onNodeCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const r = onNodeCreated?.apply(this, arguments);
      const vault = new VaultRows(this);
      const rows = new DriveRows(this, () => vault.refresh());
      this.snackSetup = rows;
      this.snackVault = vault;
      const chain = (name, fn) => {
        const widget = this.widgets?.find((w) => w.name === name);
        if (!widget) return;
        const callback = widget.callback;
        widget.callback = function () {
          const out = callback?.apply(this, arguments);
          fn();
          return out;
        };
      };
      chain(DRIVE_ANCHOR, () => { rows.editing = false; vault.editing = false; rows.refresh(); vault.refresh(); });
      chain(VAULT_ANCHOR, () => { vault.editing = false; vault.refresh(); });
      // after a workflow is loaded the values are set without their callbacks: check again then
      setTimeout(() => { rows.refresh(); vault.refresh(); }, 0);
      return r;
    };

    const onConfigure = nodeType.prototype.onConfigure;
    nodeType.prototype.onConfigure = function () {
      const r = onConfigure?.apply(this, arguments);
      setTimeout(() => { this.snackSetup?.refresh(); this.snackVault?.refresh(); }, 0);
      return r;
    };

    const onRemoved = nodeType.prototype.onRemoved;
    nodeType.prototype.onRemoved = function () {
      clearTimeout(this.snackSetup?.timer);
      return onRemoved?.apply(this, arguments);
    };
  },
});
