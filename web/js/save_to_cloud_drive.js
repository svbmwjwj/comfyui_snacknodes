// Shows the upload result of "Save to Cloud Drive" on the node.
// - wait_for_upload on: the result arrives with the node's output (onExecuted).
// - background uploads (default): the node only queues the files; progress, completion and failures
//   arrive later as "snacknodes.upload" websocket events from the upload queue (cloud_drive/uploads.py).
import { app } from "../../../scripts/app.js";
import { ComfyWidgets } from "../../../scripts/widgets.js";
import { api } from "../../../scripts/api.js";

const NODE = "SnackSaveToCloudDrive";
const WIDGET = "upload_result";

function isChinese() {
  const locale = app.ui?.settings?.getSettingValue?.("Comfy.Locale") || navigator.language || "";
  return locale.toLowerCase().startsWith("zh");
}
const T = (zh, en) => (isChinese() ? zh : en);
const tr = (pair) => (pair ? (isChinese() ? pair.zh : pair.en) || pair.en || "" : "");

const NEW_WIDTH = 360; // default width of a new node (about three canvas grid cells)

function toast(severity, summary, detail) {
  const t = app.extensionManager?.toast;
  if (t?.add) t.add({ severity, summary, detail, life: severity === "error" ? 10000 : 4000 });
}

function mb(n) {
  return `${(n / 1048576).toFixed(1)} MB`;
}

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

