// ITENARO Service Worker - Enables offline mode for travelers
const CACHE_NAME = 'itenaro-v4';
const STATIC_ASSETS = [
    '/',
    '/static/styles.css',
    '/static/index-redesign.css',
    '/static/scripts/script.js',
    '/static/scripts/firebase-config.js',
    '/static/scripts/firebase-auth.js',
    '/static/images/logo.jpg',
    '/static/manifest.json',
    'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css',
    'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js',
    'https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.2/jspdf.umd.min.js',
    'https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js',
    'https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400;700;900&family=DM+Sans:wght@300;400;500;700&display=swap'
];

const DYNAMIC_CACHE = 'itenaro-dynamic-v4';
const OFFLINE_ITINERARY_URL = '/offline/last-itinerary.json';
const OFFLINE_ITINERARY_META_URL = '/offline/last-itinerary-meta.json';

// Install event - cache static assets
self.addEventListener('install', event => {
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then(cache => {
                console.log('[SW] Caching static assets');
                return cache.addAll(STATIC_ASSETS);
            })
            .catch(err => {
                console.warn('[SW] Some assets failed to cache:', err);
            })
    );
    self.skipWaiting();
});

// Activate event - clean up old caches
self.addEventListener('activate', event => {
    event.waitUntil(
        caches.keys().then(keys => {
            return Promise.all(
                keys.filter(key => key !== CACHE_NAME && key !== DYNAMIC_CACHE)
                    .map(key => {
                        console.log('[SW] Removing old cache:', key);
                        return caches.delete(key);
                    })
            );
        })
    );
    self.clients.claim();
});

// Message event - cache explicit itinerary payload for offline landing mode
self.addEventListener('message', event => {
    const { data } = event || {};
    if (!data || data.type !== 'CACHE_ITINERARY' || !data.payload) {
        return;
    }

    event.waitUntil((async () => {
        const cache = await caches.open(DYNAMIC_CACHE);
        await cache.put(
            OFFLINE_ITINERARY_URL,
            new Response(JSON.stringify(data.payload), {
                headers: { 'Content-Type': 'application/json' }
            })
        );

        await cache.put(
            OFFLINE_ITINERARY_META_URL,
            new Response(JSON.stringify({ cached_at: new Date().toISOString() }), {
                headers: { 'Content-Type': 'application/json' }
            })
        );
    })());
});

// Fetch event - serve from cache, fallback to network
self.addEventListener('fetch', event => {
    const { request } = event;
    const url = new URL(request.url);

    // Skip non-GET requests
    if (request.method !== 'GET') return;

    // Explicit offline itinerary cache endpoint
    if (url.pathname === OFFLINE_ITINERARY_URL || url.pathname === OFFLINE_ITINERARY_META_URL) {
        event.respondWith(
            caches.open(DYNAMIC_CACHE).then(cache =>
                cache.match(url.pathname).then(cached => {
                    if (cached) {
                        return cached;
                    }
                    return new Response(JSON.stringify({ error: 'No cached itinerary available.' }), {
                        headers: { 'Content-Type': 'application/json' },
                        status: 404,
                    });
                })
            )
        );
        return;
    }

    // Skip API calls that need fresh data
    if (url.pathname.startsWith('/api/') ||
        url.pathname.startsWith('/generate-') ||
        url.pathname.startsWith('/get-weather')) {
        // Network-first for API calls, cache response for offline
        event.respondWith(
            fetch(request)
                .then(response => {
                    // Cache successful API responses for offline access
                    if (response.ok) {
                        const responseClone = response.clone();
                        caches.open(DYNAMIC_CACHE).then(cache => {
                            cache.put(request, responseClone);
                        });
                    }
                    return response;
                })
                .catch(() => {
                    // If offline, try to serve cached API response
                    return caches.match(request).then(cachedResponse => {
                        if (cachedResponse) {
                            return cachedResponse;
                        }
                        // Return offline-friendly error
                        return new Response(
                            JSON.stringify({ error: 'You are offline. This data is not available.' }),
                            { headers: { 'Content-Type': 'application/json' } }
                        );
                    });
                })
        );
        return;
    }

    // Cache-first for static assets
    event.respondWith(
        caches.match(request)
            .then(cachedResponse => {
                if (cachedResponse) {
                    return cachedResponse;
                }

                return fetch(request).then(response => {
                    // Cache new static resources
                    if (response.ok && (
                        url.pathname.startsWith('/static/') ||
                        url.pathname === '/' ||
                        url.pathname.startsWith('/destinations') ||
                        url.pathname.startsWith('/blog') ||
                        url.pathname.startsWith('/shared/')
                    )) {
                        const responseClone = response.clone();
                        caches.open(DYNAMIC_CACHE).then(cache => {
                            cache.put(request, responseClone);
                        });
                    }
                    return response;
                });
            })
            .catch(() => {
                // Offline fallback for HTML pages
                if (request.headers.get('accept').includes('text/html')) {
                    return caches.match('/');
                }
            })
    );
});
