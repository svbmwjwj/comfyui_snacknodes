// "网盘设置 / Cloud drives" tab of the SnackNodes popup: connect drives and set up encryption vaults,
// for all nodes at once. The popup itself lives in upload_panel.js (one place for settings and uploads).
// Everything is stored on the ComfyUI machine (nodes/routes.py -> cloud_drive/connect.py), never in a
// workflow; passwords and secret keys are typed into masked fields and never sent back to the page.
import {
  PROVIDERS, T, call, changed, confirmDialog, h, t, toast, vaultCall, vaultDialog,
} from "./snack_common.js";

const CSS = `
.snack-set{display:flex;flex-direction:column;height:100%;font:13px/1.5 sans-serif;color:var(--fg-color,#ddd)}
.snack-set-head{padding:8px 14px 0}
.snack-set-head h3{margin:0 0 2px;font-size:15px;font-weight:600}
.snack-set-head div{opacity:.7;font-size:12px}
.snack-set-list{padding:10px;display:flex;flex-direction:column;gap:10px}
.snack-card{border:1px solid var(--border-color,#444);border-radius:8px;padding:10px 12px;display:flex;flex-direction:column;gap:8px;
  background:var(--comfy-input-bg,rgba(255,255,255,.03))}
.snack-card.focus{outline:2px solid #4ea1ff}
.snack-card-row{display:flex;align-items:center;justify-content:space-between;gap:8px}
.snack-card-title{font-weight:600;font-size:14px}
.snack-chip{font-size:11px;padding:1px 8px;border-radius:999px;border:1px solid currentColor;white-space:nowrap}
.snack-chip.on{color:#4cc38a}.snack-chip.off{color:#a0a0a0}.snack-chip.wait{color:#e0a030}
.snack-muted{opacity:.72;font-size:12px}
.snack-err{color:#ff8a80;font-size:12px;white-space:pre-wrap;word-break:break-word}
.snack-card label{display:flex;flex-direction:column;gap:3px;font-size:12px}
.snack-card input{background:var(--comfy-menu-bg,#111);color:inherit;border:1px solid var(--border-color,#555);border-radius:6px;
  padding:6px 8px;font:inherit;font-size:13px;min-width:0}
.snack-actions{display:flex;gap:6px;flex-wrap:wrap;align-items:center}
.snack-set button{background:transparent;color:inherit;border:1px solid var(--border-color,#666);border-radius:6px;
  padding:4px 12px;font:inherit;font-size:12px;cursor:pointer}
.snack-set button:hover{background:rgba(128,128,128,.15)}
.snack-set button.primary{background:#2f6fde;border-color:#2f6fde;color:#fff}
.snack-set button:disabled{opacity:.6;cursor:wait}
.snack-vault{border-top:1px dashed var(--border-color,#555);padding-top:8px;display:flex;flex-direction:column;gap:6px}
.snack-code{font:700 18px monospace;letter-spacing:2px;user-select:all}
.snack-set a{color:#4ea1ff}
`;

const NAMES = Object.fromEntries(Object.entries(PROVIDERS).map(([label, id]) => [id, label]));

class DriveCard {
  constructor(panel, provider) {
    this.panel = panel;
    this.provider = provider;
    this.status = null;
    this.vault = null;
    this.editing = false;
    this.editingVault = false;
    this.error = "";
    this.vaultError = "";
    this.busy = "";
    this.timer = null;
    this.vaultPath = "";
    this.drafts = {}; // what was typed so far (in memory only), so a redraw or an error keeps it
    this.el = h("div", { class: "snack-card" });
  }

  async load() {
    try {
      this.status = await call(this.provider);
      this.vault = this.status.connected ? await vaultCall(this.provider) : null;
      this.error = "";
    } catch (e) {
      this.error = t(e);
    }
    this.draw();
    clearTimeout(this.timer);
    if (this.status?.oauth?.state === "pending") this.timer = setTimeout(() => this.poll(), 3000);
  }

  async poll() {
    if (!this.panel.root) return;
    const wasConnected = this.status?.connected;
    await this.load();
    if (this.status?.connected && !wasConnected) {
      toast("success", T(`${NAMES[this.provider]} 已连接`, `${NAMES[this.provider]} connected`));
      changed(this.provider);
    }
  }

  async run(label, fn) {
    this.busy = label;
    this.draw();
    try { await fn(); } finally { this.busy = ""; this.draw(); }
  }

  draw() {
    const s = this.status;
    const name = NAMES[this.provider];
    const chip = !s ? h("span", { class: "snack-chip off" }, "…")
      : s.oauth?.state === "pending" ? h("span", { class: "snack-chip wait" }, T("等待授权", "Waiting"))
        : s.connected ? h("span", { class: "snack-chip on" }, T("已连接", "Connected"))
          : h("span", { class: "snack-chip off" }, T("未连接", "Not connected"));
    const body = [];
    if (s && s.oauth?.state === "pending") body.push(...this.pending());
    else if (s && s.connected && !this.editing) body.push(...this.connected());
    else if (s) body.push(...this.form());
    if (this.error) body.push(h("div", { class: "snack-err" }, this.error));
    if (s?.connected && s.oauth?.state !== "pending") body.push(this.vaultSection());
    // replaceChildren() would print a null placeholder as the text "null"
    this.el.replaceChildren(h("div", { class: "snack-card-row" }, h("span", { class: "snack-card-title" }, name), chip),
      ...body.filter(Boolean));
  }

