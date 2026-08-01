(function () {
    "use strict";

    const STORAGE_KEY = "aiStudyBuddy.listenNotes.speed";
    const BASE_WORDS_PER_MINUTE = 165;
    const MAX_CHUNK_LENGTH = 4200;
    const ALLOWED_RATES = [0.75, 1, 1.25, 1.5];
    const STATUS = {
        preparing: { text: "\u231B Preparing...", className: "is-preparing" },
        speaking: { text: "\u{1F50A} Speaking...", className: "is-speaking" },
        paused: { text: "\u23F8 Paused", className: "is-paused" },
        finished: { text: "\u2705 Finished", className: "is-finished" },
        stopped: { text: "\u23F9 Stopped", className: "is-stopped" },
    };

    const synth = window.speechSynthesis;
    const supportsSpeech = Boolean("SpeechSynthesisUtterance" in window && synth);
    const player = document.querySelector("[data-listen-notes-player]");
    const notesSection = document.querySelector("[data-listen-notes-section]");
    const notesContent = document.querySelector("[data-listen-notes-content]");

    if (!player || !notesContent) {
        return;
    }

    const statusText = player.querySelector("[data-listen-notes-status]");
    const statusBadge = player.querySelector("[data-listen-notes-badge]");
    const estimateOutput = player.querySelector("[data-listen-notes-estimate]");
    const progressBar = player.querySelector("[data-listen-notes-progress]");
    const elapsedOutput = player.querySelector("[data-listen-notes-elapsed]");
    const remainingOutput = player.querySelector("[data-listen-notes-remaining]");
    const buttons = {
        play: player.querySelector("[data-listen-action='play']"),
        pause: player.querySelector("[data-listen-action='pause']"),
        resume: player.querySelector("[data-listen-action='resume']"),
        stop: player.querySelector("[data-listen-action='stop']"),
        restart: player.querySelector("[data-listen-action='restart']"),
    };
    const speedInputs = Array.from(player.querySelectorAll("input[name='listen-notes-speed']"));
    const controls = Object.values(buttons).filter(Boolean);

    let selectedRate = restoreSavedRate();
    let selectedVoice = null;
    let readerState = "preparing";
    let hasText = false;
    let hasPlaybackStarted = false;
    let stopRequested = false;
    let chunks = [];
    let activeChunkIndex = 0;
    let activeUtterance = null;
    let activeHighlight = null;
    let textModel = { text: "", map: [] };
    let estimatedSeconds = 0;
    let elapsedSeconds = 0;
    let speakingStartedAt = 0;
    let currentProgressRatio = 0;
    let currentGlobalCharIndex = 0;
    let pausedResumeOffset = null;
    let progressTimer = null;
    let pendingSpeechTimer = null;
    let prepareTimer = null;
    let suppressMutation = false;
    let notesObserver = null;

    function restoreSavedRate() {
        try {
            const savedRate = Number(window.localStorage.getItem(STORAGE_KEY));
            return ALLOWED_RATES.includes(savedRate) ? savedRate : 1;
        } catch (error) {
            return 1;
        }
    }

    function saveRate(rate) {
        try {
            window.localStorage.setItem(STORAGE_KEY, String(rate));
        } catch (error) {
            // localStorage can be unavailable in private or restricted contexts.
        }
    }

    function setSpeedInputs() {
        speedInputs.forEach(function (input) {
            input.checked = Number(input.value) === selectedRate;
        });
    }

    function setStatus(state, message) {
        readerState = state;
        const status = STATUS[state] || STATUS.stopped;
        if (statusBadge) {
            statusBadge.textContent = status.text;
            statusBadge.className = `listen-notes-status-badge ${status.className}`;
        }
        if (statusText) {
            statusText.textContent = message || defaultMessageForState(state);
        }
        updateControls();
    }

    function defaultMessageForState(state) {
        if (!supportsSpeech) {
            return "Speech playback is not available in this browser.";
        }
        if (!hasText) {
            return "There are no lesson notes to read.";
        }
        if (state === "speaking") {
            return `Reading lesson notes at ${selectedRate}x speed.`;
        }
        if (state === "paused") {
            return "Narration is paused.";
        }
        if (state === "finished") {
            return "Finished reading the lesson notes.";
        }
        if (state === "preparing") {
            return "Preparing the lesson notes reader.";
        }
        return "Ready to read the lesson notes.";
    }

    function updateControls() {
        if (!supportsSpeech) {
            controls.forEach(function (button) {
                button.disabled = true;
            });
            speedInputs.forEach(function (input) {
                input.disabled = true;
            });
            return;
        }

        const isPreparing = readerState === "preparing";
        const isSpeaking = readerState === "speaking";
        const isPaused = readerState === "paused";
        const isFinished = readerState === "finished";
        const isStopped = readerState === "stopped";
        const canStart = hasText && !isPreparing && (isStopped || isFinished);
        const canRestart = hasText && !isPreparing && (hasPlaybackStarted || isFinished || isSpeaking || isPaused);

        if (buttons.play) {
            buttons.play.disabled = !canStart;
        }
        if (buttons.pause) {
            buttons.pause.disabled = !isSpeaking;
        }
        if (buttons.resume) {
            buttons.resume.disabled = !isPaused;
        }
        if (buttons.stop) {
            buttons.stop.disabled = !(isSpeaking || isPaused || isPreparing);
        }
        if (buttons.restart) {
            buttons.restart.disabled = !canRestart;
        }
    }

    function formatDuration(totalSeconds) {
        const seconds = Math.max(0, Math.round(totalSeconds || 0));
        const minutes = Math.floor(seconds / 60);
        const remainingSeconds = seconds % 60;
        if (minutes > 0) {
            return `${minutes} min ${remainingSeconds} sec`;
        }
        return `${remainingSeconds} sec`;
    }

    function buildTextModel() {
        const walker = document.createTreeWalker(
            notesContent,
            NodeFilter.SHOW_TEXT,
            {
                acceptNode: function (node) {
                    if (!node.nodeValue || !node.nodeValue.trim()) {
                        return NodeFilter.FILTER_REJECT;
                    }
                    return NodeFilter.FILTER_ACCEPT;
                },
            }
        );
        const pieces = [];
        const map = [];
        let pendingSpace = false;
        let node = walker.nextNode();

        while (node) {
            const value = node.nodeValue || "";
            for (let index = 0; index < value.length; index += 1) {
                const character = value[index];
                if (/\s/.test(character)) {
                    pendingSpace = pieces.length > 0;
                    continue;
                }
                if (pendingSpace) {
                    pieces.push(" ");
                    map.push({ node: node, offset: index });
                    pendingSpace = false;
                }
                pieces.push(character);
                map.push({ node: node, offset: index });
            }
            node = walker.nextNode();
        }

        textModel = {
            text: pieces.join("").trim(),
            map: map,
        };
        hasText = textModel.text.length > 0;
    }

    function calculateEstimate() {
        const words = textModel.text.match(/\S+/g) || [];
        estimatedSeconds = words.length ? Math.max(1, Math.ceil((words.length / (BASE_WORDS_PER_MINUTE * selectedRate)) * 60)) : 0;
        if (estimateOutput) {
            estimateOutput.textContent = estimatedSeconds ? formatDuration(estimatedSeconds) : "0 sec";
        }
    }

    function buildChunksFromOffset(startOffset) {
        const start = Math.max(0, Math.min(startOffset || 0, textModel.text.length));
        const sourceText = textModel.text.slice(start);
        const sentenceMatches = sourceText.match(/[^.!?]+[.!?]+|[^.!?]+$/g) || [];
        const nextChunks = [];
        let buffer = "";
        let bufferStart = start;
        let cursor = start;

        sentenceMatches.forEach(function (sentence) {
            const cleanSentence = sentence.trim();
            if (!cleanSentence) {
                cursor += sentence.length;
                return;
            }

            const sentenceOffsetInSource = sentence.indexOf(cleanSentence);
            const sentenceStart = cursor + Math.max(0, sentenceOffsetInSource);

            if (cleanSentence.length > MAX_CHUNK_LENGTH) {
                if (buffer) {
                    nextChunks.push({ text: buffer.trim(), start: bufferStart });
                    buffer = "";
                }
                splitLongText(cleanSentence, sentenceStart).forEach(function (chunk) {
                    nextChunks.push(chunk);
                });
                cursor += sentence.length;
                return;
            }

            const candidate = buffer ? `${buffer} ${cleanSentence}` : cleanSentence;
            if (candidate.length > MAX_CHUNK_LENGTH) {
                nextChunks.push({ text: buffer.trim(), start: bufferStart });
                buffer = cleanSentence;
                bufferStart = sentenceStart;
            } else {
                if (!buffer) {
                    bufferStart = sentenceStart;
                }
                buffer = candidate;
            }
            cursor += sentence.length;
        });

        if (buffer) {
            nextChunks.push({ text: buffer.trim(), start: bufferStart });
        }

        chunks = nextChunks;
        activeChunkIndex = 0;
    }

    function splitLongText(text, startOffset) {
        const nextChunks = [];
        let chunkStart = 0;
        while (chunkStart < text.length) {
            let chunkEnd = Math.min(chunkStart + MAX_CHUNK_LENGTH, text.length);
            if (chunkEnd < text.length) {
                const lastSpace = text.lastIndexOf(" ", chunkEnd);
                if (lastSpace > chunkStart + 600) {
                    chunkEnd = lastSpace;
                }
            }
            const chunkText = text.slice(chunkStart, chunkEnd).trim();
            if (chunkText) {
                nextChunks.push({ text: chunkText, start: startOffset + chunkStart });
            }
            chunkStart = chunkEnd + 1;
        }
        return nextChunks;
    }

    function updateEstimateAndProgress(resetProgress) {
        calculateEstimate();
        if (resetProgress) {
            elapsedSeconds = 0;
            speakingStartedAt = 0;
            currentProgressRatio = 0;
            currentGlobalCharIndex = 0;
        }
        updateProgressDisplay();
    }

    function updateProgressDisplay() {
        const liveElapsed = elapsedSeconds + (readerState === "speaking" && speakingStartedAt ? (Date.now() - speakingStartedAt) / 1000 : 0);
        const timeRatio = estimatedSeconds ? Math.min(liveElapsed / estimatedSeconds, 1) : 0;
        const progressRatio = readerState === "finished" ? 1 : Math.max(currentProgressRatio, timeRatio);
        const clampedRatio = Math.max(0, Math.min(progressRatio, readerState === "speaking" ? 0.995 : 1));

        if (progressBar) {
            progressBar.style.width = `${clampedRatio * 100}%`;
        }
        if (elapsedOutput) {
            elapsedOutput.textContent = `Elapsed ${formatDuration(liveElapsed)}`;
        }
        if (remainingOutput) {
            remainingOutput.textContent = `Remaining ${formatDuration(Math.max(estimatedSeconds - liveElapsed, 0))}`;
        }
    }

    function startProgressTimer() {
        clearProgressTimer();
        updateProgressDisplay();
        progressTimer = window.setInterval(updateProgressDisplay, 1000);
    }

    function clearProgressTimer() {
        if (progressTimer) {
            window.clearInterval(progressTimer);
            progressTimer = null;
        }
    }

    function clearPendingSpeechTimer() {
        if (pendingSpeechTimer) {
            window.clearTimeout(pendingSpeechTimer);
            pendingSpeechTimer = null;
        }
    }

    function clearPrepareTimer() {
        if (prepareTimer) {
            window.clearTimeout(prepareTimer);
            prepareTimer = null;
        }
    }

    function chooseVoice(voices) {
        const availableVoices = voices || [];
        return (
            availableVoices.find(function (voice) {
                return /^en-IN$/i.test(voice.lang || "") || /english.*india|india.*english/i.test(voice.name || "");
            }) ||
            availableVoices.find(function (voice) {
                return /^en-US$/i.test(voice.lang || "") || /english.*united states|united states.*english/i.test(voice.name || "");
            }) ||
            availableVoices.find(function (voice) {
                return /^en[-_]/i.test(voice.lang || "") || /\benglish\b/i.test(voice.name || "");
            }) ||
            null
        );
    }

    function refreshVoices() {
        if (!supportsSpeech) {
            return;
        }
        selectedVoice = chooseVoice(synth.getVoices());
    }

    function createUtterance(chunk) {
        const utterance = new SpeechSynthesisUtterance(chunk.text);
        utterance.rate = selectedRate;
        utterance.lang = selectedVoice ? selectedVoice.lang : "en-IN";
        if (selectedVoice) {
            utterance.voice = selectedVoice;
        }
        utterance.onboundary = function (event) {
            handleBoundary(event, chunk);
        };
        utterance.onend = function () {
            handleChunkEnd(chunk);
        };
        utterance.onerror = function () {
            if (!stopRequested) {
                stopPlayback("Narration stopped because the browser could not continue playback.");
            }
        };
        return utterance;
    }

    function speakActiveChunk() {
        if (!chunks.length || activeChunkIndex >= chunks.length) {
            finishPlayback();
            return;
        }

        stopRequested = false;
        const chunk = chunks[activeChunkIndex];
        activeUtterance = createUtterance(chunk);
        currentGlobalCharIndex = chunk.start;
        setStatus("speaking");
        if (!speakingStartedAt) {
            speakingStartedAt = Date.now();
        }
        startProgressTimer();
        synth.speak(activeUtterance);
    }

    function startPlaybackFromOffset(startOffset) {
        if (!supportsSpeech) {
            setStatus("stopped", "Speech playback is not available in this browser.");
            return;
        }
        prepareTextModel();
        if (!hasText) {
            setStatus("stopped", "There are no lesson notes to read.");
            return;
        }

        clearPendingSpeechTimer();
        stopRequested = true;
        synth.cancel();
        removeHighlight();
        buildChunksFromOffset(startOffset || 0);
        if (!chunks.length) {
            finishPlayback();
            return;
        }

        hasPlaybackStarted = true;
        stopRequested = false;
        setStatus("preparing");
        pendingSpeechTimer = window.setTimeout(function () {
            pendingSpeechTimer = null;
            speakActiveChunk();
        }, 90);
    }

    function startPlayback() {
        elapsedSeconds = 0;
        speakingStartedAt = 0;
        currentProgressRatio = 0;
        currentGlobalCharIndex = 0;
        pausedResumeOffset = null;
        updateProgressDisplay();
        startPlaybackFromOffset(0);
    }

    function pausePlayback() {
        if (!supportsSpeech || readerState !== "speaking") {
            return;
        }
        synth.pause();
        pausedResumeOffset = null;
        if (speakingStartedAt) {
            elapsedSeconds += (Date.now() - speakingStartedAt) / 1000;
            speakingStartedAt = 0;
        }
        clearProgressTimer();
        setStatus("paused");
        updateProgressDisplay();
    }

    function resumePlayback() {
        if (!supportsSpeech || readerState !== "paused") {
            return;
        }
        if (pausedResumeOffset !== null) {
            const resumeAt = pausedResumeOffset;
            pausedResumeOffset = null;
            speakingStartedAt = Date.now();
            startPlaybackFromOffset(resumeAt);
            return;
        }
        synth.resume();
        speakingStartedAt = Date.now();
        setStatus("speaking");
        startProgressTimer();
    }

    function restartPlayback() {
        stopPlayback("Restarting lesson notes.", { keepStarted: true, nextState: "preparing" });
        startPlayback();
    }

    function stopPlayback(message, options) {
        const settings = options || {};
        clearPendingSpeechTimer();
        clearProgressTimer();
        stopRequested = true;
        activeUtterance = null;
        pausedResumeOffset = null;
        if (speakingStartedAt && readerState === "speaking") {
            elapsedSeconds += (Date.now() - speakingStartedAt) / 1000;
        }
        speakingStartedAt = 0;
        if (supportsSpeech) {
            synth.cancel();
        }
        removeHighlight();
        if (!settings.keepStarted && settings.resetStarted) {
            hasPlaybackStarted = false;
        }
        setStatus(settings.nextState || "stopped", message || "Stopped.");
        updateProgressDisplay();
    }

    function finishPlayback() {
        clearPendingSpeechTimer();
        clearProgressTimer();
        removeHighlight();
        activeUtterance = null;
        pausedResumeOffset = null;
        stopRequested = false;
        elapsedSeconds = Math.max(elapsedSeconds, estimatedSeconds);
        speakingStartedAt = 0;
        currentProgressRatio = 1;
        currentGlobalCharIndex = textModel.text.length;
        setStatus("finished");
        updateProgressDisplay();
    }

    function handleChunkEnd(chunk) {
        if (stopRequested) {
            return;
        }
        currentGlobalCharIndex = chunk.start + chunk.text.length;
        currentProgressRatio = textModel.text.length ? currentGlobalCharIndex / textModel.text.length : 1;
        removeHighlight();
        activeChunkIndex += 1;
        if (activeChunkIndex < chunks.length) {
            speakActiveChunk();
        } else {
            finishPlayback();
        }
    }

    function handleBoundary(event, chunk) {
        if (stopRequested || readerState !== "speaking" || typeof event.charIndex !== "number") {
            return;
        }
        const globalIndex = Math.max(0, Math.min(chunk.start + event.charIndex, textModel.text.length));
        currentGlobalCharIndex = globalIndex;
        currentProgressRatio = textModel.text.length ? globalIndex / textModel.text.length : 0;
        updateProgressDisplay();
        highlightBoundary(globalIndex, event.charLength || 0, event.name || "");
    }

    function highlightBoundary(globalIndex, charLength, boundaryName) {
        const bounds = getHighlightBounds(globalIndex, charLength, boundaryName);
        if (!bounds || bounds.end <= bounds.start) {
            return;
        }
        highlightRange(bounds.start, bounds.end);
    }

    function getHighlightBounds(index, charLength, boundaryName) {
        const text = textModel.text;
        if (!text) {
            return null;
        }
        const startIndex = Math.max(0, Math.min(index, text.length - 1));
        if (charLength > 0 && charLength < 260) {
            return {
                start: startIndex,
                end: Math.min(startIndex + charLength, text.length),
            };
        }
        if (/sentence/i.test(boundaryName)) {
            return getSentenceBounds(startIndex);
        }
        return getWordBounds(startIndex) || getSentenceBounds(startIndex);
    }

    function getWordBounds(index) {
        const text = textModel.text;
        let start = index;
        let end = index;

        while (start > 0 && isWordCharacter(text[start - 1])) {
            start -= 1;
        }
        while (start < text.length && !isWordCharacter(text[start])) {
            start += 1;
        }
        end = start;
        while (end < text.length && isWordCharacter(text[end])) {
            end += 1;
        }
        return end > start ? { start: start, end: end } : null;
    }

    function getSentenceBounds(index) {
        const text = textModel.text;
        let start = index;
        let end = index;
        while (start > 0 && !/[.!?]/.test(text[start - 1])) {
            start -= 1;
        }
        while (start < text.length && /\s/.test(text[start])) {
            start += 1;
        }
        while (end < text.length && !/[.!?]/.test(text[end])) {
            end += 1;
        }
        if (end < text.length) {
            end += 1;
        }
        return { start: start, end: Math.max(end, start + 1) };
    }

    function isWordCharacter(character) {
        return Boolean(character && /[^\s.,;:!?()[\]{}"'<>/\\|]+/.test(character));
    }

    function highlightRange(start, end) {
        removeHighlight();
        buildTextModel();
        const map = textModel.map;
        if (!map.length || start >= map.length) {
            return;
        }
        const safeStart = Math.max(0, Math.min(start, map.length - 1));
        const safeEnd = Math.max(safeStart + 1, Math.min(end, map.length));
        const startRef = map[safeStart];
        const endRef = map[safeEnd - 1];
        if (!startRef || !endRef) {
            return;
        }

        const range = document.createRange();
        try {
            range.setStart(startRef.node, startRef.offset);
            range.setEnd(endRef.node, endRef.offset + 1);
            if (range.collapsed) {
                return;
            }
            const mark = document.createElement("mark");
            mark.className = "listen-notes-highlight";
            withSuppressedMutations(function () {
                mark.appendChild(range.extractContents());
                range.insertNode(mark);
            });
            activeHighlight = mark;
            scrollHighlightIntoView(mark);
        } catch (error) {
            removeHighlight();
        } finally {
            range.detach();
        }
    }

    function removeHighlight() {
        if (!activeHighlight || !activeHighlight.parentNode) {
            activeHighlight = null;
            return;
        }
        const parent = activeHighlight.parentNode;
        withSuppressedMutations(function () {
            while (activeHighlight.firstChild) {
                parent.insertBefore(activeHighlight.firstChild, activeHighlight);
            }
            parent.removeChild(activeHighlight);
            parent.normalize();
        });
        activeHighlight = null;
    }

    function withSuppressedMutations(callback) {
        suppressMutation = true;
        try {
            callback();
        } finally {
            window.setTimeout(function () {
                suppressMutation = false;
            }, 0);
        }
    }

    function scrollHighlightIntoView(mark) {
        const rect = mark.getBoundingClientRect();
        const topLimit = 96;
        const bottomLimit = window.innerHeight - 80;
        if (rect.top < topLimit || rect.bottom > bottomLimit) {
            mark.scrollIntoView({ behavior: "smooth", block: "center", inline: "nearest" });
        }
    }

    function prepareTextModel() {
        removeHighlight();
        buildTextModel();
        calculateEstimate();
    }

    function prepareReader() {
        clearPrepareTimer();
        setStatus("preparing");
        prepareTextModel();
        updateEstimateAndProgress(true);
        setStatus("stopped");
    }

    function schedulePrepareForNewNotes() {
        if (suppressMutation) {
            return;
        }
        clearPrepareTimer();
        if (readerState === "speaking" || readerState === "paused" || readerState === "preparing") {
            stopPlayback("Stopped because new lesson notes loaded.", { resetStarted: true });
        }
        prepareTimer = window.setTimeout(function () {
            prepareTimer = null;
            prepareReader();
        }, 180);
    }

    function handleSpeedChange(input) {
        selectedRate = Number(input.value) || 1;
        if (!ALLOWED_RATES.includes(selectedRate)) {
            selectedRate = 1;
        }
        setSpeedInputs();
        saveRate(selectedRate);
        calculateEstimate();

        if (readerState === "speaking") {
            const resumeAt = getResumeOffset();
            stopPlayback("Applying new speed.", { keepStarted: true, nextState: "preparing" });
            startPlaybackFromOffset(resumeAt);
        } else if (readerState === "paused") {
            pausedResumeOffset = getResumeOffset();
            clearPendingSpeechTimer();
            stopRequested = true;
            if (supportsSpeech) {
                synth.cancel();
            }
            removeHighlight();
            setStatus("paused", `Paused. New speed ${selectedRate}x will be used when you resume.`);
            updateProgressDisplay();
        } else {
            updateProgressDisplay();
            setStatus(readerState === "paused" ? "paused" : readerState, `Ready to read at ${selectedRate}x speed.`);
        }
    }

    function getResumeOffset() {
        const sentenceBounds = getSentenceBounds(currentGlobalCharIndex || 0);
        return Math.max(0, sentenceBounds ? sentenceBounds.start : currentGlobalCharIndex || 0);
    }

    function isEditableTarget(target) {
        if (!(target instanceof Element)) {
            return false;
        }
        return Boolean(target.closest("input, textarea, select, button, a, [contenteditable='true']"));
    }

    function bindEvents() {
        if (buttons.play) {
            buttons.play.addEventListener("click", startPlayback);
        }
        if (buttons.pause) {
            buttons.pause.addEventListener("click", pausePlayback);
        }
        if (buttons.resume) {
            buttons.resume.addEventListener("click", resumePlayback);
        }
        if (buttons.stop) {
            buttons.stop.addEventListener("click", function () {
                stopPlayback("Stopped.");
            });
        }
        if (buttons.restart) {
            buttons.restart.addEventListener("click", restartPlayback);
        }

        speedInputs.forEach(function (input) {
            input.addEventListener("change", function () {
                handleSpeedChange(input);
            });
        });

        document.addEventListener("keydown", function (event) {
            if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey || isEditableTarget(event.target)) {
                return;
            }
            if (event.code === "Space" || event.key === " ") {
                event.preventDefault();
                if (readerState === "speaking") {
                    pausePlayback();
                } else if (readerState === "paused") {
                    resumePlayback();
                } else if (readerState === "stopped" || readerState === "finished") {
                    startPlayback();
                }
            }
            if (event.key === "Escape" && (readerState === "speaking" || readerState === "paused" || readerState === "preparing")) {
                event.preventDefault();
                stopPlayback("Stopped.");
            }
        });

        document.addEventListener("click", function (event) {
            const target = event.target;
            if (!(target instanceof Element)) {
                return;
            }
            if (target.closest("[data-listen-notes-player]") || target.closest("[data-listen-notes-content]")) {
                return;
            }
            if (target.closest("#revision-tools, #diagram-section, #ai-tutor-step, #quiz-step, #flashcards-step, #memory-step, .continue-learning-section, .revision-tools-section, .result-actions")) {
                stopPlayback("Stopped as you moved to another learning tool.");
            }
        });

        document.addEventListener("submit", function (event) {
            const form = event.target;
            if (form instanceof Element && !form.closest("[data-listen-notes-player]")) {
                stopPlayback("Stopped as you moved to another learning tool.");
            }
        });

        if ("IntersectionObserver" in window && notesSection) {
            const observer = new IntersectionObserver(function (entries) {
                entries.forEach(function (entry) {
                    if (!entry.isIntersecting && (readerState === "speaking" || readerState === "paused")) {
                        stopPlayback("Stopped because you left the Notes section.");
                    }
                });
            }, { threshold: 0.01 });
            observer.observe(notesSection);
        }

        if ("MutationObserver" in window) {
            notesObserver = new MutationObserver(schedulePrepareForNewNotes);
            notesObserver.observe(notesContent, { childList: true, subtree: true, characterData: true });
        }

        document.addEventListener("visibilitychange", function () {
            if (document.hidden) {
                stopPlayback("Stopped.");
            }
        });
        window.addEventListener("pagehide", cleanup);
        window.addEventListener("beforeunload", cleanup);
    }

    function cleanup() {
        clearPrepareTimer();
        clearPendingSpeechTimer();
        clearProgressTimer();
        stopRequested = true;
        if (supportsSpeech) {
            synth.cancel();
        }
        removeHighlight();
        if (notesObserver) {
            notesObserver.disconnect();
            notesObserver = null;
        }
    }

    function initialize() {
        setSpeedInputs();
        refreshVoices();
        if (supportsSpeech) {
            if (typeof synth.addEventListener === "function") {
                synth.addEventListener("voiceschanged", refreshVoices);
            } else {
                synth.onvoiceschanged = refreshVoices;
            }
        }
        bindEvents();
        if (!supportsSpeech) {
            buildTextModel();
            updateEstimateAndProgress(true);
            setStatus("stopped", "Speech playback is not available in this browser.");
            updateControls();
            return;
        }
        prepareReader();
    }

    initialize();
}());
