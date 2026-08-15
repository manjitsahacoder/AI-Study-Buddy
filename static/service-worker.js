const CACHE_VERSION = "ai-study-buddy-pwa-v8";
const STATIC_CACHE = `${CACHE_VERSION}-static`;
const OFFLINE_URL = "/offline";

const PRECACHE_URLS = [
    OFFLINE_URL,
    "/manifest.json?v=ai-study-buddy-v2",
    "/static/style.css",
    "/static/motion.js",
    "/static/pwa.js",
    "/static/tutor.js",
    "/static/css/visualization.css",
    "/static/js/visualization.js",
    "/static/js/memory_challenge.js",
    "/static/images/ai-study-buddy-mark-v2.png",
    "/static/images/study_banner.png",
    "/static/images/backgrounds/ai-brain-circuit.svg",
    "/static/images/backgrounds/home-education.svg",
    "/static/images/backgrounds/learn-doodles.svg",
    "/static/images/backgrounds/pencil.svg",
    "/static/images/backgrounds/quiz-doodles.svg",
    "/static/images/backgrounds/result-success.svg",
    "/static/icons/favicon.ico?v=ai-study-buddy-v2",
    "/static/icons/favicon-16.png?v=ai-study-buddy-v2",
    "/static/icons/favicon-16x16.png?v=ai-study-buddy-v2",
    "/static/icons/favicon-32.png?v=ai-study-buddy-v2",
    "/static/icons/favicon-32x32.png?v=ai-study-buddy-v2",
    "/static/icons/apple-touch-icon.png?v=ai-study-buddy-v2",
    "/static/icons/icon-48.png?v=ai-study-buddy-v2",
    "/static/icons/icon-72.png?v=ai-study-buddy-v2",
    "/static/icons/icon-96.png?v=ai-study-buddy-v2",
    "/static/icons/icon-128.png?v=ai-study-buddy-v2",
    "/static/icons/icon-144.png?v=ai-study-buddy-v2",
    "/static/icons/icon-152.png?v=ai-study-buddy-v2",
    "/static/icons/icon-180.png?v=ai-study-buddy-v2",
    "/static/icons/icon-192.png?v=ai-study-buddy-v2",
    "/static/icons/icon-256.png?v=ai-study-buddy-v2",
    "/static/icons/icon-384.png?v=ai-study-buddy-v2",
    "/static/icons/icon-512.png?v=ai-study-buddy-v2",
    "/static/icons/maskable-192.png?v=ai-study-buddy-v2",
    "/static/icons/maskable-512.png?v=ai-study-buddy-v2",
    "/static/icons/maskable-icon.png?v=ai-study-buddy-v2"
];

const STATIC_DESTINATIONS = new Set(["style", "script", "image", "font", "manifest"]);

function isSameOrigin(request) {
    return new URL(request.url).origin === self.location.origin;
}

function isCacheableStaticRequest(request) {
    if (request.method !== "GET" || !isSameOrigin(request)) {
        return false;
    }

    const url = new URL(request.url);
    return STATIC_DESTINATIONS.has(request.destination) || url.pathname.startsWith("/static/");
}

async function cacheFirst(request) {
    const cached = await caches.match(request);
    if (cached) {
        return cached;
    }

    const response = await fetch(request);
    if (response && response.ok) {
        const cache = await caches.open(STATIC_CACHE);
        cache.put(request, response.clone());
    }
    return response;
}

async function networkOnlyNavigation(request) {
    try {
        return await fetch(request);
    } catch (error) {
        return caches.match(OFFLINE_URL);
    }
}

self.addEventListener("install", (event) => {
    event.waitUntil(
        caches.open(STATIC_CACHE)
            .then((cache) => cache.addAll(PRECACHE_URLS))
            .then(() => self.skipWaiting())
    );
});

self.addEventListener("activate", (event) => {
    event.waitUntil(
        caches.keys()
            .then((cacheNames) => Promise.all(
                cacheNames
                    .filter((cacheName) => cacheName.startsWith("ai-study-buddy-pwa-") && !cacheName.startsWith(CACHE_VERSION))
                    .map((cacheName) => caches.delete(cacheName))
            ))
            .then(() => self.clients.claim())
    );
});

self.addEventListener("fetch", (event) => {
    const request = event.request;

    if (request.method !== "GET" || !isSameOrigin(request)) {
        return;
    }

    if (request.mode === "navigate") {
        event.respondWith(networkOnlyNavigation(request));
        return;
    }

    if (isCacheableStaticRequest(request)) {
        event.respondWith(cacheFirst(request));
    }
});