// Text for a background job snapshot (see UploadQueue.snapshot).
function jobText(job) {
  const files = job.files || [];
  const done = files.filter((f) => f.state === "done");
  const where = `${job.provider_label} / ${job.remote_folder}`;
  if (job.state === "done") {
    return summary(done.map((f) => f.result || f.name), true, files.length);
  }
  if (job.state === "failed") {
    return summary(done.map((f) => f.result || f.name), false, files.length, job.error) +
      "\n\n" + T("可以点下面的「重试上传」；本地文件会保留到上传成功为止。",
        "Click Retry upload below; the local files are kept until the upload succeeds.");
  }
  if (job.state === "waiting") {
    const at = new Date(job.next_try * 1000).toLocaleTimeString();
    return T(`⏸ 暂时上传不了，${at} 自动重试（第 ${job.attempts} 次）\n`,
      `⏸ Upload paused; retrying automatically at ${at} (attempt ${job.attempts})\n`) +
      tr(job.error) + `\n${where}`;
  }
  if (job.state === "queued") {
    return T(`⏳ 已加入上传队列：${files.length} 个文件 → ${where}\n后台上传，工作流不用等。`,
      `⏳ Queued: ${files.length} file(s) → ${where}\nUploading in the background; the workflow does not wait.`);
  }
  // running
  const index = files.findIndex((f) => f.state !== "done");
  const f = files[index] || files[files.length - 1];
  const pct = job.total ? Math.floor((100 * job.sent) / job.total) : 0;
  return T(`⬆ 后台上传中 ${pct}% · ${index + 1}/${files.length} · ${f.name} · ${mb(f.sent)}/${mb(f.size)}\n→ ${where}`,
    `⬆ Uploading in the background ${pct}% · ${index + 1}/${files.length} · ${f.name} · ${mb(f.sent)}/${mb(f.size)}\n→ ${where}`);
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

// Native "Retry upload" / "Cancel" buttons under the result while a background upload has failed.
function setJobButtons(node, job) {
  const names = ["snack_upload_retry", "snack_upload_cancel"];
  const existing = (node.widgets || []).filter((w) => names.includes(w.name));
  if (job?.state === "failed" && existing.length && existing[0].snackJob === job.id) return;
  for (const w of existing) {
    if (node.removeWidget) node.removeWidget(w);
    else node.widgets.splice(node.widgets.indexOf(w), 1);
  }
  if (job?.state !== "failed") return;
  const button = (name, label, action) => {
    const w = node.addCustomWidget({
      type: "button", name, label, value: null, serialize: false, options: { serialize: false },
      callback: async () => {
        try {
          const resp = await api.fetchApi(`/snacknodes/uploads/${job.id}/${action}`, { method: "POST" });
          const data = await resp.json().catch(() => ({}));
          if (!resp.ok) throw data.error || { zh: `HTTP ${resp.status}`, en: `HTTP ${resp.status}` };
          if (action === "cancel") {
            setJobButtons(node, null);
            showResult(node, T("已取消这次上传。", "Upload cancelled."), 2);
          }
        } catch (e) {
          toast("error", T("操作失败", "Failed"), tr(e));
        }
      },
    });
    w.serialize = false;
    w.snackJob = job.id;
    return w;
  };
  button(names[0], T("重试上传", "Retry upload"), "retry");
  button(names[1], T("取消（删除为上传保留的文件）", "Cancel (delete files kept for upload)"), "cancel");
  node.setSize?.([node.size[0], Math.max(node.size[1], node.computeSize()[1])]);
}

function graphNodes() {
  return app.graph?._nodes || app.graph?.nodes || [];
}

function nodeForJob(job) {
  const nodes = graphNodes().filter((n) => n.type === NODE);
  return nodes.find((n) => n.snackJob === job.id) ||
    nodes.find((n) => String(n.id) === String(job.node_id) && (!n.snackJob || job.state === "queued"));
}

function renderJob(job) {
  const node = nodeForJob(job);
  if (!node) return;
  node.snackJob = job.id;
  const text = jobText(job);
  showResult(node, text, text.split("\n").length + 1);
  setJobButtons(node, job);
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

    // Background uploads: progress and results come from the server's upload queue.
    api.addEventListener("snacknodes.upload", ({ detail }) => {
      const job = detail?.job;
      if (!job) return;
      renderJob(job);
      const where = `${job.provider_label} / ${job.remote_folder}`;
      if (detail.type === "done") {
        toast("success", T("上传完成", "Upload finished"),
          T(`${job.files.length} 个文件已上传到 ${where}`, `${job.files.length} file(s) uploaded to ${where}`));
      } else if (detail.type === "failed") {
        toast("error", T("上传失败", "Upload failed"),
          `${tr(job.error)}\n${T("在节点上可以重试。", "You can retry it on the node.")}`);
      }
    });
  },

  async afterConfigureGraph() {
    // After a reload, show uploads that are still running (or failed) on their nodes again.
    try {
      const resp = await api.fetchApi("/snacknodes/uploads");
      if (!resp.ok) return;
      const { jobs } = await resp.json();
      for (const job of jobs || []) if (job.state !== "done") renderJob(job);
    } catch { /* older server: nothing to show */ }
  },

  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== NODE) return;

    const onNodeCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      onNodeCreated?.apply(this, arguments);
      // The node has a VIDEO input, so the Vue node UI would otherwise play the previews as video.
      this.previewMediaType = "image";
      this.setSize([NEW_WIDTH, this.size[1]]);
    };

    const onExecuted = nodeType.prototype.onExecuted;
    nodeType.prototype.onExecuted = function (message) {
      onExecuted?.apply(this, arguments);
      const job = message?.upload_job?.[0];
      if (job) {
        // Background upload: the queue's own events may already have moved it on; only claim it here.
        if (this.snackJob !== job.id) {
          this.snackJob = job.id;
          const text = jobText(job);
          showResult(this, text, text.split("\n").length + 1);
          setJobButtons(this, job);
        }
        return;
      }
      this.snackJob = null;
      setJobButtons(this, null);
      const lines = String(message?.text?.[0] ?? "").split("\n").filter(Boolean);
      const ok = message?.upload_ok?.[0] !== false;
      const error = message?.upload_error?.[0];
      if (!lines.length && !error) return;
      showResult(this, summary(lines, ok, message?.upload_total?.[0] ?? lines.length, error),
                 lines.length + (error ? 7 : 1));
    };
  },
});
