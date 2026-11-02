// Shared by SnackNodes' frontend files: language helpers, server calls, the masked vault password
// dialog, and opening the SnackNodes sidebar tab. Loaded by ComfyUI like the other files in web/js
// (it registers no extension itself).
import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";

export const NODE = "SnackSaveToCloudDrive";
// Dropdown label -> provider id (same as cloud_drive.NODE_PROVIDERS), in dropdown order
export const PROVIDERS = { "Google Drive": "google_drive", WebDAV: "webdav", "Cloudflare R2": "r2" };
export const SETTINGS_TAB = "snacknodes-settings";
export const CHANGED = "snacknodes:drives-changed"; // window event after a connection or vault changed

export const zh = () => {
  const locale = app.ui?.settings?.getSettingValue?.("Comfy.Locale") || navigator.language || "";
  return locale.toLowerCase().startsWith("zh");
};
export const t = (pair) => (pair ? (zh() ? pair.zh : pair.en) || pair.en || "" : "");
export const T = (z, e) => (zh() ? z : e);

export function toast(severity, summary, detail) {
  const add = app.extensionManager?.toast?.add;
  if (add) {
    add.call(app.extensionManager.toast, { severity, summary, detail, life: severity === "error" ? 10000 : 4000 });
  } else if (severity === "error") {
    alert([summary, detail].filter(Boolean).join("\n\n"));
  }
}

export async function confirmDialog(title, message) {
  const dialog = app.extensionManager?.dialog;
  if (dialog?.confirm) {
    try { return !!(await dialog.confirm({ title, message, type: "default" })); } catch { /* fall back */ }
  }
  return confirm(message);
}

export const call = (provider, action, body) => request(`/snacknodes/drive/${provider}`, action, body);
export const vaultCall = (provider, action, body) => request(`/snacknodes/vault/${provider}`, action, body);

async function request(base, action, body) {
  const url = base + (action ? `/${action}` : "");
  const resp = await api.fetchApi(url, body === undefined && !action ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body ?? {}),
  });
  let data = {};
  try { data = await resp.json(); } catch { /* not JSON */ }
  if (resp.status === 404 && !data.error) {
    // The page has the new code but the server is still running older Python code.
    throw { zh: "ComfyUI 后端还没加载新版本的 SnackNodes：请完全重启 ComfyUI 后再刷新网页。如果重启后仍然这样，请查看启动日志里 SnackNodes 的报错。",
            en: "The ComfyUI server has not loaded the new SnackNodes yet: fully restart ComfyUI, then reload the page. If it persists, check the startup log for SnackNodes errors." };
  }
  if (!resp.ok) throw data.error || { zh: `请求失败（HTTP ${resp.status}）`, en: `Request failed (HTTP ${resp.status})` };
  return data;
}


// ---- vault password dialog --------------------------------------------------------------------
// A node widget cannot hide what is typed, so the password goes into this small masked dialog.

// Same alphabet as auth.py (no 0/O, 1/l/I): 6 groups x 5 characters, about 148 bits.
const GEN_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789";
export function generatePassword(groups = 6, size = 5) {
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

export function h(tag, attrs = {}, ...children) {
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
export function vaultDialog({ mode, path, drive, minLength, submit }) {
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


export function openSettings(provider) {
  // Open the SnackNodes sidebar tab (and point it at a drive). The tab store is reactive.
  const store = app.extensionManager?.sidebarTab;
  if (store && store.activeSidebarTabId !== SETTINGS_TAB) {
    if (store.toggleSidebarTab) store.toggleSidebarTab(SETTINGS_TAB);
    else store.activeSidebarTabId = SETTINGS_TAB;
  }
  window.dispatchEvent(new CustomEvent("snacknodes:focus-drive", { detail: { provider } }));
}

export function changed(provider) {
  window.dispatchEvent(new CustomEvent(CHANGED, { detail: { provider } }));
}
