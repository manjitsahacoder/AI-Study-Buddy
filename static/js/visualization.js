(function () {
    function setButtonLabel(button, activeLabel, inactiveLabel, isActive) {
        if (button) {
            button.textContent = isActive ? activeLabel : inactiveLabel;
        }
    }

    function initDiagramCard(card) {
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
