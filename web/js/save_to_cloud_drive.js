// Shows the upload result of "Save to Cloud Drive" on the node after each run.
import { app } from "../../../scripts/app.js";
import { ComfyWidgets } from "../../../scripts/widgets.js";
import { api } from "../../../scripts/api.js";

const NODE = "SnackSaveToCloudDrive";
const WIDGET = "upload_result";

function isChinese() {
  const locale = app.ui?.settings?.getSettingValue?.("Comfy.Locale") || navigator.language || "";
  return locale.toLowerCase().startsWith("zh");
}

const MIN_WIDTH = 480; // fits "remote_folder  ComfyUI/%date:yyyy-MM-dd%" without truncation

function summary(lines, ok, total, error) {
  const zh = isChinese();
  const encrypted = lines.filter((l) => l.endsWith("[encrypted]")).length;
  let head;
  if (ok) {
    head = zh ? `✅ 已上传 ${lines.length} 个文件` : `✅ Uploaded ${lines.length} file(s)`;
    if (encrypted) head += zh ? `（${encrypted} 个已加密）` : ` (${encrypted} encrypted)`;
  } else {
    head = zh ? `❌ 上传失败（已完成 ${lines.length}/${total}）` : `❌ Upload failed (${lines.length}/${total} done)`;
  }
  const body = lines.map((l) => "• " + l.replace(/ \[encrypted\]$/, " 🔒"));
  if (error) {
    // error = {code, zh, en, detail}: friendly text in the UI language, then the technical detail
    body.push((zh ? error.zh : error.en) || "", "", (zh ? "详细信息：" : "Details: ") + (error.detail || ""));
  }
  return [head, ...body].join("\n");
}

function showResult(node, text, rows) {
  let widget = node.widgets?.find((w) => w.name === WIDGET);
  if (!widget) {
    widget = ComfyWidgets.STRING(node, WIDGET, ["STRING", { multiline: true }], app).widget;
    widget.label = isChinese() ? "上传结果" : "upload result";
    widget.serialize = false; // display only: never stored in the workflow
    widget.options = { ...widget.options, serialize: false };
    if (widget.element) {
      widget.element.readOnly = true;
      widget.element.style.opacity = "0.85";
    }
  }
  widget.value = text;
  // Grow with the content, capped so big batches stay compact.
  const height = Math.min(rows, 10) * 20 + 16;
  widget.options = { ...widget.options, getMinHeight: () => height };
  node.setSize?.([node.size[0], Math.max(node.size[1], node.computeSize()[1])]);
  app.graph.setDirtyCanvas(true, true);
}

app.registerExtension({
  name: "SnackNodes.SaveToCloudDrive",
  setup() {
    // With stop_on_error on, the node raises and never sends "executed"; ComfyUI's own error toast is
    // brief, so also put the (already localized) explanation on the node itself.
    api.addEventListener("execution_error", ({ detail }) => {
      if (detail?.node_type !== NODE) return;
      const node = app.graph?.getNodeById?.(Number(detail.node_id)) ?? app.graph?.getNodeById?.(detail.node_id);
      if (!node) return;
      const zh = isChinese();
      const text = (zh ? "❌ 上传失败\n" : "❌ Upload failed\n") + String(detail.exception_message || "").trim();
      showResult(node, text, text.split("\n").length + 1);
    });
  },
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== NODE) return;

    const onNodeCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      onNodeCreated?.apply(this, arguments);
      // The node has a VIDEO input, so the Vue node UI would otherwise play the previews as video.
      this.previewMediaType = "image";
      if (this.size[0] < MIN_WIDTH) this.setSize([MIN_WIDTH, this.size[1]]);
    };

    const onExecuted = nodeType.prototype.onExecuted;
    nodeType.prototype.onExecuted = function (message) {
      onExecuted?.apply(this, arguments);
      const lines = String(message?.text?.[0] ?? "").split("\n").filter(Boolean);
      const ok = message?.upload_ok?.[0] !== false;
      const error = message?.upload_error?.[0];
      if (!lines.length && !error) return;
      showResult(this, summary(lines, ok, message?.upload_total?.[0] ?? lines.length, error),
                 lines.length + (error ? 7 : 1));
    };
  },
});
