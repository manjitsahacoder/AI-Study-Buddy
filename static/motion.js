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
            target.classList.add("motion-reveal");
            target.style.setProperty("--motion-delay", `${Math.min(index % 6, 5) * 35}ms`);
            revealObserver.observe(target);
        });
    }

    function setupLoadingStates() {
        document.querySelectorAll("form").forEach(function (form) {
            form.addEventListener("submit", function (event) {
                const submitter = event.submitter || form.querySelector("button[type='submit'], input[type='submit']");
                if (!submitter || submitter.disabled) {
                    return;
                }

                submitter.classList.add("is-loading");
                submitter.setAttribute("aria-busy", "true");

                const loadingRegion = form.closest(".quiz-box, .study-form, .tutor-composer, .report-download-form, .learning-action-card, .quiz-start-form, .notes-download-form");
                if (loadingRegion) {
                    loadingRegion.classList.add("is-loading");
                    loadingRegion.setAttribute("aria-busy", "true");
                }
            });
        });
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

    document.addEventListener("DOMContentLoaded", function () {
        setupReveal();
        setupCounters();
        setupLoadingStates();
        setupSuccessMotion();
        setupSidebarMotion();
        setupDemoButtons();
        setupExhibitionTour();
    });
})();
