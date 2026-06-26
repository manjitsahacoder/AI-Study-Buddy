(function () {
    const form = document.getElementById("tutor-form");
    const input = document.getElementById("tutor-input");
    const sendButton = document.getElementById("tutor-send");
    const messages = document.getElementById("tutor-messages");
    const quizTemplate = document.getElementById("tutor-quiz-cta-template");

    if (!form || !input || !messages) {
        return;
    }

    function escapeHtml(value) {
        return value
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    function scrollToLatest() {
        messages.scrollTop = messages.scrollHeight;
    }

    function resizeInput() {
        input.style.height = "auto";
        input.style.height = Math.min(input.scrollHeight, 180) + "px";
    }

    function quizCallToAction() {
        if (!quizTemplate) {
            return null;
        }
        return quizTemplate.content.firstElementChild.cloneNode(true);
    }

    function addMessage(sender, text, html) {
        const row = document.createElement("article");
        row.className = "tutor-message-row " + sender;

        if (sender === "assistant") {
            const avatar = document.createElement("div");
            avatar.className = "tutor-avatar";
            avatar.setAttribute("aria-hidden", "true");
            avatar.textContent = "\uD83C\uDFEB";
            row.appendChild(avatar);
        }

        const bubble = document.createElement("div");
        bubble.className = "tutor-message";

        const meta = document.createElement("div");
        meta.className = "tutor-message-meta";
        meta.textContent = sender === "student" ? "You" : "AI Tutor";
        bubble.appendChild(meta);

        const content = document.createElement("div");
        content.className = "tutor-message-content";
        if (sender === "assistant") {
            content.innerHTML = html || escapeHtml(text);
        } else {
            content.textContent = text;
        }
        bubble.appendChild(content);

        if (sender === "assistant") {
            const source = document.createElement("textarea");
            source.className = "tutor-message-source";
            source.hidden = true;
            source.readOnly = true;
            source.value = text;
            bubble.appendChild(source);

            const actions = document.createElement("div");
            actions.className = "tutor-message-actions";
            const copy = document.createElement("button");
            copy.type = "button";
            copy.className = "copy-response-button";
            copy.dataset.copyResponse = "true";
            copy.textContent = "Copy response";
            actions.appendChild(copy);
            bubble.appendChild(actions);

            const cta = quizCallToAction();
            if (cta) {
                bubble.appendChild(cta);
            }
        }

        row.appendChild(bubble);
        messages.appendChild(row);
        scrollToLatest();
        return row;
    }

    function addTyping() {
        const row = document.createElement("article");
        row.className = "tutor-message-row assistant typing-row";
        row.innerHTML = [
            '<div class="tutor-avatar" aria-hidden="true">&#127979;</div>',
            '<div class="tutor-message">',
            '<div class="tutor-message-meta">AI Tutor</div>',
            '<div class="typing-indicator" aria-label="AI Tutor is typing">',
            "<span></span><span></span><span></span>",
            "</div>",
            "</div>"
        ].join("");
        messages.appendChild(row);
        scrollToLatest();
        return row;
    }

    async function copyText(text, button) {
        try {
            if (navigator.clipboard && window.isSecureContext) {
                await navigator.clipboard.writeText(text);
            } else {
                const temp = document.createElement("textarea");
                temp.value = text;
                document.body.appendChild(temp);
                temp.select();
                document.execCommand("copy");
                temp.remove();
            }
            button.textContent = "Copied";
            setTimeout(function () {
                button.textContent = "Copy response";
            }, 1400);
        } catch (error) {
            button.textContent = "Copy failed";
            setTimeout(function () {
                button.textContent = "Copy response";
            }, 1400);
        }
    }

    messages.addEventListener("click", function (event) {
        const button = event.target.closest("[data-copy-response]");
        if (!button) {
            return;
        }
        const bubble = button.closest(".tutor-message");
        const source = bubble ? bubble.querySelector(".tutor-message-source") : null;
        if (source) {
            copyText(source.value, button);
        }
    });

    input.addEventListener("input", resizeInput);
    input.addEventListener("keydown", function (event) {
        if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            form.requestSubmit();
        }
    });

    form.addEventListener("submit", async function (event) {
        event.preventDefault();
        const text = input.value.trim();
        if (!text) {
            return;
        }

        addMessage("student", text);
        input.value = "";
        resizeInput();
        input.disabled = true;
        sendButton.disabled = true;

        const typing = addTyping();
        try {
            const response = await fetch(form.dataset.endpoint, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "Accept": "application/json"
                },
                body: JSON.stringify({ message: text })
            });
            const data = await response.json();
            typing.remove();
            if (!response.ok) {
                addMessage("assistant", data.error || "I could not answer that yet. Please try again.");
                return;
            }
            addMessage("assistant", data.reply, data.reply_html);
        } catch (error) {
            typing.remove();
            addMessage("assistant", "The tutor could not connect right now. Please try again.");
        } finally {
            input.disabled = false;
            sendButton.disabled = false;
            input.focus();
        }
    });

    resizeInput();
    scrollToLatest();
})();
