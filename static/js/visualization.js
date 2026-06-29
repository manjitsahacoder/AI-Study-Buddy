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

    document.querySelectorAll("[data-diagram-library-card]").forEach(initDiagramCard);
}());