  connected() {
    const s = this.status;
    const oauth = s.form.kind === "oauth";
    return [
      t(s.summary) ? h("div", { class: "snack-muted" }, t(s.summary)) : null,
      h("div", { class: "snack-actions" },
        h("button", { onclick: () => { this.editing = true; this.error = ""; if (oauth) this.startOAuth(); else this.draw(); } },
          oauth ? T("重新登录", "Sign in again") : T("修改", "Change")),
        h("button", { onclick: () => this.disconnect() }, T("断开", "Disconnect"))),
    ];
  }

  form() {
    const s = this.status;
    const form = s.form;
    const intro = h("div", { class: "snack-muted" }, t(form.intro),
      form.help ? [" ", h("a", { href: form.help, target: "_blank", rel: "noopener" }, T("图文教程", "Guide"))] : null);
    const cancel = s.connected ? h("button", { onclick: () => { this.editing = false; this.error = ""; this.draw(); } }, T("取消", "Cancel")) : null;
    if (form.kind === "oauth") {
      const err = s.oauth?.state === "error" ? [t(s.oauth.error), s.oauth.error?.detail].filter(Boolean).join("\n") : "";
      return [intro, err ? h("div", { class: "snack-err" }, err) : null,
        h("div", { class: "snack-actions" },
          h("button", { class: "primary", disabled: !!this.busy, onclick: () => this.startOAuth() },
            this.busy || T(`连接 ${NAMES[this.provider]}`, `Connect ${NAMES[this.provider]}`)), cancel)];
    }
    const inputs = {};
    const fields = form.fields.map((f) => {
      const input = h("input", {
        type: f.secret ? "password" : "text", placeholder: f.placeholder || "", value: this.drafts[f.key] ?? f.default ?? "",
        autocomplete: f.secret ? "new-password" : "off", spellcheck: "false",
      });
      input.addEventListener("input", () => { this.drafts[f.key] = input.value; });
      input.addEventListener("keydown", (ev) => { ev.stopPropagation(); if (ev.key === "Enter") submit(); });
      inputs[f.key] = input;
      return h("label", {}, t(f.label) + (f.optional ? T("（可选）", " (optional)") : ""), input,
        t(f.hint) ? h("span", { class: "snack-muted" }, t(f.hint)) : null);
    });
    const submit = () => {
      const values = Object.fromEntries(Object.entries(inputs).map(([k, i]) => [k, i.value.trim()]));
      const missing = form.fields.find((f) => !f.optional && !values[f.key]);
      if (missing) { this.error = T(`请填写：${t(missing.label)}`, `Please fill in: ${t(missing.label)}`); return this.draw(); }
      this.run(T("正在连接…", "Connecting…"), async () => {
        try {
          const result = await call(this.provider, "connect", values);
          this.status = result;
          this.editing = false;
          this.error = "";
          this.drafts = {};
          this.vault = await vaultCall(this.provider).catch(() => null);
          toast("success", T(`${NAMES[this.provider]} 已连接`, `${NAMES[this.provider]} connected`),
            [t(result.summary), t(result.note)].filter(Boolean).join(T("，", ", ")));
          changed(this.provider);
        } catch (e) {
          this.error = [t(e), e.detail].filter(Boolean).join("\n");
        }
      });
    };
    return [intro, ...fields,
      h("div", { class: "snack-actions" },
        h("button", { class: "primary", disabled: !!this.busy, onclick: submit }, this.busy || T("连接", "Connect")), cancel),
      h("div", { class: "snack-muted" }, T("只保存在运行 ComfyUI 的机器上，不写进工作流。", "Stored on the ComfyUI machine only, never in a workflow."))];
  }

  pending() {
    const flow = this.status.oauth;
    return [
      h("div", {}, "1. ", T("打开 ", "Open "), h("a", { href: flow.url, target: "_blank", rel: "noopener" }, flow.url),
        T("（任意设备都可以）", " (any device)")),
      h("div", { class: "snack-actions" }, "2. " + T("输入验证码", "Enter the code"), h("span", { class: "snack-code" }, flow.code),
        h("button", { onclick: async () => {
          try { await navigator.clipboard.writeText(flow.code); toast("info", T("已复制验证码", "Code copied")); } catch { /* select it */ }
        } }, T("复制", "Copy"))),
      h("div", { class: "snack-muted" }, T("3. 登录 Google 账号并允许访问，完成后这里会自动更新。",
        "3. Sign in and allow access; this updates by itself.")),
    ];
  }

  startOAuth() {
    this.run(T("正在获取验证码…", "Getting a code…"), async () => {
      try {
        this.status = await call(this.provider, "oauth");
        this.error = "";
        clearTimeout(this.timer);
        this.timer = setTimeout(() => this.poll(), 3000);
      } catch (e) {
        this.error = [t(e), e.detail].filter(Boolean).join("\n");
      }
    });
  }

