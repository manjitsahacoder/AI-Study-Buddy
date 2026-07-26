(function () {
    function setButtonLabel(button, activeLabel, inactiveLabel, isActive) {
        if (button) {
            button.textContent = isActive ? activeLabel : inactiveLabel;
        }
    }

    function element(tagName, className, text) {
        const item = document.createElement(tagName);
        if (className) {
            item.className = className;
        }
        if (text !== undefined) {
            item.textContent = text;
        }
        return item;
    }

    function removeHydratedContent(card) {
        Array.from(card.children).forEach(function (child, index) {
            if (index > 0) {
                child.remove();
            }
        });
    }

    function payloadTypeLabel(payload) {
        const raw = (payload && (payload.visualization_label || payload.type || payload.visualization_type)) || "Educational Diagram";
        return String(raw).replace(/_/g, " ").replace(/\b\w/g, function (letter) {
            return letter.toUpperCase();
        });
    }

    function renderInfoCard(card, title, lines, listItems) {
        removeHydratedContent(card);
        const info = element("div", "visualization-info-card");
        info.setAttribute("role", "note");
        info.setAttribute("aria-label", title);
        const icon = element("span", "visualization-info-icon");
        icon.setAttribute("aria-hidden", "true");
        icon.innerHTML = "&#9432;";
        const body = element("div");
        body.appendChild(element("h3", "", title));
        lines.forEach(function (line) {
            body.appendChild(element("p", "", line));
        });
        if (Array.isArray(listItems) && listItems.length) {
            const list = element("ul", "diagram-learning-list");
            listItems.forEach(function (item) {
                list.appendChild(element("li", "", item));
            });
            body.appendChild(list);
        }
        info.append(icon, body);
        card.appendChild(info);
    }

    function retryEndpoint(endpoint, body) {
        if (body && body.retry_url) {
            return body.retry_url;
        }
        return endpoint + (endpoint.indexOf("?") === -1 ? "?retry=1" : "&retry=1");
    }

    function renderDiagramFailure(card, endpoint, body) {
        removeHydratedContent(card);
        const info = element("div", "visualization-info-card diagram-unavailable-card");
        info.setAttribute("role", "note");
        info.setAttribute("aria-label", "Educational diagram unavailable");
        const icon = element("span", "visualization-info-icon");
        icon.setAttribute("aria-hidden", "true");
        icon.innerHTML = "&#9432;";
        const copy = element("div");
        copy.appendChild(element("h3", "", "Educational Diagram"));
        copy.appendChild(element("p", "", (body && body.message) || "We could not create the diagram right now."));
        const retry = element("button", "button-link secondary-link", "Retry diagram");
        retry.type = "button";
        retry.addEventListener("click", function () {
            const nextEndpoint = retryEndpoint(endpoint, body || {});
            retry.disabled = true;
            retry.textContent = "Retrying...";
            hydratePendingDiagram(card, nextEndpoint);
        });
        copy.appendChild(retry);
        info.append(icon, copy);
        card.appendChild(info);
    }

    function scheduleDiagramPoll(card, endpoint) {
        window.setTimeout(function () {
            hydratePendingDiagram(card, endpoint);
        }, 1800);
    }

    function renderDiagramReady(card, body) {
        const payload = body.diagram_payload || {};
        const view = body.diagram_view || {};
        removeHydratedContent(card);
        card.removeAttribute("data-diagram-pending-url");

        const insights = element("div", "visualization-insights");
        insights.setAttribute("aria-label", "Diagram selection details");
        [
            ["Selected Type", payloadTypeLabel(payload)],
            ["Confidence", `${payload.confidence_percent || 0}%`],
            ["Source", view.provider || "AI Study Buddy", "visualization-reason"]
        ].forEach(function (entry) {
            const block = element("div", entry[2] || "");
            block.append(element("span", "", entry[0]), element("strong", "", entry[1]));
            insights.appendChild(block);
        });
        card.appendChild(insights);

        const toolbar = element("div", "diagram-library-toolbar");
        toolbar.setAttribute("aria-label", "Educational diagram controls");
        const zoom = element("button", "button-link secondary-link", "Zoom");
        zoom.type = "button";
        zoom.setAttribute("data-diagram-zoom", "");
        const fullscreen = element("button", "button-link secondary-link", "Fullscreen");
        fullscreen.type = "button";
        fullscreen.setAttribute("data-diagram-fullscreen", "");
        toolbar.append(zoom, fullscreen);
        if (body.download_url) {
            const download = element("a", "button-link secondary-link", "Download PNG");
            download.href = body.download_url;
            toolbar.appendChild(download);
        }
        card.appendChild(toolbar);

        const figure = element("figure", "diagram-library-figure");
        figure.setAttribute("data-diagram-figure", "");
        const shell = element("div", "diagram-library-image-shell");
        const image = element("img", "diagram-library-image");
        image.src = view.image_url || "";
        image.alt = `${card.dataset.topic || "Lesson"} educational diagram`;
        image.loading = "lazy";
        image.setAttribute("data-diagram-image", "");
        shell.appendChild(image);
        const attribution = element("figcaption", "diagram-library-attribution");
        [
            ["Diagram Source", view.provider || "AI Study Buddy", view.source_url],
            ["Author", view.author || "AI Study Buddy"],
            ["License", view.license || "Generated educational diagram"]
        ].forEach(function (entry) {
            const span = element("span");
            span.appendChild(element("strong", "", entry[0]));
            span.appendChild(document.createTextNode(" "));
            if (entry[2]) {
                const link = element("a", "", entry[1]);
                link.href = entry[2];
                link.target = "_blank";
                link.rel = "noopener noreferrer";
                span.appendChild(link);
            } else {
                span.appendChild(document.createTextNode(entry[1]));
            }
            attribution.appendChild(span);
        });
        figure.append(shell, attribution);
        card.appendChild(figure);

        if (body.explanation_url) {
            const lesson = body.lesson || {};
            const panel = element("section", "diagram-explanation-panel");
            panel.setAttribute("aria-label", "AI textbook diagram explanation");
            panel.setAttribute("data-diagram-explanation-panel", "");
            panel.dataset.explanationUrl = body.explanation_url;
            panel.dataset.learnUrl = "/learn";
            panel.dataset.lessonName = lesson.name || "Student";
            panel.dataset.lessonClass = lesson.student_class || "";
            panel.dataset.lessonSubject = lesson.subject || "";
            panel.dataset.lessonBook = lesson.book_name || "";
            const status = element("div", "diagram-explanation-status");
            status.setAttribute("data-diagram-explanation-status", "");
            const spinner = element("span", "diagram-explanation-spinner");
            spinner.setAttribute("aria-hidden", "true");
            status.append(spinner, element("span", "", "Preparing textbook explanation..."));
            const content = element("div", "diagram-explanation-grid");
            content.setAttribute("data-diagram-explanation-content", "");
            content.hidden = true;
            panel.append(status, content);
            card.appendChild(panel);
            initDiagramExplanation(panel);
        }

        const lightbox = element("div", "diagram-lightbox");
        lightbox.setAttribute("role", "dialog");
        lightbox.setAttribute("aria-modal", "true");
        lightbox.setAttribute("aria-label", `${card.dataset.topic || "Lesson"} full-size educational diagram`);
        lightbox.setAttribute("data-diagram-lightbox", "");
        lightbox.hidden = true;
        const close = element("button", "diagram-lightbox-close", "Close");
        close.type = "button";
        close.setAttribute("data-diagram-lightbox-close", "");
        const stage = element("div", "diagram-lightbox-stage");
        const fullImage = element("img", "diagram-lightbox-image");
        fullImage.src = view.image_url || "";
        fullImage.alt = `${card.dataset.topic || "Lesson"} educational diagram full size`;
        stage.appendChild(fullImage);
        lightbox.append(close, stage);
        card.appendChild(lightbox);

        initDiagramCard(card);
    }

    function hydratePendingDiagram(card, endpoint) {
        if (card.dataset.diagramHydrating === "true" || !window.fetch) {
            return;
        }
        card.dataset.diagramHydrating = "true";
        fetch(endpoint, { headers: { "Accept": "application/json" } })
            .then(function (response) {
                return response.json().then(function (body) {
                    if (!response.ok) {
                        throw new Error(body.error || "Unable to load the educational diagram.");
                    }
                    return body;
                });
            })
            .then(function (body) {
                card.dataset.diagramHydrating = "false";
                if (body.status === "ready") {
                    renderDiagramReady(card, body);
                } else if (body.status === "not_required") {
                    renderInfoCard(card, "AI Visualization", [
                        "This lesson is primarily text-based and does not require a visual diagram.",
                        "AI Study Buddy has automatically focused on notes, revision, flashcards, quizzes, memory challenge, and AI Tutor instead."
                    ]);
                } else if (body.status === "failed") {
                    renderDiagramFailure(card, endpoint, body);
                } else if (body.status === "pending" || body.status === "generating") {
                    const message = card.querySelector("[data-diagram-progress-message]");
                    if (message) {
                        message.textContent = body.message || "Creating your educational diagram...";
                    }
                    scheduleDiagramPoll(card, endpoint);
                } else {
                    renderInfoCard(card, "Educational Diagram", [
                        "No suitable educational diagram found.",
                        "Continue learning using:"
                    ], ["Notes", "Revision", "Flashcards", "Memory Challenge", "AI Tutor", "Quiz"]);
                }
            })
            .catch(function (error) {
                card.dataset.diagramHydrating = "false";
                const message = card.querySelector("[data-diagram-progress-message]");
                if (message) {
                    message.textContent = error.message || "The educational diagram is unavailable right now.";
                }
            });
    }

    function initDiagramCard(card) {
        const pendingUrl = card.dataset.diagramPendingUrl;
        if (pendingUrl) {
            hydratePendingDiagram(card, pendingUrl);
        }

        const image = card.querySelector("[data-diagram-image]");
        const zoomButton = card.querySelector("[data-diagram-zoom]");
        const fullscreenButton = card.querySelector("[data-diagram-fullscreen]");
        const lightbox = card.querySelector("[data-diagram-lightbox]");
        const lightboxClose = card.querySelector("[data-diagram-lightbox-close]");
        if (!image) {
            return;
        }

        function markLoaded() {
            image.classList.add("is-loaded");
        }

        if (image.complete) {
            markLoaded();
        } else {
            image.addEventListener("load", markLoaded, { once: true });
            image.addEventListener("error", markLoaded, { once: true });
        }

        function openLightbox() {
            if (!lightbox) {
                return;
            }
            lightbox.hidden = false;
            document.body.classList.add("diagram-lightbox-open");
            lightboxClose?.focus();
        }

        function closeLightbox() {
            if (!lightbox || lightbox.hidden) {
                return;
            }
            lightbox.hidden = true;
            document.body.classList.remove("diagram-lightbox-open");
            zoomButton?.focus();
        }

        image.addEventListener("click", openLightbox);
        zoomButton?.addEventListener("click", openLightbox);
        lightboxClose?.addEventListener("click", closeLightbox);
        lightbox?.addEventListener("click", function (event) {
            if (event.target === lightbox) {
                closeLightbox();
            }
        });

        fullscreenButton?.addEventListener("click", function () {
            card.classList.toggle("is-fullscreen");
            setButtonLabel(fullscreenButton, "Exit Fullscreen", "Fullscreen", card.classList.contains("is-fullscreen"));
        });

        document.addEventListener("keydown", function (event) {
            if (event.key !== "Escape") {
                return;
            }
            closeLightbox();
            if (!card.classList.contains("is-fullscreen")) {
                return;
            }
            card.classList.remove("is-fullscreen");
            setButtonLabel(fullscreenButton, "Exit Fullscreen", "Fullscreen", false);
        });
    }

    const SECTION_META = {
        summary: { title: "What does this diagram show?", icon: "&#128214;" },
        steps: { title: "Step-by-Step Explanation", icon: "&#128218;" },
        labels: { title: "Important Labels", icon: "&#127991;" },
        keyPoints: { title: "Key Points to Remember", icon: "&#11088;" },
        examTip: { title: "NCERT Exam Tip", icon: "&#128221;" },
        relatedTopics: { title: "Related Topics", icon: "&#127919;" }
    };

    function textValue(value) {
        return String(value || "").trim();
    }

    function appendHeading(card, meta) {
        const heading = document.createElement("h3");
        const icon = document.createElement("span");
        icon.setAttribute("aria-hidden", "true");
        icon.innerHTML = meta.icon;
        heading.append(icon, document.createTextNode(meta.title));
        card.appendChild(heading);
    }

    function createCard(meta, wide) {
        const card = document.createElement("article");
        card.className = "diagram-explanation-card" + (wide ? " is-wide" : "");
        appendHeading(card, meta);
        return card;
    }

    function appendTextCard(container, meta, text, wide) {
        if (!textValue(text)) {
            return;
        }
        const card = createCard(meta, wide);
        const paragraph = document.createElement("p");
        paragraph.textContent = textValue(text);
        card.appendChild(paragraph);
        container.appendChild(card);
    }

    function appendItemListCard(container, meta, items) {
        if (!Array.isArray(items) || !items.length) {
            return;
        }
        const card = createCard(meta, false);
        const list = document.createElement("ul");
        list.className = "diagram-explanation-list";
        items.forEach(function (item) {
            const title = textValue(item && item.title);
            const body = textValue(item && item.body);
            if (!title && !body) {
                return;
            }
            const listItem = document.createElement("li");
            if (title) {
                const strong = document.createElement("strong");
                strong.textContent = title;
                listItem.appendChild(strong);
            }
            if (body) {
                const span = document.createElement("span");
                span.textContent = body;
                listItem.appendChild(span);
            }
            list.appendChild(listItem);
        });
        if (list.children.length) {
            card.appendChild(list);
            container.appendChild(card);
        }
    }

    function appendBulletCard(container, meta, items) {
        if (!Array.isArray(items) || !items.length) {
            return;
        }
        const card = createCard(meta, false);
        const list = document.createElement("ul");
        list.className = "diagram-key-points";
        items.forEach(function (item) {
            const text = textValue(item);
            if (!text) {
                return;
            }
            const listItem = document.createElement("li");
            listItem.textContent = text;
            list.appendChild(listItem);
        });
        if (list.children.length) {
            card.appendChild(list);
            container.appendChild(card);
        }
    }

    function appendRelatedTopicsCard(panel, container, meta, topics, lesson) {
        if (!Array.isArray(topics) || !topics.length) {
            return;
        }
        const card = createCard(meta, true);
        const topicWrap = document.createElement("div");
        topicWrap.className = "diagram-related-topics";
        const learnUrl = panel.dataset.learnUrl || "/learn";
        topics.forEach(function (topic) {
            const topicText = textValue(topic);
            if (!topicText) {
                return;
            }
            const form = document.createElement("form");
            form.method = "POST";
            form.action = learnUrl;
            [
                ["name", lesson.name || "Student"],
                ["student_class", lesson.student_class || ""],
                ["subject", lesson.subject || ""],
                ["book_name", lesson.book_name || ""],
                ["topic", topicText]
            ].forEach(function (entry) {
                const input = document.createElement("input");
                input.type = "hidden";
                input.name = entry[0];
                input.value = entry[1];
                form.appendChild(input);
            });
            const button = document.createElement("button");
            button.type = "submit";
            button.textContent = topicText;
            form.appendChild(button);
            topicWrap.appendChild(form);
        });
        if (topicWrap.children.length) {
            card.appendChild(topicWrap);
            container.appendChild(card);
        }
    }

    function panelLessonContext(panel) {
        return {
            name: panel.dataset.lessonName || "Student",
            student_class: panel.dataset.lessonClass || "",
            subject: panel.dataset.lessonSubject || "",
            book_name: panel.dataset.lessonBook || ""
        };
    }

    function renderDiagramExplanation(panel, payload, lesson) {
        const status = panel.querySelector("[data-diagram-explanation-status]");
        const content = panel.querySelector("[data-diagram-explanation-content]");
        if (!content) {
            return;
        }
        const explanation = payload || {};
        content.innerHTML = "";
        appendTextCard(content, SECTION_META.summary, explanation.summary, true);
        appendItemListCard(content, SECTION_META.steps, explanation.steps);
        appendItemListCard(content, SECTION_META.labels, explanation.labels);
        appendBulletCard(content, SECTION_META.keyPoints, explanation.key_points);
        appendTextCard(content, SECTION_META.examTip, explanation.exam_tip, false);
        appendRelatedTopicsCard(
            panel,
            content,
            SECTION_META.relatedTopics,
            explanation.related_topics,
            { ...panelLessonContext(panel), ...(lesson || {}) }
        );
        if (!content.children.length) {
            panel.classList.remove("is-loaded");
            if (status) {
                status.hidden = false;
                status.removeAttribute("aria-hidden");
                status.textContent = "The diagram explanation is unavailable right now.";
            }
            content.hidden = true;
            content.classList.remove("is-visible");
            return;
        }
        panel.classList.add("is-loaded");
        content.hidden = false;
        content.classList.add("is-visible");
        if (status) {
            status.setAttribute("aria-hidden", "true");
            window.setTimeout(function () {
                if (panel.classList.contains("is-loaded")) {
                    status.hidden = true;
                }
            }, 220);
        }
    }

    function initDiagramExplanation(panel) {
        const cachedScript = panel.querySelector("[data-diagram-explanation-json]");
        if (cachedScript && cachedScript.textContent.trim()) {
            try {
                renderDiagramExplanation(panel, JSON.parse(cachedScript.textContent), panelLessonContext(panel));
                return;
            } catch (error) {
                // Fall through to the lazy endpoint when cached JSON cannot be parsed.
            }
        }
        const endpoint = panel.dataset.explanationUrl;
        const status = panel.querySelector("[data-diagram-explanation-status]");
        if (!endpoint || !window.fetch) {
            if (status) {
                status.textContent = "The diagram explanation is unavailable right now.";
            }
            return;
        }
        panel.classList.add("is-loading");
        fetch(endpoint, { headers: { "Accept": "application/json" } })
            .then(function (response) {
                return response.json().then(function (body) {
                    if (!response.ok) {
                        throw new Error(body.error || "Unable to load diagram explanation.");
                    }
                    return body;
                });
            })
            .then(function (body) {
                panel.classList.remove("is-loading");
                renderDiagramExplanation(panel, body.explanation, body.lesson || {});
            })
            .catch(function (error) {
                panel.classList.remove("is-loading");
                panel.classList.remove("is-loaded");
                if (status) {
                    status.hidden = false;
                    status.removeAttribute("aria-hidden");
                    status.textContent = error.message || "The diagram explanation is unavailable right now.";
                }
            });
    }

    document.querySelectorAll("[data-diagram-library-card]").forEach(initDiagramCard);
    document.querySelectorAll("[data-diagram-explanation-panel]").forEach(initDiagramExplanation);
}());
