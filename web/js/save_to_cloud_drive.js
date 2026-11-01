// Shows the upload result of "Save to Cloud Drive" on the node after each run.
import { app } from "../../../scripts/app.js";
import { ComfyWidgets } from "../../../scripts/widgets.js";

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
  if (error) body.push(error);
  return [head, ...body].join("\n");
}

app.registerExtension({
  name: "SnackNodes.SaveToCloudDrive",
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
      let widget = this.widgets?.find((w) => w.name === WIDGET);
      if (!widget) {
        widget = ComfyWidgets.STRING(this, WIDGET, ["STRING", { multiline: true }], app).widget;
        widget.label = isChinese() ? "上传结果" : "upload result";
        widget.serialize = false; // display only: never stored in the workflow
        widget.options = { ...widget.options, serialize: false };
        if (widget.element) {
          widget.element.readOnly = true;
          widget.element.style.opacity = "0.85";
        }
      }
      widget.value = summary(lines, ok, message?.upload_total?.[0] ?? lines.length, error);
      // Grow with the number of lines (head line + one per file), capped so big batches stay compact.
      const rows = Math.min(lines.length + (error ? 3 : 1), 8);
      widget.options = { ...widget.options, getMinHeight: () => rows * 20 + 16 };
      this.setSize?.([this.size[0], Math.max(this.size[1], this.computeSize()[1])]);
      app.graph.setDirtyCanvas(true, true);
    };
  },
});
