(function () {
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    function parseNumberText(text) {
        const match = String(text || "").trim().replace(/,/g, "").match(/^(\d+(?:\.\d+)?)(.*)$/);
        if (!match) {
            return null;
        }
        return {
            value: Number(match[1]),
            suffix: match[2] || "",
            decimals: match[1].includes(".") ? match[1].split(".")[1].length : 0,
        };
    }

    function animateNumber(element) {
        if (reduceMotion || element.dataset.motionCounted === "true") {
            return;
        }

        const parsed = parseNumberText(element.textContent);
        if (!parsed || !Number.isFinite(parsed.value)) {
            return;
        }

        const target = parsed.value;
        const start = performance.now();
        const duration = Math.min(1100, Math.max(520, 620 + target * 10));
        element.dataset.motionCounted = "true";
        element.classList.add("is-counting");

        function frame(now) {
            const progress = Math.min((now - start) / duration, 1);
            const eased = 1 - Math.pow(1 - progress, 3);
            const current = target * eased;
            element.textContent = `${current.toFixed(parsed.decimals)}${parsed.suffix}`;

            if (progress < 1) {
                requestAnimationFrame(frame);
            } else {
                element.textContent = `${target.toFixed(parsed.decimals)}${parsed.suffix}`;
                element.classList.remove("is-counting");
                element.classList.add("count-complete");
            }
        }

        requestAnimationFrame(frame);
    }

    function setupCounters() {
        const counterTargets = document.querySelectorAll(
            ".dashboard-stat-card strong, .weekly-summary-grid strong, .weekly-summary-panel > .dashboard-section-heading > strong, .score-card h2, .performance-summary-grid strong, .subject-analysis-grid strong"
        );

        if (!("IntersectionObserver" in window)) {
            counterTargets.forEach(animateNumber);
            return;
        }

        const counterObserver = new IntersectionObserver(
            function (entries, observer) {
                entries.forEach(function (entry) {
                    if (!entry.isIntersecting) {
                        return;
                    }
                    animateNumber(entry.target);
                    observer.unobserve(entry.target);
                });
            },
            { threshold: 0.45 }
        );

        counterTargets.forEach(function (target) {
            counterObserver.observe(target);
        });
    }

    function setupReveal() {
        const revealTargets = document.querySelectorAll(
            [
                ".feature-card",
                ".dashboard-main > *",
                ".learn-container > *",
                ".container > section",
                ".container > article",
                ".tutor-shell > *",
                ".learning-history-card",
                ".learning-action-card",
                ".performance-chart-card",
                ".performance-summary-grid div",
                ".subject-analysis-grid article",
                ".insight-card",
                ".evaluation-card",
                ".teacher-report-card",
                ".flashcard-study-panel",
                ".quiz-question",
                ".score-card",
                ".card",
                ".recommendation-card",
                ".achievement-card",
                ".achievement-badge",
                ".recommended-topic-card",
                ".quick-actions-grid a",
            ].join(", ")
        );

        if (reduceMotion) {
            revealTargets.forEach(function (target) {
                target.classList.add("is-visible", "motion-ready");
            });
            return;
        }

        document.body.classList.add("motion-enabled");

        function markVisible(target) {
            target.classList.add("is-visible");
            window.setTimeout(function () {
                target.classList.add("motion-ready");
            }, 560);
        }

        if (!("IntersectionObserver" in window)) {
            revealTargets.forEach(function (target) {
                target.classList.add("is-visible", "motion-ready");
            });
            return;
        }

        const revealObserver = new IntersectionObserver(
            function (entries, observer) {
                entries.forEach(function (entry) {
                    if (!entry.isIntersecting) {
                        return;
                    }
                    markVisible(entry.target);
                    observer.unobserve(entry.target);
                });
            },
            { rootMargin: "0px 0px -8% 0px", threshold: 0.08 }
        );

        revealTargets.forEach(function (target, index) {
            if (target.matches("[data-page-transition-overlay], [data-page-transition-overlay] *")) {
                return;
            }
            target.classList.add("motion-reveal");
            target.style.setProperty("--motion-delay", `${Math.min(index % 6, 5) * 35}ms`);
            revealObserver.observe(target);
        });
    }

    function setupLoadingStates() {
        // Form loading is handled by the centralized page navigation manager.
    }

    function setupSuccessMotion() {
        document.querySelectorAll(".flash-success, .result-page .badge, .evaluation-card.correct, .status-pill.correct").forEach(function (item, index) {
            item.classList.add("success-motion");
            item.style.setProperty("--success-delay", `${Math.min(index, 6) * 45}ms`);
        });

        document.querySelectorAll(".score-dashboard").forEach(function (item) {
            item.classList.add("score-motion");
        });
    }

    function setupSidebarMotion() {
        document.querySelectorAll(".student-sidebar").forEach(function (sidebar) {
            sidebar.classList.add("is-ready");
        });
    }

    function setupDemoButtons() {
        const form = document.getElementById("lesson-form");
        if (!form) {
            return;
        }

        const fields = {
            name: form.querySelector("[name='name']"),
            studentClass: form.querySelector("[name='student_class']"),
            subject: form.querySelector("[name='subject']"),
            bookName: form.querySelector("[name='book_name']"),
            topic: form.querySelector("[name='topic']"),
        };

        document.querySelectorAll("[data-demo-topic]").forEach(function (button) {
            button.addEventListener("click", function () {
                if (fields.name) {
                    fields.name.value = button.dataset.demoName || "";
                }
                if (fields.studentClass) {
                    fields.studentClass.value = button.dataset.demoClass || "";
                }
                if (fields.subject) {
                    fields.subject.value = button.dataset.demoSubject || "";
                }
                if (fields.bookName) {
                    fields.bookName.value = button.dataset.demoBook || "";
                }
                if (fields.topic) {
                    fields.topic.value = button.dataset.demoTopic || "";
                }

                form.classList.add("demo-ready");
                form.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "center" });
                const firstEmpty = Object.values(fields).find(function (field) {
                    return field && field.required && !field.value;
                });
                (firstEmpty || fields.topic || form).focus({ preventScroll: true });
            });
        });
    }

    function setupExhibitionTour() {
        const tour = document.querySelector("[data-exhibition-tour]");
        if (!tour) {
            return;
        }

        const title = tour.querySelector("#exhibition-tour-title");
        const copy = tour.querySelector("[data-tour-copy]");
        const progress = tour.querySelector("[data-tour-progress]");
        const nextButton = tour.querySelector("[data-tour-next]");
        const skipButton = tour.querySelector("[data-tour-skip]");
        const startButtons = document.querySelectorAll("[data-start-tour]");
        const steps = Array.from(document.querySelectorAll("[data-tour-title]")).map(function (target) {
            return {
                target,
                title: target.dataset.tourTitle,
                body: target.dataset.tourBody || "",
            };
        });
        let index = 0;

        function rememberTourSeen() {
            try {
                localStorage.setItem("ai-study-buddy-exhibition-tour-seen", "1");
            } catch (error) {
                return null;
            }
            return null;
        }

        function hasSeenTour() {
            try {
                return localStorage.getItem("ai-study-buddy-exhibition-tour-seen") === "1";
            } catch (error) {
                return false;
            }
        }

        function clearHighlights() {
            document.querySelectorAll(".tour-highlight").forEach(function (item) {
                item.classList.remove("tour-highlight");
            });
        }

        function closeTour() {
            clearHighlights();
            tour.hidden = true;
            rememberTourSeen();
        }

        function showStep(nextIndex) {
            if (!steps.length) {
                return;
            }

            index = Math.min(nextIndex, steps.length - 1);
            const step = steps[index];
            clearHighlights();
            step.target.classList.add("tour-highlight");

            if (title) {
                title.textContent = step.title;
            }
            if (copy) {
                copy.textContent = step.body;
            }
            if (progress) {
                progress.style.width = `${((index + 1) / steps.length) * 100}%`;
            }
            if (nextButton) {
                nextButton.textContent = index === steps.length - 1 ? "Finish" : "Next";
            }

            step.target.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "center" });
        }

        function openTour() {
            tour.hidden = false;
            showStep(0);
        }

        startButtons.forEach(function (button) {
            button.addEventListener("click", openTour);
        });

        if (nextButton) {
            nextButton.addEventListener("click", function () {
                if (index >= steps.length - 1) {
                    closeTour();
                    return;
                }
                showStep(index + 1);
            });
        }

        if (skipButton) {
            skipButton.addEventListener("click", closeTour);
        }

        tour.addEventListener("click", function (event) {
            if (event.target === tour) {
                closeTour();
            }
        });

        document.addEventListener("keydown", function (event) {
            if (event.key === "Escape" && !tour.hidden) {
                closeTour();
            }
        });

        if (!hasSeenTour()) {
            window.setTimeout(openTour, 650);
        }
    }

    function setupPageTransitionOverlay() {
        const overlay = document.querySelector("[data-page-transition-overlay]");
        const messageTarget = document.querySelector("[data-page-transition-message]");
        const generationStepper = document.querySelector("[data-generation-stepper]");
        const generationSteps = generationStepper ? Array.from(generationStepper.querySelectorAll("[data-generation-step]")) : [];
        if (!overlay || !messageTarget) {
            return;
        }

        let pendingHideTimer = null;
        let messageTimer = null;
        let generationStepTimer = null;
        let messageIndex = 0;
        let generationStepIndex = 0;
        let navigationLocked = false;
        let suppressUnloadOverlayUntil = 0;
        const minimumOverlayPaintDelay = 180;
        const nativeLocationAssign = window.location.assign.bind(window.location);
        const nativeLocationReplace = window.location.replace.bind(window.location);
        const nativeFormSubmit = HTMLFormElement.prototype.submit;
        const attachmentRoutePatterns = [
            /^\/download_(?:pdf|notes|diagram)(?:\/)?$/,
            /\/download(?:\/)?$/,
            /\/diagram\/download(?:\/)?$/,
            /\/settings\/download-data(?:\/)?$/,
        ];
        const attachmentExtensions = /\.(?:pdf|png|jpe?g|gif|webp|svg|json|zip)$/i;
        const defaultProgressMessages = [
            "Understanding your topic...",
            "Preparing lesson...",
            "Creating notes...",
            "Building quiz...",
            "Preparing flashcards...",
            "Finalizing lesson...",
        ];
        const navigationProgressMessages = [
            "Opening your workspace...",
            "Loading saved progress...",
            "Preparing page tools...",
            "Almost ready...",
        ];
        const analyticsProgressMessages = [
            "Loading analytics...",
            "Reading your learning history...",
            "Preparing charts...",
            "Almost ready...",
        ];
        const messageRules = [
            { pattern: /dashboard/i, message: "Loading Dashboard..." },
            { pattern: /profile|my profile/i, message: "Opening Profile..." },
            { pattern: /learning history|study library/i, message: "Preparing Learning History..." },
            { pattern: /settings/i, message: "Opening Settings..." },
            { pattern: /performance|analytics/i, message: "Loading Performance Analytics..." },
            { pattern: /quiz history/i, message: "Opening Quiz History..." },
            { pattern: /saved notes|favourite/i, message: "Opening Saved Notes..." },
            { pattern: /revision/i, message: "Preparing Revision..." },
            { pattern: /important questions/i, message: "Preparing Important Questions..." },
            { pattern: /flashcards/i, message: "Preparing Flashcards..." },
            { pattern: /memory/i, message: "Opening Memory Challenge..." },
            { pattern: /tutor/i, message: "Opening AI Tutor..." },
            { pattern: /home|back to home|start new lesson/i, message: "Opening Home..." },
            { pattern: /login/i, message: "Opening Login..." },
            { pattern: /register|create/i, message: "Opening Registration..." },
            { pattern: /logout/i, message: "Signing Out..." },
        ];

        function ensurePageTransitionOverlayViewport() {
            if (overlay.parentElement !== document.body) {
                document.body.appendChild(overlay);
            }
        }

        function linkLabel(link) {
            return (link.dataset.pageLoadingLabel || link.textContent || "").replace(/\s+/g, " ").trim();
        }

        function sourceLabel(source) {
            if (!source) {
                return "";
            }
            return (source.dataset.pageLoadingLabel || source.textContent || source.value || "").replace(/\s+/g, " ").trim();
        }

        function sourceType(source, fallback) {
            if (!source) {
                return fallback || "JavaScript Navigation";
            }
            if (source instanceof HTMLFormElement) {
                return "Form Submit";
            }
            if (source.closest("[data-dashboard-sidebar]")) {
                return "Sidebar";
            }
            if (source.closest("[data-profile-dropdown], [data-profile-menu]")) {
                return "Profile Menu";
            }
            if (source.closest(".quick-actions-grid, .dashboard-panel, .dashboard-stat-grid, .dashboard-hero-grid")) {
                return "Dashboard Card";
            }
            return fallback || "Link";
        }

        function progressMessagesFor(text) {
            if (/learn|lesson|revision|flashcards|quiz|tutor/i.test(text)) {
                return defaultProgressMessages;
            }
            if (/performance|analytics|dashboard/i.test(text)) {
                return analyticsProgressMessages;
            }
            return navigationProgressMessages;
        }

        function startMessageRotation(firstMessage, messages) {
            window.clearInterval(messageTimer);
            const rotation = (messages && messages.length ? messages : navigationProgressMessages).filter(Boolean);
            messageIndex = 0;
            messageTarget.textContent = firstMessage || rotation[0] || "Loading...";
            messageTimer = window.setInterval(function () {
                messageIndex = (messageIndex + 1) % rotation.length;
                messageTarget.textContent = rotation[messageIndex];
            }, 1650);
        }

        function stopGenerationStepper() {
            window.clearInterval(generationStepTimer);
            generationStepTimer = null;
            generationStepIndex = 0;
            overlay.removeAttribute("data-generation");
            generationSteps.forEach(function (step) {
                step.classList.remove("is-active", "is-complete");
            });
        }

        function setGenerationStep(index) {
            generationStepIndex = Math.max(0, Math.min(index, generationSteps.length - 1));
            generationSteps.forEach(function (step, stepIndex) {
                step.classList.toggle("is-complete", stepIndex < generationStepIndex);
                step.classList.toggle("is-active", stepIndex === generationStepIndex);
            });
            if (generationSteps[generationStepIndex]) {
                const label = generationSteps[generationStepIndex].querySelector("strong");
                if (label) {
                    messageTarget.textContent = `${label.textContent}...`;
                }
            }
        }

        function startGenerationStepper() {
            if (!generationSteps.length) {
                return;
            }
            overlay.dataset.generation = "lesson";
            setGenerationStep(0);
            window.clearInterval(generationStepTimer);
            generationStepTimer = window.setInterval(function () {
                setGenerationStep((generationStepIndex + 1) % generationSteps.length);
            }, 1450);
        }

        function normalizeUrl(destination) {
            try {
                return new URL(destination, window.location.href);
            } catch (error) {
                return null;
            }
        }

        function contextualMessage(source, destinationUrl) {
            if (source && source.dataset && source.dataset.pageLoadingMessage) {
                return source.dataset.pageLoadingMessage;
            }

            const label = source && source.tagName === "A" ? linkLabel(source) : sourceLabel(source);
            const path = destinationUrl ? destinationUrl.pathname.replace(/[-_/]+/g, " ") : "";
            const haystack = `${label} ${path}`;
            const rule = messageRules.find(function (item) {
                return item.pattern.test(haystack);
            });

            if (rule) {
                return rule.message;
            }

            if (label) {
                return `Opening ${label.replace(/[.?!]+$/g, "")}...`;
            }
            return "Loading page...";
        }

        function contextualFormMessage(form, submitter, destinationUrl) {
            const label = `${sourceLabel(submitter)} ${sourceLabel(form)} ${destinationUrl.pathname}`;
            const rule = messageRules.find(function (item) {
                return item.pattern.test(label.replace(/[-_/]+/g, " "));
            });

            return {
                label,
                message: rule ? rule.message : "Preparing your request...",
            };
        }

        function isAttachmentUrl(url) {
            if (attachmentExtensions.test(url.pathname)) {
                return true;
            }
            return attachmentRoutePatterns.some(function (pattern) {
                return pattern.test(url.pathname);
            });
        }

        function isAttachmentLink(link, url) {
            if (link.hasAttribute("download")) {
                return true;
            }
            return isAttachmentUrl(url);
        }

        function isSamePageAnchor(rawDestination, url) {
            if (rawDestination && rawDestination.trim().startsWith("#")) {
                return true;
            }

            return (
                url.pathname === window.location.pathname &&
                url.search === window.location.search &&
                Boolean(url.hash)
            );
        }

        function isInternalPageUrl(destination, options) {
            const rawDestination = String(destination || "").trim();
            const url = normalizeUrl(rawDestination);
            if (!url) {
                return null;
            }

            if (
                /^(?:mailto|tel|javascript):/i.test(rawDestination) ||
                url.origin !== window.location.origin ||
                isSamePageAnchor(rawDestination, url) ||
                isAttachmentUrl(url)
            ) {
                return null;
            }

            if (options && options.allowCurrentPage !== true &&
                url.pathname === window.location.pathname &&
                url.search === window.location.search &&
                !url.hash
            ) {
                return null;
            }

            return url;
        }

        function suppressUnloadOverlay() {
            suppressUnloadOverlayUntil = Date.now() + 1800;
        }

        function shouldSkipPageLoaderElement(element) {
            return Boolean(
                element &&
                element.closest(
                    [
                        "[data-page-loader='false']",
                        "[data-no-page-loader]",
                        "[data-developer-users-link]",
                        "[data-diagram-lightbox]",
                        "[data-diagram-zoom]",
                        "[data-diagram-fullscreen]",
                    ].join(", ")
                )
            );
        }

        function shouldHandlePageTransition(event, link) {
            if (navigationLocked) {
                return true;
            }

            if (
                event.defaultPrevented ||
                event.button !== 0 ||
                event.metaKey ||
                event.ctrlKey ||
                event.shiftKey ||
                event.altKey
            ) {
                return false;
            }

            if (shouldSkipPageLoaderElement(link)) {
                suppressUnloadOverlay();
                return false;
            }

            const rawHref = link.getAttribute("href");
            const url = normalizeUrl(link.href);
            if (!rawHref || !url) {
                return false;
            }

            if (
                url.origin !== window.location.origin ||
                link.target && link.target !== "_self" ||
                /^(?:mailto|tel|javascript):/i.test(rawHref)
            ) {
                suppressUnloadOverlay();
                return false;
            }

            if (isSamePageAnchor(rawHref, url) || isAttachmentLink(link, url)) {
                suppressUnloadOverlay();
                return false;
            }

            return true;
        }

        function lockNavigation() {
            navigationLocked = true;
            document.documentElement.classList.add("page-transition-active");
        }

        function preventRepeatedNavigation(event) {
            event.preventDefault();
            event.stopImmediatePropagation();
        }

        function hidePageTransitionOverlay() {
            window.clearTimeout(pendingHideTimer);
            window.clearInterval(messageTimer);
            stopGenerationStepper();
            pendingHideTimer = null;
            messageTimer = null;
            navigationLocked = false;
            overlay.classList.remove("is-visible");
            overlay.hidden = true;
            document.documentElement.classList.remove("page-transition-active");
        }

        function showOverlay(message, label, options) {
            window.clearTimeout(pendingHideTimer);
            ensurePageTransitionOverlayViewport();
            startMessageRotation(message, progressMessagesFor(label));
            if (options && options.generation === "lesson") {
                startGenerationStepper();
            } else {
                stopGenerationStepper();
            }
            overlay.hidden = false;
            lockNavigation();
            overlay.offsetHeight;
            overlay.classList.add("is-visible");
        }

        function afterOverlayPaint(callback) {
            window.requestAnimationFrame(function () {
                window.setTimeout(callback, minimumOverlayPaintDelay);
            });
        }

        function showPageTransitionOverlay(link, destination) {
            const url = normalizeUrl(destination || link.href);
            if (!url) {
                return;
            }

            const label = `${linkLabel(link)} ${url.pathname}`;
            showOverlay(contextualMessage(link, url), label);
        }

        function shouldSkipFormTransition(form, url, method) {
            return Boolean(
                form.matches("[data-page-loader='false'], [data-no-page-loader], [data-endpoint], .tutor-composer") ||
                form.target && form.target !== "_self" ||
                method === "DIALOG" ||
                isAttachmentUrl(url)
            );
        }

        function showFormTransitionOverlay(form, submitter) {
            const method = (form.method || "GET").toUpperCase();
            const url = normalizeUrl(form.action || window.location.href);
            if (!url) {
                return false;
            }
            if (shouldSkipFormTransition(form, url, method)) {
                suppressUnloadOverlay();
                return false;
            }

            const context = contextualFormMessage(form, submitter, url);
            showOverlay(context.message, context.label, { generation: form.dataset.generationLoader });
            return true;
        }

        function markFormSubmitting(form, submitter) {
            const actualSubmitter = submitter || form.querySelector("button[type='submit'], input[type='submit']");
            form.dataset.submitting = "true";

            if (actualSubmitter) {
                actualSubmitter.classList.add("is-loading");
                actualSubmitter.setAttribute("aria-busy", "true");
            }

            form.querySelectorAll("button[type='submit'], input[type='submit']").forEach(function (button) {
                button.disabled = true;
            });

            const loadingRegion = form.closest(".quiz-box, .study-form, .tutor-composer, .report-download-form, .learning-action-card, .quiz-start-form, .notes-download-form");
            if (loadingRegion) {
                loadingRegion.classList.add("is-loading");
                loadingRegion.setAttribute("aria-busy", "true");
            }
        }

        function preserveSubmitterValue(form, submitter) {
            if (!submitter || !submitter.name || submitter.disabled) {
                return null;
            }

            const input = document.createElement("input");
            input.type = "hidden";
            input.name = submitter.name;
            input.value = submitter.value;
            input.dataset.pageLoaderSubmitter = "true";
            form.appendChild(input);
            return input;
        }

        function submitAfterOverlayPaint(form, submitter) {
            const hiddenSubmitter = preserveSubmitterValue(form, submitter);
            markFormSubmitting(form, submitter);
            afterOverlayPaint(function () {
                nativeFormSubmit.call(form);
                if (hiddenSubmitter && hiddenSubmitter.parentNode) {
                    hiddenSubmitter.parentNode.removeChild(hiddenSubmitter);
                }
            });
        }

        function navigate(destination, source, options) {
            const settings = options || {};
            const url = isInternalPageUrl(destination, settings);
            if (!url) {
                return false;
            }

            if (navigationLocked) {
                return true;
            }

            if (source && source.tagName === "A") {
                showPageTransitionOverlay(source, url.href);
            } else {
                showOverlay(contextualMessage(source, url), `${sourceLabel(source)} ${url.pathname}`);
            }

            afterOverlayPaint(function () {
                if (settings.replace) {
                    nativeLocationReplace(url.href);
                } else {
                    nativeLocationAssign(url.href);
                }
                // window.location.assign(destination) is routed through this centralized manager.
            });
            return true;
        }

        function navigateAfterOverlayPaint(link) {
            const destination = link.href;
            afterOverlayPaint(function () {
                nativeLocationAssign(destination);
                // window.location.assign(destination) is routed through this centralized manager.
            });
        }

        function handlePageTransitionClick(event) {
            const eventTarget = event.target instanceof Element ? event.target : null;
            const link = eventTarget ? eventTarget.closest("a[href]") : null;
            if (navigationLocked) {
                preventRepeatedNavigation(event);
                return;
            }

            if (!link || !shouldHandlePageTransition(event, link)) {
                return;
            }

            event.preventDefault();
            showPageTransitionOverlay(link);
            navigateAfterOverlayPaint(link);
        }

        function handlePageTransitionSubmit(event) {
            const form = event.target;
            if (!(form instanceof HTMLFormElement)) {
                return;
            }

            if (navigationLocked) {
                preventRepeatedNavigation(event);
                return;
            }

            if (event.defaultPrevented || shouldSkipPageLoaderElement(form)) {
                suppressUnloadOverlay();
                return;
            }

            event.preventDefault();
            if (!showFormTransitionOverlay(form, event.submitter)) {
                nativeFormSubmit.call(form);
                return;
            }
            submitAfterOverlayPaint(form, event.submitter);
        }

        function patchLocationMethod(methodName, nativeMethod, replace) {
            try {
                window.location[methodName] = function (destination) {
                    if (!navigate(destination, null, { allowCurrentPage: true, replace })) {
                        nativeMethod(destination);
                    }
                };
            } catch (error) {
                return;
            }
        }

        function handleBeforeUnload() {
            if ("navigation" in window || navigationLocked || Date.now() < suppressUnloadOverlayUntil) {
                return;
            }

            showOverlay("Loading page...", window.location.pathname);
        }

        function handleNavigationEvent(event) {
            if (navigationLocked || !event.destination || !event.destination.url) {
                return;
            }

            const url = isInternalPageUrl(event.destination.url, { allowCurrentPage: true });
            if (!url) {
                suppressUnloadOverlay();
                return;
            }

            showOverlay(contextualMessage(null, url), url.pathname);
        }

        patchLocationMethod("assign", nativeLocationAssign, false);
        patchLocationMethod("replace", nativeLocationReplace, true);

        window.AIStudyBuddyPageLoader = {
            navigate,
            showForForm: showFormTransitionOverlay,
            hide: hidePageTransitionOverlay,
        };
        window.navigate = navigate;
        window.goTo = navigate;

        document.addEventListener("click", handlePageTransitionClick, true);
        document.addEventListener("submit", handlePageTransitionSubmit);
        if ("navigation" in window) {
            window.navigation.addEventListener("navigate", handleNavigationEvent);
        }
        window.addEventListener("beforeunload", handleBeforeUnload);
        window.addEventListener("pageshow", hidePageTransitionOverlay);
        window.addEventListener("focus", function () {
            if (!document.hidden) {
                pendingHideTimer = window.setTimeout(function () {
                    if (document.visibilityState === "visible") {
                        hidePageTransitionOverlay();
                    }
                }, 800);
            }
        });
    }

    function initializeMotion() {
        setupReveal();
        setupCounters();
        setupPageTransitionOverlay();
        setupLoadingStates();
        setupSuccessMotion();
        setupSidebarMotion();
        setupDemoButtons();
        setupExhibitionTour();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initializeMotion);
    } else {
        initializeMotion();
    }
})();