  async disconnect() {
    const ok = await confirmDialog(T("断开连接", "Disconnect"),
      T(`断开 ${NAMES[this.provider]} 后会删除这台机器上保存的连接信息和这个网盘的保险库密钥（网盘上的文件不受影响）。继续？`,
        `This removes the saved ${NAMES[this.provider]} connection and its vault keys from this machine (files on the drive stay). Continue?`));
    if (!ok) return;
    this.run(T("正在断开…", "Disconnecting…"), async () => {
      try {
        this.status = await call(this.provider, "disconnect");
        this.vault = null;
        this.editing = false;
        changed(this.provider);
      } catch (e) {
        this.error = t(e);
      }
    });
  }

  vaultSection() {
    const v = this.vault;
    const title = h("div", { class: "snack-card-row" }, h("span", {}, "🔒 " + T("加密保险库", "Encryption vault")),
      v?.vault ? h("span", { class: "snack-chip on" }, T("已设置", "Ready")) : h("span", { class: "snack-chip off" }, T("未设置", "Not set up")));
    const parts = [title];
    if (v?.vault && !this.editingVault) {
      parts.push(h("div", { class: "snack-muted" }, T(`位置：${v.vault.path}。节点打开「加密」后，文件会加密放进这里（「网盘目录」是保险库里面的目录），用 Cryptomator App 打开。`,
        `Location: ${v.vault.path}. With encrypt on, files go into this vault (remote_folder is inside it); open it with the Cryptomator app.`)),
      h("div", { class: "snack-actions" }, h("button", { onclick: () => { this.editingVault = true; this.vaultError = ""; this.draw(); } }, T("更换保险库", "Use another vault"))));
    } else {
      const path = h("input", { type: "text", value: this.vaultPath || v?.vault?.path || v?.default_path || "ComfyUI-Vault", spellcheck: "false" });
      path.addEventListener("input", () => { this.vaultPath = path.value; });
      path.addEventListener("keydown", (ev) => ev.stopPropagation());
      parts.push(
        h("div", { class: "snack-muted" }, T("需要加密时设置一次：文件在本机加密后再上传，网盘看不到内容和文件名。",
          "Set up once if you want encryption: files are encrypted here before upload; the drive sees neither contents nor names.")),
        h("label", {}, T("保险库位置（网盘上的文件夹）", "Vault location (folder on the drive)"), path),
        h("div", { class: "snack-actions" },
          h("button", { class: "primary", onclick: () => this.openVault("create", path.value) }, T("新建保险库…", "Create vault…")),
          h("button", { onclick: () => this.openVault("unlock", path.value) }, T("打开已有保险库…", "Open existing vault…")),
          v?.vault ? h("button", { onclick: () => { this.editingVault = false; this.draw(); } }, T("取消", "Cancel")) : null));
    }
    if (this.vaultError) parts.push(h("div", { class: "snack-err" }, this.vaultError));
    return h("div", { class: "snack-vault" }, ...parts);
  }

  async openVault(mode, rawPath) {
    const path = (rawPath || "").trim() || this.vault?.default_path || "ComfyUI-Vault";
    const result = await vaultDialog({
      mode, path, drive: NAMES[this.provider], minLength: this.vault?.min_password || 8,
      submit: (password) => vaultCall(this.provider, mode, { path, password }),
    });
    if (!result) return;
    this.vault = result;
    this.editingVault = false;
    this.vaultPath = "";
    this.draw();
    toast("success", mode === "create" ? T("保险库已创建", "Vault created") : T("保险库已打开", "Vault opened"), result.vault?.path);
    changed(this.provider);
  }
}

class SettingsPanel {
  constructor() {
    this.cards = Object.values(PROVIDERS).map((p) => new DriveCard(this, p));
    this.root = null;
  }

  mount(el) {
    if (!document.getElementById("snack-set-style")) document.head.append(h("style", { id: "snack-set-style" }, CSS));
    this.root = h("div", { class: "snack-set" },
      h("div", { class: "snack-set-head" },
        h("div", {}, T("「保存到网盘」节点用这里的连接和保险库。只保存在运行 ComfyUI 的机器上。",
          "Connections and vaults used by Save to Cloud Drive, stored on the ComfyUI machine only."))),
      h("div", { class: "snack-set-list" }, this.cards.map((c) => c.el)));
    el.replaceChildren(this.root);
    this.loaded = Promise.all(this.cards.map((card) => card.load()));
  }

  unmount() {
    this.root = null;
    for (const card of this.cards) clearTimeout(card.timer);
  }

  async focus(provider) {
    if (!provider || !this.root) return;
    for (const card of this.cards) card.el.classList.toggle("focus", card.provider === provider);
    await this.loaded; // cards change height when their status arrives: scroll after that
    this.cards.find((c) => c.provider === provider)?.el.scrollIntoView({ block: "start" });
  }
}

// Shown in the SnackNodes popup of the top action bar (upload_panel.js), next to the upload queue.
export const settingsPanel = new SettingsPanel();
