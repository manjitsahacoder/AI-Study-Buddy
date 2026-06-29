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

        function toggleZoom() {
            card.classList.toggle("is-zoomed");
            setButtonLabel(zoomButton, "Reset Zoom", "Zoom", card.classList.contains("is-zoomed"));
        }

        image.addEventListener("click", toggleZoom);
        zoomButton?.addEventListener("click", toggleZoom);

        fullscreenButton?.addEventListener("click", function () {
            card.classList.toggle("is-fullscreen");
            setButtonLabel(fullscreenButton, "Exit Fullscreen", "Fullscreen", card.classList.contains("is-fullscreen"));
        });

        document.addEventListener("keydown", function (event) {
            if (event.key !== "Escape" || !card.classList.contains("is-fullscreen")) {
                return;
            }
            card.classList.remove("is-fullscreen");
            setButtonLabel(fullscreenButton, "Exit Fullscreen", "Fullscreen", false);
        });
    }

    document.querySelectorAll("[data-diagram-library-card]").forEach(initDiagramCard);
}());
