// One status line on Save to Cloud Drive, right below the drive dropdown:
//   ✓ 已连接：存储桶 comfy，上限 10 GB · 🔒 保险库 ComfyUI-Vault
//   ⚠ 未连接 · 点此在侧边栏连接
// Clicking it opens the SnackNodes sidebar tab (settings_panel.js), where drives and vaults are set up.
//
// Frontend notes (checked against comfyui_frontend_package 1.57):
// - node.widgets is a tracked array: splice() also updates the Nodes 2.0 (Vue) widget order.
// - addCustomWidget restores a saved value by position only for widgets with serialize !== false,
//   so the row is created with serialize: false already set, and only after an async status request
//   (i.e. after the node was configured from a workflow), so it never shifts saved widget values.
import { app } from "../../../scripts/app.js";
import { CHANGED, NODE, PROVIDERS, T, call, openSettings, t, vaultCall } from "./snack_common.js";

const ANCHOR = "provider";
const ROW = "snack_drive_status";

const shorten = (text, max = 56) => (text.length > max ? text.slice(0, max - 1) + "…" : text);

class StatusRow {
  constructor(node) {
    this.node = node;
    this.widget = null;
    this.seq = 0;
  }

  value(name) {
    return this.node.widgets?.find((w) => w.name === name)?.value;
  }

  provider() {
    return PROVIDERS[this.value(ANCHOR)];
  }

  async refresh() {
    const provider = this.provider();
    const seq = ++this.seq;
    if (!provider) return this.show(null);
    let text, tip;
    try {
      const status = await call(provider);
      if (!status.connected) {
        text = T("⚠ 未连接 · 点此在侧边栏连接", "⚠ Not connected · click to connect in the sidebar");
      } else {
        const summary = t(status.summary);
        text = "✓ " + T("已连接", "Connected") + (summary ? T("：", ": ") + summary : "");
        if (this.value("encrypt")) {
          const vault = await vaultCall(provider);
          text += vault.vault ? T(` · 🔒 保险库 ${vault.vault.path}`, ` · 🔒 vault ${vault.vault.path}`)
            : T(" · ⚠ 已开加密但没有保险库，点此设置", " · ⚠ encrypt is on but no vault, click to set up");
        }
      }
      tip = T("连接网盘、设置保险库：左侧边栏 SnackNodes（点此打开）", "Drives and vaults: SnackNodes in the left sidebar (click to open)");
    } catch (e) {
      text = "⚠ " + t(e);
      tip = t(e);
    }
    if (seq === this.seq && this.node.graph) this.show(shorten(text), tip);
  }

  show(text, tip = "") {
    const node = this.node;
    if (!text) {
      if (this.widget && node.widgets?.includes(this.widget)) {
        if (node.removeWidget) node.removeWidget(this.widget);
        else node.widgets.splice(node.widgets.indexOf(this.widget), 1);
      }
      this.widget = null;
      return;
    }
    if (!this.widget || !node.widgets?.includes(this.widget)) {
      const before = node.computeSize?.()[1] ?? 0;
      const w = node.addCustomWidget({
        type: "button", name: ROW, label: text, value: null, serialize: false, options: { serialize: false },
        callback: () => openSettings(this.provider()),
      });
      w.serialize = false;
      w.options = { ...(w.options || {}), serialize: false };
      // addCustomWidget appends: move the row right below the drive dropdown
      node.widgets.splice(node.widgets.indexOf(w), 1);
      const at = node.widgets.findIndex((x) => x.name === ANCHOR) + 1 || node.widgets.length;
      node.widgets.splice(at, 0, w);
      this.widget = w;
      const after = node.computeSize?.()[1] ?? 0;
      if (node.size && after) node.setSize([node.size[0], Math.max(after, node.size[1] + after - before)]);
    }
    this.widget.label = text;
    this.widget.tooltip = tip;
    node.graph?.setDirtyCanvas(true, true);
  }
}

app.registerExtension({
  name: "SnackNodes.DriveStatus",
  setup() {
    // a drive or vault changed in the sidebar: update every node's status line
    window.addEventListener(CHANGED, () => {
      for (const node of app.graph?._nodes || app.graph?.nodes || []) node.snackStatus?.refresh();
    });
  },
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== NODE) return;

    const onNodeCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const r = onNodeCreated?.apply(this, arguments);
      const row = new StatusRow(this);
      this.snackStatus = row;
      for (const name of [ANCHOR, "encrypt"]) {
        const widget = this.widgets?.find((w) => w.name === name);
        if (!widget) continue;
        const callback = widget.callback;
        widget.callback = function () {
          const out = callback?.apply(this, arguments);
          row.refresh();
          return out;
        };
      }
      // after a workflow is loaded the values are set without their callbacks: check again then
      setTimeout(() => row.refresh(), 0);
      return r;
    };

    const onConfigure = nodeType.prototype.onConfigure;
    nodeType.prototype.onConfigure = function () {
      const r = onConfigure?.apply(this, arguments);
      setTimeout(() => this.snackStatus?.refresh(), 0);
      return r;
    };
  },
});
