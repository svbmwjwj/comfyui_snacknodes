import { app } from "/scripts/app.js";
import { ComfyWidgets } from "/scripts/widgets.js";

// Register extension to display text processing results
app.registerExtension({
    name: "SnackNodes.TextProcessor",
    
    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        if (nodeData.name === "TextProcessor") {
            const onExecuted = nodeType.prototype.onExecuted;
            
            nodeType.prototype.onExecuted = function (message) {
                onExecuted?.apply(this, arguments);
                
                // Cleanup existing result widget
                if (this.widgets) {
                    const pos = this.widgets.findIndex((w) => w.name === "result");
                    if (pos !== -1) {
                        for (let i = pos; i < this.widgets.length; i++) {
                            this.widgets[i].onRemove?.();
                        }
                        this.widgets.length = pos;
                    }
                }
                
                // Create new result widget
                const w = ComfyWidgets["STRING"](this, "result", ["STRING", { multiline: true }], app).widget;
                w.inputEl.readOnly = true;
                w.inputEl.style.opacity = 0.6;
                w.value = message.text[0];
                
                // Resize node
                this.onResize?.(this.size);
            };
        }
    },
});
