(function () {
    const dismissKey = "ai-study-buddy-install-dismissed";
    let deferredInstallPrompt = null;

    function isStandalone() {
        return window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone === true;
    }

    function dismissedInstallBanner() {
        try {
            return localStorage.getItem(dismissKey) === "1";
        } catch (error) {
            return false;
        }
    }

    function rememberDismissedInstallBanner() {
        try {
            localStorage.setItem(dismissKey, "1");
        } catch (error) {
            return null;
        }
        return null;
    }

    function installBanner() {
        return document.querySelector("[data-pwa-install-banner]");
    }

    function hideInstallBanner() {
        const banner = installBanner();
        if (banner) {
            banner.hidden = true;
        }
    }

    function showInstallBanner() {
        const banner = installBanner();
        if (!banner || dismissedInstallBanner() || isStandalone()) {
            return;
        }
        banner.hidden = false;
    }

    function setupInstallPrompt() {
        const banner = installBanner();
        if (!banner) {
            return;
        }

        const installButton = banner.querySelector("[data-pwa-install]");
        const dismissButton = banner.querySelector("[data-pwa-dismiss]");

        if (installButton) {
            installButton.addEventListener("click", async function () {
                if (!deferredInstallPrompt) {
                    hideInstallBanner();
                    return;
                }

                deferredInstallPrompt.prompt();
                await deferredInstallPrompt.userChoice;
                deferredInstallPrompt = null;
                hideInstallBanner();
            });
        }

        if (dismissButton) {
            dismissButton.addEventListener("click", function () {
                rememberDismissedInstallBanner();
                hideInstallBanner();
            });
        }
    }

    if ("serviceWorker" in navigator) {
        window.addEventListener("load", function () {
            navigator.serviceWorker.register("/service-worker.js", { scope: "/" }).catch(function () {
                return null;
            });
        });
    }

    window.addEventListener("beforeinstallprompt", function (event) {
        event.preventDefault();
        deferredInstallPrompt = event;
        showInstallBanner();
    });

    window.addEventListener("appinstalled", function () {
        deferredInstallPrompt = null;
        hideInstallBanner();
    });

    document.addEventListener("DOMContentLoaded", setupInstallPrompt);
})();
