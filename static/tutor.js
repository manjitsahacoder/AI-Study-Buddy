(function () {
    const form = document.getElementById("tutor-form");
    const input = document.getElementById("tutor-input");
    const sendButton = document.getElementById("tutor-send");
    const messages = document.getElementById("tutor-messages");
    const quizTemplate = document.getElementById("tutor-quiz-cta-template");
    const voiceStartButton = document.getElementById("voice-start");
    const voiceStopButton = document.getElementById("voice-stop");
    const voiceReadButton = document.getElementById("voice-read");
    const voiceMuteButton = document.getElementById("voice-mute");
    const voiceStatus = document.getElementById("voice-status");

    if (!form || !input || !messages) {
        return;
    }

    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    const canRecognizeSpeech = Boolean(SpeechRecognition);
    const canSpeakResponse = Boolean(window.speechSynthesis && window.SpeechSynthesisUtterance);
    let recognition = null;
    let isListening = false;
    let speechMuted = false;
    let transcriptBase = "";
    let finalTranscript = "";
    let hasVoiceTranscript = false;

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

    function setVoiceStatus(text) {
        if (voiceStatus) {
            voiceStatus.textContent = text;
        }
    }

    function latestAssistantResponse() {
        const assistantRows = messages.querySelectorAll(".tutor-message-row.assistant");
        for (let index = assistantRows.length - 1; index >= 0; index -= 1) {
            const source = assistantRows[index].querySelector(".tutor-message-source");
            if (source && source.value.trim()) {
                return source.value.trim();
            }

            const content = assistantRows[index].querySelector(".tutor-message-content");
            if (content && content.textContent.trim()) {
                return content.textContent.trim();
            }
        }
        return "";
    }

    function updateVoiceControls() {
        const isSending = form.classList.contains("is-sending");

        if (voiceStartButton) {
            voiceStartButton.disabled = !canRecognizeSpeech || isListening || isSending;
        }
        if (voiceStopButton) {
            voiceStopButton.disabled = !canRecognizeSpeech || !isListening;
        }
        if (voiceReadButton) {
            voiceReadButton.disabled = !canSpeakResponse || speechMuted;
        }
        if (voiceMuteButton) {
            voiceMuteButton.disabled = !canSpeakResponse;
            voiceMuteButton.textContent = speechMuted ? "\uD83D\uDD08 Unmute" : "\uD83D\uDD07 Mute";
            voiceMuteButton.setAttribute("aria-pressed", speechMuted ? "true" : "false");
        }
    }

    function stopSpeech() {
        if (canSpeakResponse) {
            window.speechSynthesis.cancel();
        }
    }

    function readLatestResponse() {
        if (!canSpeakResponse) {
            setVoiceStatus("Text-to-speech is unavailable. You can read the response on screen.");
            return;
        }
        if (speechMuted) {
            setVoiceStatus("Speech is muted.");
            return;
        }

        const responseText = latestAssistantResponse();
        if (!responseText) {
            setVoiceStatus("No tutor response is ready to read yet.");
            return;
        }

        stopSpeech();
        const utterance = new SpeechSynthesisUtterance(responseText);
        utterance.lang = document.documentElement.lang || navigator.language || "en-US";
        utterance.onstart = function () {
            setVoiceStatus("Reading response...");
        };
        utterance.onend = function () {
            setVoiceStatus("Finished reading.");
        };
        utterance.onerror = function () {
            setVoiceStatus("Could not read the response aloud.");
        };
        window.speechSynthesis.speak(utterance);
    }

    function ensureRecognition() {
        if (!canRecognizeSpeech) {
            setVoiceStatus("Speech-to-text is unavailable. Typing still works.");
            return null;
        }
        if (recognition) {
            return recognition;
        }

        recognition = new SpeechRecognition();
        recognition.continuous = false;
        recognition.interimResults = true;
        recognition.lang = document.documentElement.lang || navigator.language || "en-US";

        recognition.onstart = function () {
            isListening = true;
            finalTranscript = "";
            hasVoiceTranscript = false;
            transcriptBase = input.value.trim();
            setVoiceStatus("Listening...");
            updateVoiceControls();
        };

        recognition.onresult = function (event) {
            let interimTranscript = "";
            for (let index = event.resultIndex; index < event.results.length; index += 1) {
                const transcript = event.results[index][0].transcript;
                if (event.results[index].isFinal) {
                    finalTranscript += transcript;
                } else {
                    interimTranscript += transcript;
                }
            }

            const combinedTranscript = [transcriptBase, finalTranscript, interimTranscript]
                .map(function (part) {
                    return (part || "").trim();
                })
                .filter(Boolean)
                .join(" ");
            hasVoiceTranscript = combinedTranscript.trim() !== transcriptBase;
            input.value = combinedTranscript;
            resizeInput();
        };

        recognition.onerror = function (event) {
            const messagesByError = {
                "not-allowed": "Microphone permission was blocked. Typing still works.",
                "no-speech": "No speech was heard. Try again or type your question.",
                "audio-capture": "No microphone was found. Typing still works."
            };
            setVoiceStatus(messagesByError[event.error] || "Speech recognition stopped. Typing still works.");
        };

        recognition.onend = function () {
            const finalPrompt = input.value.trim();
            isListening = false;
            updateVoiceControls();

            if (hasVoiceTranscript && finalPrompt && !form.classList.contains("is-sending")) {
                setVoiceStatus("Sending voice question...");
                submitPrompt(finalPrompt);
            } else if (finalPrompt) {
                setVoiceStatus("Voice captured.");
            } else if (canRecognizeSpeech) {
                setVoiceStatus("Voice ready.");
            }
        };

        return recognition;
    }

    function startListening() {
        const recognizer = ensureRecognition();
        if (!recognizer || isListening || form.classList.contains("is-sending")) {
            return;
        }

        stopSpeech();
        try {
            recognizer.start();
        } catch (error) {
            setVoiceStatus("Speech recognition is already starting.");
        }
    }

    function stopListening() {
        if (recognition && isListening) {
            recognition.stop();
            setVoiceStatus("Stopping...");
        }
    }

    function messageTime(date) {
        return new Intl.DateTimeFormat(undefined, {
            day: "2-digit",
            month: "short",
            year: "numeric",
            hour: "numeric",
            minute: "2-digit"
        }).format(date || new Date());
    }

    function quizCallToAction() {
        if (!quizTemplate) {
            return null;
        }
        return quizTemplate.content.firstElementChild.cloneNode(true);
    }

    function quickSuggestionChips() {
        const chips = document.createElement("div");
        chips.className = "tutor-suggestion-chips";
        chips.setAttribute("aria-label", "Quick follow-up suggestions");

        [
            ["Explain more simply", "Explain your last answer more simply for this lesson."],
            ["Give an example", "Give an example based on this lesson."],
            ["Explain with analogy", "Explain this with an analogy."],
            ["Ask me a question", "Ask me one question to check my understanding."],
            ["Summarize", "Summarize your last answer in a few bullet points."],
            ["Generate practice questions", "Generate practice questions from this lesson."]
        ].forEach(function (item) {
            const chip = document.createElement("button");
            chip.type = "button";
            chip.dataset.prompt = item[1];
            chip.textContent = item[0];
            chips.appendChild(chip);
        });

        return chips;
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
        const speaker = document.createElement("span");
        speaker.textContent = sender === "student" ? "You" : "AI Tutor";
        const time = document.createElement("time");
        const now = new Date();
        time.dateTime = now.toISOString();
        time.textContent = messageTime(now);
        meta.appendChild(speaker);
        meta.appendChild(time);
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

            const regenerate = document.createElement("button");
            regenerate.type = "button";
            regenerate.className = "regenerate-response-button";
            regenerate.dataset.regenerateResponse = "true";
            regenerate.textContent = "Regenerate";
            actions.appendChild(regenerate);
            bubble.appendChild(actions);
            bubble.appendChild(quickSuggestionChips());

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
            '<div class="tutor-message-meta"><span>AI Tutor</span><time>AI is thinking...</time></div>',
            '<div class="thinking-label" role="status">AI is thinking...</div>',
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

    function previousStudentMessage(fromRow) {
        let row = fromRow ? fromRow.previousElementSibling : null;
        while (row) {
            if (row.classList.contains("student")) {
                const content = row.querySelector(".tutor-message-content");
                return content ? content.textContent.trim() : "";
            }
            row = row.previousElementSibling;
        }
        return "";
    }

    function setComposerState(isSending) {
        input.disabled = isSending;
        sendButton.disabled = isSending;
        form.classList.toggle("is-sending", isSending);
        form.setAttribute("aria-busy", isSending ? "true" : "false");
        updateVoiceControls();
    }

    async function submitPrompt(text) {
        const prompt = (text || "").trim();
        if (!prompt || form.classList.contains("is-sending")) {
            return;
        }

        addMessage("student", prompt);
        input.value = "";
        resizeInput();
        setComposerState(true);

        const typing = addTyping();
        try {
            const response = await fetch(form.dataset.endpoint, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "Accept": "application/json"
                },
                body: JSON.stringify({ message: prompt })
            });
            const data = await response.json();
            typing.remove();
            if (!response.ok) {
                addMessage("assistant", data.error || "I could not answer that yet. Please try again.");
                return;
            }
            addMessage("assistant", data.reply, data.reply_html);
            setVoiceStatus("Response ready.");
        } catch (error) {
            typing.remove();
            addMessage("assistant", "The tutor could not connect right now. Please try again.");
        } finally {
            setComposerState(false);
            input.focus();
        }
    }

    messages.addEventListener("click", function (event) {
        const copyButton = event.target.closest("[data-copy-response]");
        if (copyButton) {
            const bubble = copyButton.closest(".tutor-message");
            const source = bubble ? bubble.querySelector(".tutor-message-source") : null;
            if (source) {
                copyText(source.value, copyButton);
            }
            return;
        }

        const regenerateButton = event.target.closest("[data-regenerate-response]");
        if (regenerateButton) {
            const question = previousStudentMessage(regenerateButton.closest(".tutor-message-row"));
            submitPrompt(
                question
                    ? 'Please regenerate your answer to my question: "' + question + '"'
                    : "Please regenerate your previous response for this lesson."
            );
            return;
        }

        const promptButton = event.target.closest("[data-prompt]");
        if (promptButton) {
            submitPrompt(promptButton.dataset.prompt);
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
        submitPrompt(text);
    });

    if (voiceStartButton) {
        voiceStartButton.addEventListener("click", startListening);
    }
    if (voiceStopButton) {
        voiceStopButton.addEventListener("click", stopListening);
    }
    if (voiceReadButton) {
        voiceReadButton.addEventListener("click", readLatestResponse);
    }
    if (voiceMuteButton) {
        voiceMuteButton.addEventListener("click", function () {
            speechMuted = !speechMuted;
            if (speechMuted) {
                stopSpeech();
                setVoiceStatus("Speech muted.");
            } else {
                setVoiceStatus("Speech ready.");
            }
            updateVoiceControls();
        });
    }

    resizeInput();
    scrollToLatest();
    if (!canRecognizeSpeech && !canSpeakResponse) {
        setVoiceStatus("Voice tools are unavailable. Typing still works.");
    } else if (!canRecognizeSpeech) {
        setVoiceStatus("Speech-to-text is unavailable. Typing still works.");
    } else if (!canSpeakResponse) {
        setVoiceStatus("Text-to-speech is unavailable.");
    }
    updateVoiceControls();
})();
