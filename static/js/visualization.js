(function () {
    function fileName(topic, extension) {
        const safe = String(topic || "visualization")
            .trim()
            .replace(/[^A-Za-z0-9_-]+/g, "_")
            .replace(/^_+|_+$/g, "") || "visualization";
        return `${safe}.${extension}`;
    }

    function selectorEscape(value) {
        if (window.CSS && typeof window.CSS.escape === "function") {
            return window.CSS.escape(value);
        }
        return String(value).replace(/["\\]/g, "\\$&");
    }

    function downloadBlob(blob, name) {
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = name;
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(url);
    }

    function svgText(card) {
        const svg = card.querySelector("svg");
        if (!svg) {
            return "";
        }
        return new XMLSerializer().serializeToString(svg);
    }

    function svgToCanvas(card) {
        const svg = card.querySelector("svg");
        const serialized = svgText(card);
        if (!svg || !serialized) {
            return Promise.reject(new Error("Visualization SVG was not found."));
        }
        const viewBox = (svg.getAttribute("viewBox") || "0 0 1200 800").split(/\s+/).map(Number);
        const width = Math.max(900, Math.round(viewBox[2] || svg.clientWidth || 1200));
        const height = Math.max(560, Math.round(viewBox[3] || svg.clientHeight || 800));
        const canvas = document.createElement("canvas");
        const scale = Math.min(2, Math.max(1, window.devicePixelRatio || 1));
        canvas.width = width * scale;
        canvas.height = height * scale;
        const context = canvas.getContext("2d");
        context.fillStyle = getComputedStyle(document.body).getPropertyValue("--page-bg") || "#ffffff";
        context.fillRect(0, 0, canvas.width, canvas.height);
        const image = new Image();
        const svgBlob = new Blob([serialized], { type: "image/svg+xml;charset=utf-8" });
        const url = URL.createObjectURL(svgBlob);
        return new Promise(function (resolve, reject) {
            image.onload = function () {
                context.drawImage(image, 0, 0, canvas.width, canvas.height);
                URL.revokeObjectURL(url);
                resolve(canvas);
            };
            image.onerror = function () {
                URL.revokeObjectURL(url);
                reject(new Error("Could not render the visualization image."));
            };
            image.src = url;
        });
    }

    function bytesFromString(value) {
        const bytes = new Uint8Array(value.length);
        for (let index = 0; index < value.length; index += 1) {
            bytes[index] = value.charCodeAt(index) & 255;
        }
        return bytes;
    }

    function concatBytes(chunks) {
        const total = chunks.reduce(function (sum, chunk) { return sum + chunk.length; }, 0);
        const out = new Uint8Array(total);
        let offset = 0;
        chunks.forEach(function (chunk) {
            out.set(chunk, offset);
            offset += chunk.length;
        });
        return out;
    }

    function makePdfFromJpeg(jpegDataUrl, imageWidth, imageHeight) {
        const binary = atob(jpegDataUrl.split(",")[1]);
        const imageBytes = bytesFromString(binary);
        const pageWidth = 842;
        const pageHeight = 595;
        const margin = 28;
        const scale = Math.min((pageWidth - margin * 2) / imageWidth, (pageHeight - margin * 2) / imageHeight);
        const drawWidth = imageWidth * scale;
        const drawHeight = imageHeight * scale;
        const x = (pageWidth - drawWidth) / 2;
        const y = (pageHeight - drawHeight) / 2;
        const content = `q\n${drawWidth.toFixed(2)} 0 0 ${drawHeight.toFixed(2)} ${x.toFixed(2)} ${y.toFixed(2)} cm\n/Im0 Do\nQ\n`;
        const chunks = [];
        const offsets = [0];
        let position = 0;

        function pushText(text) {
            const bytes = new TextEncoder().encode(text);
            chunks.push(bytes);
            position += bytes.length;
        }

        function pushObject(id, body) {
            offsets[id] = position;
            pushText(`${id} 0 obj\n${body}\nendobj\n`);
        }

        pushText("%PDF-1.4\n");
        pushObject(1, "<< /Type /Catalog /Pages 2 0 R >>");
        pushObject(2, "<< /Type /Pages /Kids [3 0 R] /Count 1 >>");
        pushObject(3, `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${pageWidth} ${pageHeight}] /Resources << /XObject << /Im0 4 0 R >> >> /Contents 5 0 R >>`);
        offsets[4] = position;
        pushText(`4 0 obj\n<< /Type /XObject /Subtype /Image /Width ${imageWidth} /Height ${imageHeight} /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length ${imageBytes.length} >>\nstream\n`);
        chunks.push(imageBytes);
        position += imageBytes.length;
        pushText("\nendstream\nendobj\n");
        pushObject(5, `<< /Length ${content.length} >>\nstream\n${content}endstream`);
        const xrefAt = position;
        pushText(`xref\n0 6\n0000000000 65535 f \n`);
        for (let id = 1; id <= 5; id += 1) {
            pushText(`${String(offsets[id]).padStart(10, "0")} 00000 n \n`);
        }
        pushText(`trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n${xrefAt}\n%%EOF`);
        return new Blob([concatBytes(chunks)], { type: "application/pdf" });
    }

    function initCard(card) {
        const stage = card.querySelector("[data-viz-stage]");
        const layer = card.querySelector("[data-viz-pan-layer]");
        if (!stage || !layer) {
            return;
        }

        const state = { scale: 1, x: 0, y: 0, dragging: false, startX: 0, startY: 0 };

        function applyTransform() {
            layer.style.transform = `translate(${state.x}px, ${state.y}px) scale(${state.scale})`;
        }

        function zoom(delta) {
            state.scale = Math.max(0.45, Math.min(2.8, state.scale + delta));
            applyTransform();
        }

        card.querySelector("[data-viz-zoom-in]")?.addEventListener("click", function () { zoom(0.15); });
        card.querySelector("[data-viz-zoom-out]")?.addEventListener("click", function () { zoom(-0.15); });
        card.querySelector("[data-viz-reset]")?.addEventListener("click", function () {
            state.scale = 1;
            state.x = 0;
            state.y = 0;
            applyTransform();
        });
        card.querySelector("[data-viz-fullscreen]")?.addEventListener("click", function (event) {
            card.classList.toggle("is-fullscreen");
            event.currentTarget.textContent = card.classList.contains("is-fullscreen") ? "Exit Full Screen" : "Full Screen";
        });

        stage.addEventListener("pointerdown", function (event) {
            if (event.target.closest(".viz-node")) {
                return;
            }
            stage.setPointerCapture(event.pointerId);
            stage.classList.add("is-dragging");
            state.dragging = true;
            state.startX = event.clientX - state.x;
            state.startY = event.clientY - state.y;
        });
        stage.addEventListener("pointermove", function (event) {
            if (!state.dragging) {
                return;
            }
            state.x = event.clientX - state.startX;
            state.y = event.clientY - state.startY;
            applyTransform();
        });
        ["pointerup", "pointercancel", "pointerleave"].forEach(function (eventName) {
            stage.addEventListener(eventName, function () {
                state.dragging = false;
                stage.classList.remove("is-dragging");
            });
        });
        stage.addEventListener("wheel", function (event) {
            if (!event.ctrlKey && !event.metaKey) {
                return;
            }
            event.preventDefault();
            zoom(event.deltaY < 0 ? 0.12 : -0.12);
        }, { passive: false });

        card.querySelectorAll(".viz-node").forEach(function (node) {
            node.addEventListener("click", function () {
                const id = node.dataset.nodeId;
                const alreadyActive = node.classList.contains("is-active");
                card.querySelectorAll(".viz-node").forEach(function (item) {
                    item.classList.remove("is-active", "is-dimmed");
                });
                card.querySelectorAll(".viz-edge").forEach(function (edge) {
                    edge.classList.remove("is-active");
                });
                if (alreadyActive) {
                    return;
                }
                node.classList.add("is-active");
                card.querySelectorAll(".viz-node").forEach(function (item) {
                    if (item !== node) {
                        item.classList.add("is-dimmed");
                    }
                });
                card.querySelectorAll(`.viz-edge[data-from="${selectorEscape(id)}"], .viz-edge[data-to="${selectorEscape(id)}"]`).forEach(function (edge) {
                    edge.classList.add("is-active");
                    const otherId = edge.dataset.from === id ? edge.dataset.to : edge.dataset.from;
                    card.querySelector(`.viz-node[data-node-id="${selectorEscape(otherId)}"]`)?.classList.remove("is-dimmed");
                });
            });
        });

        card.querySelector("[data-viz-download-png]")?.addEventListener("click", function () {
            svgToCanvas(card).then(function (canvas) {
                canvas.toBlob(function (blob) {
                    downloadBlob(blob, fileName(card.dataset.topic, "png"));
                }, "image/png");
            });
        });

        card.querySelector("[data-viz-download-pdf]")?.addEventListener("click", function () {
            svgToCanvas(card).then(function (canvas) {
                const dataUrl = canvas.toDataURL("image/jpeg", 0.92);
                const pdf = makePdfFromJpeg(dataUrl, canvas.width, canvas.height);
                downloadBlob(pdf, fileName(card.dataset.topic, "pdf"));
            });
        });
    }

    document.querySelectorAll("[data-visualization-card]").forEach(initCard);
}());
