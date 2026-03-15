// Import Firebase authentication functions
import {
    signInUser,
    registerUser,
    signInWithGoogle,
    signOutUser,
    resetPassword,
    onAuthStateChange,
    getCurrentUser,
    getErrorMessage,
    showMessage,
    updateUIForUser,
    updateUIForSignedOut,
    toggleProfileDropdown,
    initDropdownHandler
} from './firebase-auth.js';

document.addEventListener("DOMContentLoaded", function () {
    let currentStep = 1;
    const totalSteps = 5;
    let selectedPreferences = [];
    let currentItineraryData = null; // Store structured itinerary data
    let currentItineraryRevision = 1;
    let lastSavedItineraryId = null;
    let presenceHeartbeatTimer = null;
    let latestSyncConflict = null;
    let latestJournal = null;
    let journalAutosaveTimer = null;
    let journalMediaUrls = [];
    let journalVersionHistory = [];
    let currentDayToReplan = null;
    let currentEvents = [];
    let currentNearbyPlaces = [];
    let nearbyRequestSignature = '';
    let currentMapDay = 'all';
    let showEventsLayer = true;
    let showNearbyLayer = true;
    let itineraryMap = null; // Leaflet map instance
    let mapMarkers = []; // Store map markers
    let eventMarkers = []; // Store events markers
    let nearbyMarkers = []; // Store nearby discovery markers
    let mapPolylines = []; // Store route lines
    let budgetCategoryChart = null;
    let budgetDailyChart = null;
    const exchangeRatesByBase = {};

    const replanModal = document.getElementById("replanModal");
    const replanInstruction = document.getElementById("replanInstruction");
    const replanStatus = document.getElementById("replanStatus");
    const replanModalTitle = document.getElementById("replanModalTitle");
    const replanCancelBtn = document.getElementById("replanCancelBtn");
    const replanSubmitBtn = document.getElementById("replanSubmitBtn");
    const offlineBanner = document.getElementById("offlineBanner");
    const syncIndicator = document.getElementById("syncIndicator");
    const itineraryTitle = document.getElementById("itineraryTitle");
    const itineraryMetaPills = document.getElementById("itineraryMetaPills");
    const presenceStrip = document.getElementById("presenceStrip");
    const syncConflictBanner = document.getElementById("syncConflictBanner");
    const priceHintsBar = document.getElementById("priceHintsBar");
    const eventsPanel = document.getElementById("eventsPanel");
    const eventsList = document.getElementById("eventsList");
    const eventsCategoryFilter = document.getElementById("eventsCategoryFilter");
    const toggleEventsLayer = document.getElementById("toggleEventsLayer");
    const toggleNearbyLayer = document.getElementById("toggleNearbyLayer");
    const refreshNearbyBtn = document.getElementById("refreshNearbyBtn");
    const journalBtn = document.getElementById("journalBtn");
    const journalPanel = document.getElementById("journalPanel");
    const closeJournalBtn = document.getElementById("closeJournalBtn");
    const generateJournalBtn = document.getElementById("generateJournalBtn");
    const publishJournalBtn = document.getElementById("publishJournalBtn");
    const journalTone = document.getElementById("journalTone");
    const journalTitleInput = document.getElementById("journalTitle");
    const journalTagsInput = document.getElementById("journalTags");
    const journalContentInput = document.getElementById("journalContent");
    const journalHighlights = document.getElementById("journalHighlights");
    const journalStatus = document.getElementById("journalStatus");
    const journalAutosaveInfo = document.getElementById("journalAutosaveInfo");
    const journalMediaList = document.getElementById("journalMediaList");
    const journalHistoryList = document.getElementById("journalHistoryList");
    const loadJournalHistoryBtn = document.getElementById("loadJournalHistoryBtn");
    const uploadJournalImageBtn = document.getElementById("uploadJournalImageBtn");
    const journalImageInput = document.getElementById("journalImageInput");

    function updateSyncIndicator(label = "", timestamp = null) {
        if (!syncIndicator) return;

        const normalized = String(label || '').toLowerCase();
        let state = 'idle';
        if (normalized.includes('sync')) {
            state = 'synced';
        } else if (normalized.includes('cache') || normalized.includes('offline')) {
            state = 'cached';
        } else if (normalized.includes('conflict') || normalized.includes('fail') || normalized.includes('error')) {
            state = 'error';
        }

        syncIndicator.dataset.state = state;

        const syncText = syncIndicator.querySelector('.sync-text');
        const ts = timestamp || null;
        const human = ts ? new Date(ts).toLocaleString() : '';
        const display = label || 'Not synced yet';

        if (syncText) {
            syncText.textContent = display;
        } else {
            syncIndicator.textContent = display;
        }

        syncIndicator.title = human ? `Last updated ${human}` : 'Sync status';
    }

    function getOfflineItineraryKey() {
        return 'itenaro_last_itinerary';
    }

    function showOfflineBanner(isOffline) {
        if (!offlineBanner) return;
        offlineBanner.style.display = isOffline ? 'block' : 'none';
    }

    function cacheItineraryInServiceWorker(offlinePayload) {
        if (!navigator.serviceWorker || !navigator.serviceWorker.controller) return;
        try {
            navigator.serviceWorker.controller.postMessage({
                type: 'CACHE_ITINERARY',
                payload: offlinePayload,
            });
        } catch (messageError) {
            console.warn('Failed to send itinerary payload to service worker:', messageError);
        }
    }

    function persistOfflineItinerary(sourceLabel = 'sync') {
        if (!currentItineraryData) return;

        const payload = {
            itinerary_data: currentItineraryData,
            itinerary_html: document.getElementById('itinerary-content')?.innerHTML || '',
            destination: document.getElementById('destination')?.value || '',
            budget: document.getElementById('budget')?.value || '',
            duration: document.getElementById('duration')?.value || '',
            purpose: document.getElementById('purpose')?.value || '',
            revision: currentItineraryRevision || 1,
            saved_at: new Date().toISOString(),
        };

        localStorage.setItem(getOfflineItineraryKey(), JSON.stringify(payload));
        cacheItineraryInServiceWorker(payload);
        updateSyncIndicator(sourceLabel, payload.saved_at);
    }

    async function loadOfflineItineraryIfAvailable() {
        if (currentItineraryData) return false;

        let raw = localStorage.getItem(getOfflineItineraryKey());

        if (!raw && !navigator.onLine) {
            try {
                const swResponse = await fetch('/offline/last-itinerary.json');
                if (swResponse.ok) {
                    const swPayload = await swResponse.json();
                    raw = JSON.stringify(swPayload);
                    localStorage.setItem(getOfflineItineraryKey(), raw);
                }
            } catch (_swReadError) {
                // Ignore and continue fallback flow.
            }
        }

        if (!raw) return false;

        try {
            const payload = JSON.parse(raw);
            if (!payload || !payload.itinerary_data || !Array.isArray(payload.itinerary_data.days)) {
                return false;
            }

            const itinerarySection = document.getElementById("itinerary");
            const itineraryContent = document.getElementById("itinerary-content");
            if (itinerarySection) itinerarySection.style.display = 'block';
            if (itineraryContent && payload.itinerary_html) itineraryContent.innerHTML = payload.itinerary_html;

            currentItineraryData = payload.itinerary_data;
            currentItineraryRevision = Number(payload.revision || 1) || 1;
            renderItineraryMap(currentItineraryData);
            injectReplanButtons();
            buildItineraryDayTabs();

            if (payload.destination && document.getElementById('destination')) {
                document.getElementById('destination').value = payload.destination;
            }
            if (payload.duration && document.getElementById('duration')) {
                document.getElementById('duration').value = payload.duration;
            }
            if (payload.budget && document.getElementById('budget')) {
                document.getElementById('budget').value = payload.budget;
            }
            if (payload.purpose && document.getElementById('purpose')) {
                document.getElementById('purpose').value = payload.purpose;
            }

            updateItineraryHeaderMeta();
            updateSyncIndicator('Offline cache', payload.saved_at);
            return true;
        } catch (error) {
            console.error('Failed to load offline itinerary:', error);
            return false;
        }
    }

    async function getAuthHeaders(includeJsonContentType = false) {
        const user = getCurrentUser();
        const headers = {};

        if (includeJsonContentType) {
            headers["Content-Type"] = "application/json";
        }

        if (!user) {
            return headers;
        }

        try {
            const token = await user.getIdToken();
            headers.Authorization = `Bearer ${token}`;
            return headers;
        } catch (authError) {
            console.error("Failed to get Firebase token:", authError);
            return headers;
        }
    }

    async function authJsonFetch(url, options = {}) {
        const needsJson = options.body !== undefined || options.forceJsonHeader;
        const authHeaders = await getAuthHeaders(needsJson);
        const mergedHeaders = {
            ...authHeaders,
            ...(options.headers || {})
        };

        const requestOptions = {
            ...options,
            headers: mergedHeaders,
        };

        delete requestOptions.forceJsonHeader;
        return fetch(url, requestOptions);
    }

    function escapeHtml(value) {
        return String(value || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function classifyBudgetTier(rawBudget) {
        const budgetValue = parseBudgetInput(rawBudget);
        if (!budgetValue) {
            return 'Budget not set';
        }
        if (budgetValue < 1200) {
            return 'Budget';
        }
        if (budgetValue < 3500) {
            return 'Mid-range';
        }
        return 'Premium';
    }

    function parseBudgetInput(rawBudget) {
        const budgetMatch = String(rawBudget || '').match(/[\d,]+(?:\.\d+)?/);
        if (!budgetMatch) return 0;
        const parsed = parseFloat(budgetMatch[0].replace(/,/g, ''));
        return Number.isFinite(parsed) ? parsed : 0;
    }

    function formatCurrencyValue(value, currency) {
        const safeValue = Number.isFinite(Number(value)) ? Number(value) : 0;
        const safeCurrency = String(currency || 'USD').toUpperCase();
        try {
            return new Intl.NumberFormat('en-US', {
                style: 'currency',
                currency: safeCurrency,
                maximumFractionDigits: 2,
            }).format(safeValue);
        } catch (_formatError) {
            return `${safeCurrency} ${safeValue.toFixed(2)}`;
        }
    }

    function updateItineraryHeaderMeta() {
        const destination = String(document.getElementById('destination')?.value || '').trim();
        const duration = String(document.getElementById('duration')?.value || '').trim();
        const budget = String(document.getElementById('budget')?.value || '').trim();
        const purpose = String(document.getElementById('purpose')?.value || '').trim();

        if (itineraryTitle) {
            itineraryTitle.textContent = destination || 'Your Personalized Itinerary';
        }

        if (!itineraryMetaPills) return;

        const pills = [];
        if (duration) pills.push({ icon: '📅', text: duration });
        if (budget) pills.push({ icon: '💰', text: classifyBudgetTier(budget) });
        if (purpose) pills.push({ icon: '🧭', text: purpose });

        const preferencePreview = selectedPreferences.slice(0, 2);
        if (preferencePreview.length) {
            pills.push({ icon: '✨', text: preferencePreview.join(' • ') });
        }

        itineraryMetaPills.innerHTML = pills
            .map(pill => `<span class="itinerary-meta-pill"><span>${pill.icon}</span><b>${escapeHtml(pill.text)}</b></span>`)
            .join('');
    }

    function buildItineraryDayTabs(activeDay = 'all') {
        const itineraryContent = document.getElementById('itinerary-content');
        if (!itineraryContent) return;

        const existingTabs = itineraryContent.querySelector('.itn-tabs');
        if (existingTabs) {
            existingTabs.remove();
        }

        const dayCards = Array.from(itineraryContent.querySelectorAll('.itin-day'));
        if (!dayCards.length) return;

        const tabsBar = document.createElement('div');
        tabsBar.className = 'itn-tabs';

        const tabButtons = [];
        function addTab(label, dayValue) {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'itn-tab';
            button.dataset.day = String(dayValue);
            button.textContent = label;
            tabsBar.appendChild(button);
            tabButtons.push(button);
        }

        addTab('All days', 'all');
        dayCards.forEach((card, index) => {
            const dayValue = String(card.dataset.dayNumber || index + 1);
            addTab(`Day ${dayValue}`, dayValue);
        });

        function applyDayFilter(targetDay) {
            const normalizedTarget = String(targetDay || 'all');
            tabButtons.forEach(button => {
                button.classList.toggle('active', button.dataset.day === normalizedTarget);
            });

            dayCards.forEach((card, index) => {
                const dayValue = String(card.dataset.dayNumber || index + 1);
                card.style.display = normalizedTarget === 'all' || normalizedTarget === dayValue ? 'block' : 'none';
            });
        }

        tabButtons.forEach(button => {
            button.addEventListener('click', function () {
                applyDayFilter(this.dataset.day || 'all');
            });
        });

        itineraryContent.prepend(tabsBar);

        const requested = String(activeDay || 'all');
        const exists = tabButtons.some(button => button.dataset.day === requested);
        applyDayFilter(exists ? requested : 'all');
    }

    function renderItineraryErrorState(title, message, detail = '') {
        const itineraryContent = document.getElementById('itinerary-content');
        if (!itineraryContent) return;

        const safeTitle = escapeHtml(title || "Couldn't generate your itinerary");
        const safeMessage = escapeHtml(message || 'We hit an issue reaching our AI planner.');
        const safeDetail = escapeHtml(detail || '');

        itineraryContent.innerHTML = `
            <div class="itn-error">
                <div class="itn-error-icon">⚠</div>
                <div class="itn-error-title">${safeTitle}</div>
                <div class="itn-error-text">${safeMessage}</div>
                ${safeDetail ? `<p class="itn-error-detail">${safeDetail}</p>` : ''}
                <div class="itn-error-actions">
                    <button type="button" class="err-btn-primary" data-error-action="retry">Try Again</button>
                    <button type="button" class="err-btn-secondary" data-error-action="adjust">Adjust Preferences</button>
                </div>
            </div>
        `;

        const retryBtn = itineraryContent.querySelector('[data-error-action="retry"]');
        if (retryBtn) {
            retryBtn.addEventListener('click', function () {
                const button = document.getElementById('generateBtn');
                if (button) button.click();
            });
        }

        const adjustBtn = itineraryContent.querySelector('[data-error-action="adjust"]');
        if (adjustBtn) {
            adjustBtn.addEventListener('click', function () {
                const stepFive = document.getElementById('step5');
                if (stepFive) {
                    currentStep = 5;
                    document.querySelectorAll('.step').forEach(step => {
                        step.style.display = 'none';
                    });
                    stepFive.style.display = 'block';
                }
                stepFive?.scrollIntoView({ behavior: 'smooth', block: 'center' });
            });
        }
    }

    function getSelectedNearbyTypes() {
        const selected = Array.from(document.querySelectorAll('.nearby-type-input:checked'))
            .map(input => String(input.value || '').trim().toLowerCase())
            .filter(Boolean);

        return selected.length ? selected : ['restaurant', 'cafe', 'attraction'];
    }

    function hideSyncConflictBanner() {
        latestSyncConflict = null;
        if (!syncConflictBanner) return;
        syncConflictBanner.style.display = 'none';
        syncConflictBanner.innerHTML = '';
    }

    function renderPresenceStrip(activeRows) {
        if (!presenceStrip) return;
        if (!Array.isArray(activeRows) || !activeRows.length) {
            presenceStrip.style.display = 'none';
            presenceStrip.textContent = '';
            return;
        }

        const currentUser = getCurrentUser();
        const labels = activeRows.slice(0, 6).map(row => {
            const uid = String(row.firebase_uid || '').trim();
            const email = String(row.email || '').trim();
            const status = String(row.status || 'viewing').trim();

            let name = 'Collaborator';
            if (currentUser && uid && currentUser.uid === uid) {
                name = 'You';
            } else if (email.includes('@')) {
                name = email.split('@')[0];
            } else if (uid) {
                name = uid.slice(0, 8);
            }

            return `${name} (${status})`;
        });

        const extraCount = activeRows.length - labels.length;
        const suffix = extraCount > 0 ? ` +${extraCount} more` : '';
        presenceStrip.textContent = `Active now: ${labels.join(', ')}${suffix}`;
        presenceStrip.style.display = 'block';
    }

    async function pushPresenceHeartbeat(status = 'viewing', cursorContext = null) {
        if (!lastSavedItineraryId) {
            renderPresenceStrip([]);
            return;
        }

        const user = getCurrentUser();
        if (!user) return;

        try {
            const response = await authJsonFetch(`/api/itineraries/${lastSavedItineraryId}/presence`, {
                method: 'POST',
                body: JSON.stringify({
                    status,
                    cursor_context: cursorContext,
                }),
            });
            const payload = await response.json();
            if (!response.ok) {
                throw new Error(payload.error || 'Failed to update presence');
            }

            renderPresenceStrip(payload.active || []);
        } catch (presenceError) {
            console.error('Presence heartbeat failed:', presenceError);
        }
    }

    function startPresenceHeartbeat() {
        if (presenceHeartbeatTimer) {
            clearInterval(presenceHeartbeatTimer);
            presenceHeartbeatTimer = null;
        }

        if (!lastSavedItineraryId || !getCurrentUser()) {
            renderPresenceStrip([]);
            return;
        }

        pushPresenceHeartbeat(document.hidden ? 'idle' : 'viewing');
        presenceHeartbeatTimer = setInterval(() => {
            pushPresenceHeartbeat(document.hidden ? 'idle' : 'viewing');
        }, 15000);
    }

    function applyServerItineraryVersion(latest) {
        if (!latest || typeof latest !== 'object') return;

        const itinerarySection = document.getElementById('itinerary');
        const itineraryContent = document.getElementById('itinerary-content');
        if (itinerarySection) itinerarySection.style.display = 'block';

        if (itineraryContent && typeof latest.itinerary_html === 'string') {
            itineraryContent.innerHTML = latest.itinerary_html;
        }

        if (latest.destination && document.getElementById('destination')) {
            document.getElementById('destination').value = latest.destination;
        }
        if (latest.duration && document.getElementById('duration')) {
            document.getElementById('duration').value = latest.duration;
        }
        if (latest.budget && document.getElementById('budget')) {
            document.getElementById('budget').value = latest.budget;
        }
        if (latest.purpose && document.getElementById('purpose')) {
            document.getElementById('purpose').value = latest.purpose;
        }

        if (latest.itinerary_data && typeof latest.itinerary_data === 'object') {
            currentItineraryData = latest.itinerary_data;
            renderItineraryMap(currentItineraryData);
            injectReplanButtons();
            buildItineraryDayTabs();
            persistOfflineItinerary('Synced from server');
        }

        currentItineraryRevision = Number(latest.revision || currentItineraryRevision || 1) || 1;
        updateItineraryHeaderMeta();
        updateSyncIndicator('Loaded latest shared version');
    }

    function showSyncConflictBanner(conflictPayload) {
        latestSyncConflict = conflictPayload || null;
        if (!syncConflictBanner) {
            return;
        }

        const revision = Number(conflictPayload?.server_revision || 0) || null;
        syncConflictBanner.innerHTML = `
            <div>⚠ Conflict detected: another collaborator updated this itinerary${revision ? ` (server revision ${revision})` : ''}.</div>
            <div class="sync-conflict-actions">
                <button type="button" class="load-server" id="loadServerVersionBtn">Load Latest Version</button>
                <button type="button" class="retry-local" id="retryLocalSyncBtn">Retry My Changes</button>
            </div>
        `;
        syncConflictBanner.style.display = 'block';

        const loadServerBtn = document.getElementById('loadServerVersionBtn');
        if (loadServerBtn) {
            loadServerBtn.onclick = function () {
                applyServerItineraryVersion(conflictPayload?.latest || {});
                hideSyncConflictBanner();
            };
        }

        const retryLocalBtn = document.getElementById('retryLocalSyncBtn');
        if (retryLocalBtn) {
            retryLocalBtn.onclick = function () {
                const serverRevision = Number(conflictPayload?.server_revision || 0) || null;
                if (serverRevision) {
                    currentItineraryRevision = serverRevision;
                }
                hideSyncConflictBanner();
                syncSavedItineraryToServer('retry-after-conflict');
            };
        }
    }

    async function syncSavedItineraryToServer(reason = 'manual-sync') {
        if (!lastSavedItineraryId || !currentItineraryData) {
            return;
        }

        const itineraryContent = document.getElementById('itinerary-content');
        if (!itineraryContent) {
            return;
        }

        try {
            const response = await authJsonFetch(`/api/itineraries/${lastSavedItineraryId}`, {
                method: 'PUT',
                body: JSON.stringify({
                    destination: document.getElementById('destination')?.value || '',
                    duration: document.getElementById('duration')?.value || '',
                    budget: document.getElementById('budget')?.value || '',
                    purpose: document.getElementById('purpose')?.value || '',
                    preferences: selectedPreferences,
                    itinerary_html: itineraryContent.innerHTML,
                    itinerary_data: currentItineraryData,
                    is_public: true,
                    base_revision: currentItineraryRevision,
                }),
            });

            const payload = await response.json();
            if (response.status === 409 && payload?.code === 'revision_conflict') {
                showSyncConflictBanner(payload);
                return;
            }

            if (!response.ok) {
                throw new Error(payload.error || 'Failed to sync itinerary changes');
            }

            if (payload.revision) {
                currentItineraryRevision = Number(payload.revision) || currentItineraryRevision;
            }

            hideSyncConflictBanner();
            updateSyncIndicator('Synced', new Date().toISOString());
            await pushPresenceHeartbeat('editing', {
                reason,
                revision: currentItineraryRevision,
            });
        } catch (syncError) {
            console.error('Itinerary sync failed:', syncError);
        }
    }

    // Initialize Firebase Auth State Listener
    initAuthStateListener();

    // Initialize Firebase Auth UI
    initFirebaseAuthUI();

    // Initialize dropdown handler
    initDropdownHandler();

    showOfflineBanner(!navigator.onLine);
    try {
        const cached = JSON.parse(localStorage.getItem(getOfflineItineraryKey()) || '{}');
        if (cached && cached.saved_at) {
            updateSyncIndicator('Cached', cached.saved_at);
        }
    } catch (_ignoreCacheError) {
        // Ignore malformed cache values and continue normal flow.
    }

    updateItineraryHeaderMeta();

    ['destination', 'budget', 'duration'].forEach(fieldId => {
        const field = document.getElementById(fieldId);
        if (!field) return;
        field.addEventListener('input', updateItineraryHeaderMeta);
    });

    const purposeField = document.getElementById('purpose');
    if (purposeField) {
        purposeField.addEventListener('change', updateItineraryHeaderMeta);
    }

    if (!navigator.onLine) {
        loadOfflineItineraryIfAvailable();
    }

    window.addEventListener('online', function () {
        showOfflineBanner(false);
        updateSyncIndicator('Back online');
        if (lastSavedItineraryId) {
            syncSavedItineraryToServer('back-online');
            startPresenceHeartbeat();
        }
    });

    window.addEventListener('offline', function () {
        showOfflineBanner(true);
        loadOfflineItineraryIfAvailable();
    });

    document.addEventListener('visibilitychange', function () {
        if (lastSavedItineraryId) {
            pushPresenceHeartbeat(document.hidden ? 'idle' : 'viewing');
        }
    });

    window.addEventListener('beforeunload', function () {
        if (presenceHeartbeatTimer) {
            clearInterval(presenceHeartbeatTimer);
            presenceHeartbeatTimer = null;
        }
    });

    if (syncIndicator) {
        syncIndicator.addEventListener('click', function () {
            if (lastSavedItineraryId) {
                syncSavedItineraryToServer('manual-sync-pill');
            }
        });
    }

    if (eventsCategoryFilter) {
        eventsCategoryFilter.addEventListener('change', function () {
            renderEventsList();
            showDayOnMap(currentMapDay);
        });
    }

    if (toggleEventsLayer) {
        showEventsLayer = toggleEventsLayer.checked;
        toggleEventsLayer.addEventListener('change', function () {
            showEventsLayer = toggleEventsLayer.checked;
            showDayOnMap(currentMapDay, { skipNearbyReload: true });
        });
    }

    if (toggleNearbyLayer) {
        showNearbyLayer = toggleNearbyLayer.checked;
        toggleNearbyLayer.addEventListener('change', function () {
            showNearbyLayer = toggleNearbyLayer.checked;
            if (!showNearbyLayer) {
                currentNearbyPlaces = [];
                nearbyRequestSignature = '';
                showDayOnMap(currentMapDay, { skipNearbyReload: true });
                return;
            }

            loadNearbyFeed(currentMapDay, true);
        });
    }

    document.querySelectorAll('.nearby-type-input').forEach(input => {
        input.addEventListener('change', function () {
            if (!showNearbyLayer) return;
            nearbyRequestSignature = '';
            loadNearbyFeed(currentMapDay, true);
        });
    });

    if (refreshNearbyBtn) {
        refreshNearbyBtn.addEventListener('click', function () {
            if (!showNearbyLayer) {
                alert('Enable the Nearby layer to refresh discovery spots.');
                return;
            }
            nearbyRequestSignature = '';
            loadNearbyFeed(currentMapDay, true);
        });
    }

    // Check if step1 exists before running step-related code
    if (document.getElementById("step1")) {
        // Function to show a specific step
        function showStep(step) {
            if (step < 1 || step > totalSteps) return; // Ensure step is within valid range

            const stepElement = document.getElementById(`step${step}`);
            if (!stepElement) {
                console.error(`Step ${step} does not exist in the DOM.`);
                return;
            }

            document.querySelectorAll(".step").forEach(s => s.style.display = "none");
            stepElement.style.display = "block";
        }

        // Function to move to the next step
        window.nextStep = function () {
            if (currentStep < totalSteps) {
                currentStep++;
                showStep(currentStep);
            }
        };

        // Function to move to the previous step
        window.prevStep = function () {
            if (currentStep > 1) {
                currentStep--;
                showStep(currentStep);
            }
        };

        // Show the first step initially
        showStep(currentStep);
    }

    // Handle preference button clicks
    document.querySelectorAll(".preference-btn").forEach(button => {
        button.addEventListener("click", function () {
            const value = this.getAttribute("data-value");
            this.classList.toggle("selected"); // Toggle the selected class
            if (selectedPreferences.includes(value)) {
                selectedPreferences = selectedPreferences.filter(item => item !== value);
            } else {
                selectedPreferences.push(value);
            }
            updateItineraryHeaderMeta();
        });
    });

    // Function to fetch weather for a given city
    function fetchWeather(city) {
        fetch(`/get-weather?city=${encodeURIComponent(city)}`)
            .then(response => response.json())
            .then(data => {
                if (data.error) {
                    console.error("Weather API Error:", data.error);
                    return;
                }

                const weatherEl = document.getElementById("weather-info");
                if (weatherEl) {
                    weatherEl.innerHTML = `
                        <p><strong>Weather in ${data.city}:</strong></p>
                        <p>🌡 Temperature: ${data.temperature}°C</p>
                        <p>🌤 Condition: ${data.description}</p>
                        <p>💧 Humidity: ${data.humidity}%</p>
                        <p>💨 Wind Speed: ${data.wind_speed} m/s</p>
                    `;
                }
            })
            .catch(error => console.error("Error fetching weather:", error));
    }

    async function loadTravelPriceHints(destination) {
        if (!priceHintsBar || !destination) return;

        try {
            const duration = document.getElementById('duration')?.value || '3';
            const response = await fetch(
                `/api/travel-price-hints?destination=${encodeURIComponent(destination)}&duration=${encodeURIComponent(duration)}&currency=USD`
            );
            const data = await response.json();
            if (!response.ok) {
                throw new Error(data.error || 'Failed to load price hints');
            }

            const isLive = String(data.source || '').startsWith('live-');
            const quotedAt = data.quoted_at ? new Date(data.quoted_at).toLocaleString() : null;
            const flightFrom = Number(data.flight_from || 0).toFixed(0);
            const hotelNightly = Number(data.hotel_from_per_night || 0).toFixed(0);
            const hotelTotal = Number(data.hotel_estimated_total || 0).toFixed(0);

            priceHintsBar.innerHTML = `
                <div class="price-hint-pill ${isLive ? 'live' : 'fallback'}">
                    ${isLive ? '🟢 Live' : '🟠 Estimated'} · ${String(data.currency || 'USD').toUpperCase()}
                    ${quotedAt ? `<span class="price-quoted-at">Updated ${quotedAt}</span>` : ''}
                </div>
                <div class="price-hint-pill">✈ Flights from ~$${flightFrom} <a href="${data.flight_link}" target="_blank" rel="noopener noreferrer">Book</a></div>
                <div class="price-hint-pill">🏨 Hotels from ~$${hotelNightly}/night (≈$${hotelTotal} stay) <a href="${data.hotel_link}" target="_blank" rel="noopener noreferrer">Book</a></div>
                <div class="price-hint-pill meta">ℹ ${data.note || 'Indicative price hints only.'}</div>
            `;
            priceHintsBar.style.display = 'flex';
        } catch (error) {
            console.error('Price hints error:', error);
            priceHintsBar.style.display = 'none';
        }
    }

    async function loadEventsFeed(destination) {
        if (!eventsPanel || !eventsList || !destination) return;

        try {
            const params = new URLSearchParams({ destination });
            const response = await fetch(`/api/events-feed?${params.toString()}`);
            const payload = await response.json();
            if (!response.ok) {
                throw new Error(payload.error || 'Failed to load events');
            }

            currentEvents = Array.isArray(payload.events) ? payload.events : [];
            renderEventsList();
            eventsPanel.style.display = currentEvents.length ? 'block' : 'none';
            if (itineraryMap && currentItineraryData) {
                showDayOnMap(currentMapDay);
            }
        } catch (error) {
            console.error('Events feed error:', error);
            eventsPanel.style.display = 'none';
            currentEvents = [];
        }
    }

    function getFilteredEvents() {
        const category = eventsCategoryFilter?.value || 'all';
        if (category === 'all') {
            return currentEvents;
        }
        return currentEvents.filter(evt => String(evt.category || '').toLowerCase() === category);
    }

    function renderEventsList() {
        if (!eventsList) return;

        const filteredEvents = getFilteredEvents();
        if (!filteredEvents.length) {
            eventsList.innerHTML = '<p style="color:#888; margin:0;">No events available for this category right now.</p>';
            return;
        }

        const dayOptions = Array.isArray(currentItineraryData?.days)
            ? currentItineraryData.days.map(day => `<option value="${day.day}">Day ${day.day}</option>`).join('')
            : '<option value="1">Day 1</option>';

        eventsList.innerHTML = filteredEvents.map((event, idx) => `
            <div class="event-card">
                <h4>${escapeHtml(event.name || 'Event')}</h4>
                <div class="event-meta">${escapeHtml(event.start_time || 'TBD')} · ${escapeHtml(event.venue || 'Venue TBA')}</div>
                <div class="event-meta">Category: ${escapeHtml(event.category || 'other')}${event.price_hint ? ` · ${escapeHtml(event.price_hint)}` : ''}</div>
                ${event.url ? `<div class="event-meta"><a href="${escapeHtml(event.url)}" target="_blank" rel="noopener noreferrer">Open tickets</a></div>` : ''}
                <div class="event-actions">
                    <select id="event-day-select-${idx}">${dayOptions}</select>
                    <button type="button" data-event-index="${idx}" data-event-id="${encodeURIComponent(String(event.id || `event-${idx}`))}" class="event-add-btn">Add</button>
                </div>
            </div>
        `).join('');

        eventsList.querySelectorAll('.event-add-btn').forEach(button => {
            button.addEventListener('click', async function () {
                const eventIndex = parseInt(this.dataset.eventIndex, 10);
                const daySelect = document.getElementById(`event-day-select-${eventIndex}`);
                const dayNumber = parseInt(daySelect?.value || '1', 10);
                const decodedId = decodeURIComponent(String(this.dataset.eventId || ''));
                await addEventToItineraryById(decodedId, dayNumber);
            });
        });
    }

    async function refreshItineraryHtmlFromData() {
        if (!currentItineraryData) return;

        try {
            const response = await fetch('/api/render-itinerary', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ itinerary_data: currentItineraryData })
            });
            const payload = await response.json();
            if (!response.ok) {
                throw new Error(payload.error || 'Failed to re-render itinerary');
            }

            const itineraryContent = document.getElementById('itinerary-content');
            if (itineraryContent && payload.itinerary) {
                itineraryContent.innerHTML = payload.itinerary;
            }

            injectReplanButtons();
            buildItineraryDayTabs();
            updateItineraryHeaderMeta();
            persistOfflineItinerary('Updated');
            if (lastSavedItineraryId) {
                await syncSavedItineraryToServer('update-from-ui');
            }
        } catch (error) {
            console.error('Render itinerary error:', error);
        }
    }

    async function addEventToItinerary(eventIndex) {
        const filteredEvents = getFilteredEvents();
        const event = filteredEvents[eventIndex];
        if (!event) return;

        const daySelect = document.getElementById(`event-day-select-${eventIndex}`);
        const dayNumber = parseInt(daySelect?.value || event.day_suggestion || 1, 10);

        await addEventToItineraryById(String(event.id || ''), dayNumber);
    }

    async function addEventToItineraryById(eventId, preferredDay = null) {
        if (!currentItineraryData || !Array.isArray(currentItineraryData.days)) {
            alert('Generate an itinerary first before adding events.');
            return;
        }

        const event = currentEvents.find(item => String(item.id || '') === String(eventId || ''));
        if (!event) {
            alert('Event is no longer available. Try refreshing events.');
            return;
        }

        const dayNumber = parseInt(preferredDay || event.day_suggestion || 1, 10);

        const targetDay = currentItineraryData.days.find(day => parseInt(day.day, 10) === dayNumber);
        if (!targetDay) {
            alert('Selected day not found in itinerary.');
            return;
        }

        targetDay.places = targetDay.places || [];
        targetDay.places.push({
            name: event.name || 'Local Event',
            time: event.start_time || 'Evening',
            description: event.description || `Attend ${event.name || 'a local event'} at ${event.venue || 'the venue'}.`,
            cost_estimate: event.price_hint || 'Varies',
            lat: event.lat,
            lng: event.lng,
        });

        await refreshItineraryHtmlFromData();
        renderItineraryMap(currentItineraryData);
        highlightReplannedDay(dayNumber);
    }

    async function addNearbyPlaceToItineraryById(placeId, preferredDay = null) {
        if (!currentItineraryData || !Array.isArray(currentItineraryData.days)) {
            alert('Generate an itinerary first before adding nearby places.');
            return;
        }

        const nearbyPlace = currentNearbyPlaces.find(item => String(item.id || '') === String(placeId || ''));
        if (!nearbyPlace) {
            alert('Nearby place is no longer available. Refresh nearby results and try again.');
            return;
        }

        const dayNumber = parseInt(preferredDay || nearbyPlace.day_suggestion || 1, 10);
        const targetDay = currentItineraryData.days.find(day => parseInt(day.day, 10) === dayNumber);
        if (!targetDay) {
            alert('Selected day not found in itinerary.');
            return;
        }

        const labelByType = {
            restaurant: 'Meal stop',
            cafe: 'Coffee break',
            attraction: 'Sightseeing',
        };

        targetDay.places = targetDay.places || [];
        targetDay.places.push({
            name: nearbyPlace.name || 'Nearby Place',
            time: labelByType[nearbyPlace.type] || 'Free time',
            description: nearbyPlace.nearest_stop
                ? `Visit ${nearbyPlace.name || 'this place'} near ${nearbyPlace.nearest_stop}.`
                : `Explore ${nearbyPlace.name || 'this nearby place'}.`,
            cost_estimate: nearbyPlace.type === 'attraction' ? 'Varies' : 'On demand',
            lat: nearbyPlace.lat,
            lng: nearbyPlace.lng,
        });

        await refreshItineraryHtmlFromData();
        renderItineraryMap(currentItineraryData);
        highlightReplannedDay(dayNumber);
    }

    window.addMapEventToItinerary = async function (encodedEventId, dayNumber) {
        const eventId = decodeURIComponent(String(encodedEventId || ''));
        await addEventToItineraryById(eventId, dayNumber);
    };

    window.addNearbyPlaceToItinerary = async function (encodedPlaceId, dayNumber) {
        const placeId = decodeURIComponent(String(encodedPlaceId || ''));
        await addNearbyPlaceToItineraryById(placeId, dayNumber);
    };

    function getJournalDefaultTitle() {
        const destination = (document.getElementById('destination')?.value || '').trim();
        return destination ? `${destination} Trip Journal` : 'My Trip Journal';
    }

    function getJournalDefaultTags() {
        const destination = (document.getElementById('destination')?.value || '').trim();
        return destination ? `${destination}, trip-journal, ai-recap` : 'trip-journal, ai-recap';
    }

    function getJournalDraftKey() {
        if (lastSavedItineraryId) {
            return `itinerary:${lastSavedItineraryId}`;
        }

        const destination = (document.getElementById('destination')?.value || '').trim().toLowerCase();
        if (!destination) {
            return 'destination:general';
        }

        return `destination:${destination.split(/\s+/).filter(Boolean).join('-')}`;
    }

    function showJournalAutosaveInfo(message, tone = 'info') {
        if (!journalAutosaveInfo) return;
        journalAutosaveInfo.textContent = message;
        journalAutosaveInfo.style.display = 'block';
        journalAutosaveInfo.style.background = tone === 'error' ? '#fff1f2' : '#eff6ff';
        journalAutosaveInfo.style.borderColor = tone === 'error' ? '#fecdd3' : '#bfdbfe';
        journalAutosaveInfo.style.color = tone === 'error' ? '#9f1239' : '#1e3a8a';
    }

    function renderJournalMediaList() {
        if (!journalMediaList) return;
        if (!Array.isArray(journalMediaUrls) || !journalMediaUrls.length) {
            journalMediaList.style.display = 'none';
            journalMediaList.innerHTML = '';
            return;
        }

        journalMediaList.innerHTML = journalMediaUrls.map((url, idx) => `
            <span class="journal-media-chip">📷 Image ${idx + 1}</span>
            <a class="journal-media-chip" href="${url}" target="_blank" rel="noopener noreferrer">Open</a>
        `).join('');
        journalMediaList.style.display = 'flex';
    }

    function renderJournalVersionHistory() {
        if (!journalHistoryList) return;
        if (!Array.isArray(journalVersionHistory) || !journalVersionHistory.length) {
            journalHistoryList.style.display = 'none';
            journalHistoryList.innerHTML = '';
            return;
        }

        journalHistoryList.innerHTML = journalVersionHistory.map((version, idx) => {
            const timestamp = version.created_at ? new Date(version.created_at).toLocaleString() : 'Unknown time';
            return `
                <div class="journal-history-item">
                    <span>Version ${journalVersionHistory.length - idx} · ${timestamp}</span>
                    <button type="button" data-version-index="${idx}" class="restore-journal-version-btn">Restore</button>
                </div>
            `;
        }).join('');
        journalHistoryList.style.display = 'block';

        journalHistoryList.querySelectorAll('.restore-journal-version-btn').forEach(btn => {
            btn.addEventListener('click', function () {
                const index = Number(this.dataset.versionIndex || -1);
                if (index < 0 || index >= journalVersionHistory.length) return;
                restoreJournalVersion(index);
            });
        });
    }

    function restoreJournalVersion(index) {
        const version = journalVersionHistory[index];
        if (!version) return;

        if (journalTitleInput) {
            journalTitleInput.value = String(version.title || '').trim();
        }
        if (journalContentInput) {
            journalContentInput.value = String(version.content || '').trim();
        }
        if (journalTagsInput) {
            const tags = Array.isArray(version.tags) ? version.tags.join(', ') : '';
            journalTagsInput.value = tags;
        }
        journalMediaUrls = Array.isArray(version.media_urls) ? version.media_urls : [];
        renderJournalMediaList();
        showJournalAutosaveInfo('Version restored locally. Saving draft...');
        scheduleJournalAutosave();
    }

    async function saveJournalDraft() {
        const user = getCurrentUser();
        if (!user) {
            return;
        }

        const title = (journalTitleInput?.value || '').trim();
        const content = (journalContentInput?.value || '').trim();
        const tags = (journalTagsInput?.value || '')
            .split(',')
            .map(tag => tag.trim())
            .filter(Boolean);

        if (!title && !content && !tags.length && !journalMediaUrls.length) {
            return;
        }

        const payload = {
            draft_key: getJournalDraftKey(),
            itinerary_id: lastSavedItineraryId || undefined,
            destination: (document.getElementById('destination')?.value || '').trim(),
            title,
            content,
            tags,
            media_urls: journalMediaUrls,
        };

        try {
            const response = await authJsonFetch('/api/journal-drafts', {
                method: 'POST',
                body: JSON.stringify(payload),
            });
            const body = await response.json();

            if (!response.ok) {
                throw new Error(body.error || 'Failed to save draft');
            }

            showJournalAutosaveInfo('Draft autosaved.');
            if (body.draft?.updated_at) {
                updateSyncIndicator('Journal draft', body.draft.updated_at);
            }
        } catch (error) {
            console.error('Journal autosave error:', error);
            showJournalAutosaveInfo('Autosave failed. Will retry on next edit.', 'error');
        }
    }

    function scheduleJournalAutosave() {
        if (journalAutosaveTimer) {
            clearTimeout(journalAutosaveTimer);
        }

        journalAutosaveTimer = setTimeout(() => {
            saveJournalDraft();
        }, 1200);
    }

    async function loadLatestJournalDraft() {
        const user = getCurrentUser();
        if (!user) {
            return;
        }

        const params = new URLSearchParams();
        params.set('draft_key', getJournalDraftKey());
        if (lastSavedItineraryId) {
            params.set('itinerary_id', String(lastSavedItineraryId));
        }

        try {
            const response = await authJsonFetch(`/api/journal-drafts/latest?${params.toString()}`, {
                method: 'GET',
                forceJsonHeader: false,
            });
            const body = await response.json();
            if (!response.ok) {
                throw new Error(body.error || 'Failed to load draft');
            }

            const draft = body.draft;
            if (!draft) {
                return;
            }

            if (journalTitleInput && !journalTitleInput.value.trim()) {
                journalTitleInput.value = String(draft.title || '').trim();
            }
            if (journalContentInput && !journalContentInput.value.trim()) {
                journalContentInput.value = String(draft.content || '').trim();
            }
            if (journalTagsInput && !journalTagsInput.value.trim()) {
                const tags = Array.isArray(draft.tags) ? draft.tags.join(', ') : '';
                journalTagsInput.value = tags;
            }

            journalMediaUrls = Array.isArray(draft.media_urls) ? draft.media_urls : [];
            renderJournalMediaList();
            showJournalAutosaveInfo('Loaded your latest journal draft.');
        } catch (error) {
            console.error('Load journal draft error:', error);
        }
    }

    async function loadJournalHistory() {
        const user = getCurrentUser();
        if (!user) {
            showJournalStatus('Log in to view journal version history.', 'warning');
            return;
        }

        const params = new URLSearchParams();
        params.set('draft_key', getJournalDraftKey());
        params.set('limit', '12');
        if (lastSavedItineraryId) {
            params.set('itinerary_id', String(lastSavedItineraryId));
        }

        try {
            const response = await authJsonFetch(`/api/journal-drafts/history?${params.toString()}`, {
                method: 'GET',
                forceJsonHeader: false,
            });
            const body = await response.json();
            if (!response.ok) {
                throw new Error(body.error || 'Failed to load journal history');
            }

            journalVersionHistory = Array.isArray(body.versions) ? body.versions : [];
            renderJournalVersionHistory();
            showJournalAutosaveInfo(`Loaded ${journalVersionHistory.length} historical versions.`);
        } catch (error) {
            console.error('Load journal history error:', error);
            showJournalStatus(error.message || 'Failed to load version history.', 'error');
        }
    }

    async function uploadJournalImageFile(file) {
        const user = getCurrentUser();
        if (!user) {
            showJournalStatus('Log in to upload journal media.', 'warning');
            return;
        }

        if (!file) {
            return;
        }

        try {
            const headers = await getAuthHeaders(false);
            const formData = new FormData();
            formData.append('image', file);

            const response = await fetch('/api/journal-media', {
                method: 'POST',
                headers,
                body: formData,
            });

            const body = await response.json();
            if (!response.ok) {
                throw new Error(body.error || 'Failed to upload image');
            }

            if (body.media_url) {
                journalMediaUrls = [body.media_url, ...journalMediaUrls].slice(0, 12);
                renderJournalMediaList();
                showJournalStatus('Image uploaded and attached to this draft.', 'success');
                scheduleJournalAutosave();
            }
        } catch (error) {
            console.error('Journal media upload error:', error);
            showJournalStatus(error.message || 'Failed to upload image.', 'error');
        }
    }

    function clearJournalStatus() {
        if (!journalStatus) return;
        journalStatus.style.display = 'none';
        journalStatus.textContent = '';
        journalStatus.className = 'journal-status';
    }

    function showJournalStatus(message, type = 'success') {
        if (!journalStatus) return;
        journalStatus.textContent = message;
        journalStatus.className = `journal-status ${type}`;
        journalStatus.style.display = 'block';
    }

    function renderJournalHighlights(highlights) {
        if (!journalHighlights) return;

        if (!Array.isArray(highlights) || highlights.length === 0) {
            journalHighlights.style.display = 'none';
            journalHighlights.innerHTML = '';
            return;
        }

        journalHighlights.innerHTML = '';
        const heading = document.createElement('h4');
        heading.textContent = 'Highlights';
        const list = document.createElement('ul');

        highlights.forEach(item => {
            const text = String(item || '').trim();
            if (!text) return;
            const li = document.createElement('li');
            li.textContent = text;
            list.appendChild(li);
        });

        if (!list.children.length) {
            journalHighlights.style.display = 'none';
            return;
        }

        journalHighlights.appendChild(heading);
        journalHighlights.appendChild(list);
        journalHighlights.style.display = 'block';
    }

    function openJournalPanel() {
        if (!journalPanel) return;
        if (!currentItineraryData || !Array.isArray(currentItineraryData.days) || !currentItineraryData.days.length) {
            alert('Generate an itinerary first before creating a trip journal.');
            return;
        }

        journalPanel.style.display = 'block';
        journalPanel.scrollIntoView({ behavior: 'smooth', block: 'start' });

        if (journalTitleInput && !journalTitleInput.value.trim()) {
            journalTitleInput.value = getJournalDefaultTitle();
        }
        if (journalTagsInput && !journalTagsInput.value.trim()) {
            journalTagsInput.value = getJournalDefaultTags();
        }

        if (journalHistoryList) {
            journalHistoryList.style.display = 'none';
        }
        renderJournalMediaList();
        loadLatestJournalDraft();
    }

    function closeJournalPanel() {
        if (!journalPanel) return;
        journalPanel.style.display = 'none';
    }

    async function generateTripJournalRecap() {
        if (!currentItineraryData || !Array.isArray(currentItineraryData.days) || !currentItineraryData.days.length) {
            alert('Generate an itinerary first before creating a trip journal.');
            return;
        }

        if (journalPanel && journalPanel.style.display === 'none') {
            openJournalPanel();
        }

        const btnLabel = generateJournalBtn?.textContent || 'Generate Recap';
        if (generateJournalBtn) {
            generateJournalBtn.disabled = true;
            generateJournalBtn.textContent = 'Generating...';
        }

        clearJournalStatus();

        try {
            const destination = (document.getElementById('destination')?.value || currentItineraryData.destination || '').trim();
            const purpose = (document.getElementById('purpose')?.value || '').trim();
            const tone = journalTone?.value || 'vivid';

            const response = await fetch('/api/generate-trip-journal', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    itinerary_data: currentItineraryData,
                    destination,
                    purpose,
                    tone,
                    max_words: 280,
                }),
            });

            const payload = await response.json();
            if (!response.ok) {
                throw new Error(payload.error || 'Failed to generate trip journal recap');
            }

            const journal = payload.journal || {};
            latestJournal = journal;

            if (journalTitleInput) {
                journalTitleInput.value = String(journal.title || getJournalDefaultTitle()).trim();
            }
            if (journalContentInput) {
                journalContentInput.value = String(journal.recap || '').trim();
            }
            if (journalTagsInput && !journalTagsInput.value.trim()) {
                journalTagsInput.value = getJournalDefaultTags();
            }

            renderJournalHighlights(journal.highlights);

            if (payload.source === 'fallback') {
                showJournalStatus(payload.warning || 'AI recap unavailable. A local recap draft is ready.', 'warning');
            } else {
                showJournalStatus('Recap ready. Edit if needed, then publish to blog.', 'success');
            }

            scheduleJournalAutosave();
        } catch (error) {
            showJournalStatus(error.message || 'Failed to generate trip journal recap.', 'error');
        } finally {
            if (generateJournalBtn) {
                generateJournalBtn.disabled = false;
                generateJournalBtn.textContent = btnLabel;
            }
        }
    }

    async function publishTripJournalToBlog() {
        const user = getCurrentUser();
        if (!user) {
            alert('Please log in to publish your journal to the blog.');
            return;
        }

        const title = (journalTitleInput?.value || '').trim();
        const content = (journalContentInput?.value || '').trim();
        if (!title || !content) {
            showJournalStatus('Title and recap content are required before publishing.', 'error');
            return;
        }

        const btnLabel = publishJournalBtn?.textContent || 'Publish to Blog';
        if (publishJournalBtn) {
            publishJournalBtn.disabled = true;
            publishJournalBtn.textContent = 'Publishing...';
        }

        try {
            const destination = (document.getElementById('destination')?.value || currentItineraryData?.destination || '').trim();
            const tags = (journalTagsInput?.value || '')
                .split(',')
                .map(tag => tag.trim())
                .filter(Boolean);

            const payload = {
                title,
                content,
                destination,
                location: destination,
                category: 'travel-journal',
                tags,
                media_urls: journalMediaUrls,
            };

            if (Array.isArray(journalMediaUrls) && journalMediaUrls.length > 0) {
                payload.image = journalMediaUrls[0];
            }

            if (lastSavedItineraryId) {
                payload.itinerary_id = lastSavedItineraryId;
            }

            const response = await authJsonFetch('/api/publish-trip-journal', {
                method: 'POST',
                body: JSON.stringify(payload),
            });

            const body = await response.json();
            if (!response.ok) {
                throw new Error(body.error || 'Failed to publish trip journal');
            }

            showJournalStatus('Journal published to blog successfully.', 'success');

            if (body.blog_url) {
                try {
                    await navigator.clipboard.writeText(body.blog_url);
                } catch (_clipError) {
                    // Clipboard permissions may be blocked in some browsers.
                }

                const openPost = window.confirm(`Trip journal published. Open it now?\n\n${body.blog_url}`);
                if (openPost) {
                    window.open(body.blog_url, '_blank', 'noopener');
                }
            }
        } catch (error) {
            showJournalStatus(error.message || 'Failed to publish trip journal.', 'error');
        } finally {
            if (publishJournalBtn) {
                publishJournalBtn.disabled = false;
                publishJournalBtn.textContent = btnLabel;
            }
        }
    }

    if (journalBtn) {
        journalBtn.addEventListener('click', openJournalPanel);
    }

    if (closeJournalBtn) {
        closeJournalBtn.addEventListener('click', closeJournalPanel);
    }

    if (generateJournalBtn) {
        generateJournalBtn.addEventListener('click', generateTripJournalRecap);
    }

    if (publishJournalBtn) {
        publishJournalBtn.addEventListener('click', publishTripJournalToBlog);
    }

    if (loadJournalHistoryBtn) {
        loadJournalHistoryBtn.addEventListener('click', loadJournalHistory);
    }

    if (uploadJournalImageBtn && journalImageInput) {
        uploadJournalImageBtn.addEventListener('click', function () {
            journalImageInput.click();
        });

        journalImageInput.addEventListener('change', function (event) {
            const file = event.target.files && event.target.files[0];
            if (file) {
                uploadJournalImageFile(file);
            }
            journalImageInput.value = '';
        });
    }

    [journalTitleInput, journalTagsInput, journalContentInput].forEach(field => {
        if (!field) return;
        field.addEventListener('input', scheduleJournalAutosave);
    });

    // ============================================
    // GENERATE ITINERARY (Updated with Map + Data)
    // ============================================
    const generateBtn = document.getElementById("generateBtn");
    if (generateBtn) {
        generateBtn.addEventListener("click", function () {
            let destination = document.getElementById("destination").value;
            let budget = document.getElementById("budget").value;
            let duration = document.getElementById("duration").value;
            let purpose = document.getElementById("purpose").value;

            updateItineraryHeaderMeta();

            if (!destination || !budget || !duration || !purpose) {
                alert("Please fill out all fields before generating the itinerary.");
                return;
            }

            if (!Array.isArray(selectedPreferences) || selectedPreferences.length === 0) {
                const itineraryContent = document.getElementById("itinerary-content");
                const itinerarySection = document.getElementById("itinerary");
                if (itinerarySection) {
                    itinerarySection.style.display = "block";
                    itinerarySection.scrollIntoView({ behavior: 'smooth', block: 'start' });
                }
                if (itineraryContent) {
                    renderItineraryErrorState(
                        'Choose at least one preference',
                        'Pick one or more interests before generating your itinerary.',
                        'Tip: use the Step 5 chips like Hiking, Museums, or Food Tours.'
                    );
                }
                return;
            }

            const itineraryContent = document.getElementById("itinerary-content");
            const itinerarySection = document.getElementById("itinerary");

            if (itineraryContent && itinerarySection) {
                itineraryContent.innerHTML = `
                    <div style="text-align: center; padding: 40px;">
                        <div style="width: 50px; height: 50px; border: 4px solid #f0f0f0; border-top-color: #ff7f50; border-radius: 50%; animation: spin 0.8s linear infinite; margin: 0 auto 16px;"></div>
                        <p style="color: #888; font-size: 1.1rem;">✨ Our AI is crafting your perfect itinerary...</p>
                        <p style="color: #aaa; font-size: 0.9rem;">This usually takes 10-20 seconds</p>
                    </div>
                `;
                itinerarySection.style.display = "block";
                itinerarySection.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }

            fetch("/generate-itinerary", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ destination, budget, duration, purpose, preferences: selectedPreferences })
            })
            .then(response => {
                if (!response.ok) {
                    return response.json().then(errorData => {
                        throw new Error(errorData.error || "Network response was not ok");
                    });
                }
                return response.json();
            })
            .then(data => {
                if (itineraryContent) {
                    itineraryContent.innerHTML = data.itinerary;
                    buildItineraryDayTabs();
                }
                updateItineraryHeaderMeta();

                // Store structured data for map/export features
                if (data.itinerary_data) {
                    currentItineraryData = data.itinerary_data;
                    lastSavedItineraryId = null;
                    currentItineraryRevision = 1;
                    latestJournal = null;
                    journalMediaUrls = [];
                    journalVersionHistory = [];
                    hideSyncConflictBanner();
                    renderPresenceStrip([]);
                    if (presenceHeartbeatTimer) {
                        clearInterval(presenceHeartbeatTimer);
                        presenceHeartbeatTimer = null;
                    }
                    renderItineraryMap(currentItineraryData);
                    injectReplanButtons();
                    buildItineraryDayTabs();
                    updateItineraryHeaderMeta();
                    persistOfflineItinerary('Generated');

                    if (journalTitleInput) {
                        journalTitleInput.value = getJournalDefaultTitle();
                    }
                    if (journalContentInput) {
                        journalContentInput.value = '';
                    }
                    if (journalTagsInput) {
                        journalTagsInput.value = getJournalDefaultTags();
                    }
                    if (journalAutosaveInfo) {
                        journalAutosaveInfo.style.display = 'none';
                    }
                    if (journalHistoryList) {
                        journalHistoryList.style.display = 'none';
                        journalHistoryList.innerHTML = '';
                    }
                    renderJournalMediaList();
                    renderJournalHighlights([]);
                    clearJournalStatus();
                }

                // Fetch weather for destination
                fetchWeather(destination);
                loadTravelPriceHints(destination);
                loadEventsFeed(destination);
            })
            .catch(error => {
                console.error("Error:", error);
                if (itineraryContent) {
                    const errorMessage = error.message;
                    if (errorMessage.includes("quota") || errorMessage.includes("limit") || errorMessage.includes("429")) {
                        renderItineraryErrorState(
                            'Rate limit reached',
                            'Your Gemini key is valid, but the current quota is exhausted. Try again later or add billing in Google AI Studio.',
                            errorMessage
                        );
                    } else {
                        renderItineraryErrorState(
                            "Couldn't generate your itinerary",
                            'We hit an issue while creating your plan. Please retry in a few moments.',
                            errorMessage
                        );
                    }
                }
            });
        });
    }

    // ============================================
    // INTERACTIVE MAP (Leaflet.js)
    // ============================================
    function normalizeCoordinate(value) {
        const numeric = Number(value);
        return Number.isFinite(numeric) ? numeric : null;
    }

    function getStopsForNearby(dayNum) {
        if (!currentItineraryData || !Array.isArray(currentItineraryData.days)) {
            return [];
        }

        const parsedDay = dayNum === 'all' ? 'all' : parseInt(dayNum, 10);
        const normalizedDayNum = parsedDay === 'all' || Number.isFinite(parsedDay) ? parsedDay : 'all';
        const daysToInspect = normalizedDayNum === 'all'
            ? currentItineraryData.days
            : currentItineraryData.days.filter(day => parseInt(day.day, 10) === normalizedDayNum);

        const seen = new Set();
        const stops = [];

        daysToInspect.forEach(day => {
            const dayNumber = parseInt(day.day, 10) || 1;
            (day.places || []).forEach(place => {
                const lat = normalizeCoordinate(place.lat);
                const lng = normalizeCoordinate(place.lng);
                if (lat === null || lng === null) {
                    return;
                }

                const dedupeKey = `${lat.toFixed(4)}:${lng.toFixed(4)}:${dayNumber}`;
                if (seen.has(dedupeKey)) {
                    return;
                }
                seen.add(dedupeKey);

                stops.push({
                    lat,
                    lng,
                    day: dayNumber,
                    name: String(place.name || '').trim() || `Day ${dayNumber} stop`,
                });
            });
        });

        return stops.slice(0, 6);
    }

    async function loadNearbyFeed(dayNum = currentMapDay, forceRefresh = false) {
        if (!itineraryMap || !currentItineraryData || !showNearbyLayer) {
            return;
        }

        const selectedTypes = getSelectedNearbyTypes();
        const stops = getStopsForNearby(dayNum);
        if (!stops.length) {
            currentNearbyPlaces = [];
            nearbyRequestSignature = '';
            showDayOnMap(dayNum, { skipNearbyReload: true });
            return;
        }

        const signature = [
            dayNum,
            selectedTypes.join(','),
            stops.map(stop => `${stop.day}-${stop.lat.toFixed(3)}-${stop.lng.toFixed(3)}`).join('|'),
        ].join('::');

        if (!forceRefresh && signature === nearbyRequestSignature) {
            return;
        }

        nearbyRequestSignature = signature;

        try {
            const aggregated = [];
            const seen = new Set();
            const requests = stops.map(async stop => {
                const params = new URLSearchParams({
                    lat: stop.lat.toString(),
                    lng: stop.lng.toString(),
                    radius: '1800',
                    limit: '8',
                    types: selectedTypes.join(','),
                });

                const response = await fetch(`/api/nearby-feed?${params.toString()}`);
                const payload = await response.json();
                if (!response.ok) {
                    return;
                }

                const places = Array.isArray(payload.places) ? payload.places : [];
                places.forEach((place, index) => {
                    const placeLat = normalizeCoordinate(place.lat);
                    const placeLng = normalizeCoordinate(place.lng);
                    if (placeLat === null || placeLng === null) {
                        return;
                    }

                    const normalizedId = String(place.id || `nearby-${stop.day}-${index}`);
                    const dedupeKey = `${normalizedId}:${stop.day}`;
                    if (seen.has(dedupeKey)) {
                        return;
                    }
                    seen.add(dedupeKey);

                    aggregated.push({
                        id: normalizedId,
                        name: place.name || 'Nearby Place',
                        type: String(place.type || 'attraction').toLowerCase(),
                        lat: placeLat,
                        lng: placeLng,
                        distance_m: Number(place.distance_m || 0),
                        day_suggestion: stop.day,
                        nearest_stop: stop.name,
                        source: place.source || payload.source || 'fallback',
                        url: place.url || '',
                    });
                });
            });

            await Promise.all(requests);
            aggregated.sort((a, b) => a.distance_m - b.distance_m);
            currentNearbyPlaces = aggregated.slice(0, 24);
            showDayOnMap(dayNum, { skipNearbyReload: true });
        } catch (nearbyError) {
            console.error('Nearby feed error:', nearbyError);
            currentNearbyPlaces = [];
            showDayOnMap(dayNum, { skipNearbyReload: true });
        }
    }

    function renderItineraryMap(data) {
        const mapSection = document.getElementById("mapSection");
        const mapContainer = document.getElementById("itineraryMap");
        const dayFilterBar = document.getElementById("dayFilterBar");

        if (!mapSection || !mapContainer || !data || !data.days) return;

        mapSection.style.display = "block";

        if (itineraryMap) {
            itineraryMap.remove();
        }

        itineraryMap = L.map('itineraryMap', {
            scrollWheelZoom: true,
            zoomControl: true
        }).setView([0, 0], 2);

        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
            maxZoom: 18,
        }).addTo(itineraryMap);

        dayFilterBar.innerHTML = '';
        const allBtn = document.createElement('button');
        allBtn.className = 'day-filter-btn active';
        allBtn.textContent = 'All Days';
        allBtn.addEventListener('click', () => showDayOnMap('all'));
        dayFilterBar.appendChild(allBtn);

        data.days.forEach(day => {
            const btn = document.createElement('button');
            btn.className = 'day-filter-btn';
            btn.textContent = `Day ${day.day}`;
            btn.dataset.day = day.day;
            btn.addEventListener('click', () => showDayOnMap(day.day));
            dayFilterBar.appendChild(btn);
        });

        const initialDay = currentMapDay === 'all' ? 'all' : parseInt(currentMapDay, 10);
        showDayOnMap(Number.isFinite(initialDay) ? initialDay : 'all');

        setTimeout(() => {
            itineraryMap.invalidateSize();
        }, 300);
    }

    function showDayOnMap(dayNum, options = {}) {
        if (!itineraryMap || !currentItineraryData) return;

        const parsedDay = dayNum === 'all' ? 'all' : parseInt(dayNum, 10);
        const normalizedDayNum = parsedDay === 'all' || Number.isFinite(parsedDay) ? parsedDay : 'all';
        currentMapDay = normalizedDayNum;

        document.querySelectorAll('.day-filter-btn').forEach(btn => {
            btn.classList.remove('active');
            if ((normalizedDayNum === 'all' && btn.textContent === 'All Days') ||
                (btn.dataset.day && parseInt(btn.dataset.day, 10) === normalizedDayNum)) {
                btn.classList.add('active');
            }
        });

        mapMarkers.forEach(marker => marker.remove());
        eventMarkers.forEach(marker => marker.remove());
        nearbyMarkers.forEach(marker => marker.remove());
        mapPolylines.forEach(polyline => polyline.remove());
        mapMarkers = [];
        eventMarkers = [];
        nearbyMarkers = [];
        mapPolylines = [];

        const bounds = [];
        const dayColors = ['#e74c3c', '#3498db', '#2ecc71', '#9b59b6', '#f39c12', '#1abc9c', '#e67e22', '#34495e', '#e91e63', '#00bcd4'];

        const daysToShow = normalizedDayNum === 'all'
            ? currentItineraryData.days
            : currentItineraryData.days.filter(day => parseInt(day.day, 10) === normalizedDayNum);

        daysToShow.forEach((day, dayIndex) => {
            const color = dayColors[dayIndex % dayColors.length];
            const dayPoints = [];

            (day.places || []).forEach((place, placeIndex) => {
                const lat = normalizeCoordinate(place.lat);
                const lng = normalizeCoordinate(place.lng);
                if (lat === null || lng === null) {
                    return;
                }

                const latlng = [lat, lng];
                bounds.push(latlng);
                dayPoints.push(latlng);

                const markerIcon = L.divIcon({
                    className: 'custom-map-marker',
                    html: `<div style="
                        background: ${color};
                        color: white;
                        width: 30px;
                        height: 30px;
                        border-radius: 50%;
                        display: flex;
                        align-items: center;
                        justify-content: center;
                        font-weight: 700;
                        font-size: 14px;
                        border: 3px solid white;
                        box-shadow: 0 2px 8px rgba(0,0,0,0.3);
                    ">${placeIndex + 1}</div>`,
                    iconSize: [30, 30],
                    iconAnchor: [15, 15],
                    popupAnchor: [0, -18],
                });

                const marker = L.marker(latlng, { icon: markerIcon }).addTo(itineraryMap);
                const popupContent = `
                    <div class="map-popup-content">
                        <h4>📍 ${escapeHtml(place.name || 'Stop')}</h4>
                        <p class="popup-time">🕐 ${escapeHtml(place.time || '')}</p>
                        <p>${escapeHtml(place.description || '')}</p>
                        ${place.cost_estimate ? `<p>💰 ${escapeHtml(place.cost_estimate)}</p>` : ''}
                        <p style="color: ${color}; font-weight: 600; margin-top: 4px;">Day ${day.day}</p>
                    </div>
                `;
                marker.bindPopup(popupContent, { maxWidth: 300 });
                mapMarkers.push(marker);
            });

            if (dayPoints.length > 1) {
                const polyline = L.polyline(dayPoints, {
                    color,
                    weight: 3,
                    opacity: 0.7,
                    dashArray: '8, 6',
                    smoothFactor: 1
                }).addTo(itineraryMap);
                mapPolylines.push(polyline);
            }
        });

        if (showEventsLayer) {
            renderEventMarkers(normalizedDayNum, bounds);
        }

        if (showNearbyLayer) {
            renderNearbyMarkers(normalizedDayNum, bounds);
        }

        if (bounds.length > 0) {
            itineraryMap.fitBounds(bounds, { padding: [40, 40], maxZoom: 14 });
        }

        if (!options.skipNearbyReload && showNearbyLayer) {
            loadNearbyFeed(normalizedDayNum, false);
        }
    }

    function renderEventMarkers(dayNum, bounds) {
        if (!itineraryMap || !Array.isArray(currentEvents) || currentEvents.length === 0) {
            return;
        }

        const filteredByCategory = getFilteredEvents();
        filteredByCategory.forEach((event, eventIndex) => {
            const daySuggestion = parseInt(event.day_suggestion, 10) || 1;
            if (dayNum !== 'all' && daySuggestion && daySuggestion !== dayNum) {
                return;
            }

            const lat = normalizeCoordinate(event.lat);
            const lng = normalizeCoordinate(event.lng);
            if (lat === null || lng === null) {
                return;
            }

            const latlng = [lat, lng];
            bounds.push(latlng);

            const icon = L.divIcon({
                className: 'event-map-marker',
                html: `<div style="
                    background: #0ea5e9;
                    color: white;
                    width: 26px;
                    height: 26px;
                    border-radius: 50%;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    border: 2px solid white;
                    box-shadow: 0 2px 8px rgba(0,0,0,0.25);
                    font-size: 13px;
                ">🎫</div>`,
                iconSize: [26, 26],
                iconAnchor: [13, 13],
                popupAnchor: [0, -14],
            });

            const encodedEventId = encodeURIComponent(String(event.id || `event-${eventIndex}`));
            const targetDay = dayNum === 'all' ? daySuggestion : (Number.isFinite(Number(dayNum)) ? Number(dayNum) : daySuggestion);

            const marker = L.marker(latlng, { icon }).addTo(itineraryMap);
            marker.bindPopup(`
                <div class="map-popup-content">
                    <h4>🎟️ ${escapeHtml(event.name || 'Local Event')}</h4>
                    <p>🗓️ ${escapeHtml(event.start_time || 'TBD')}</p>
                    <p>📍 ${escapeHtml(event.venue || 'Venue TBA')}</p>
                    ${event.url ? `<p><a href="${escapeHtml(event.url)}" target="_blank" rel="noopener noreferrer">Open event</a></p>` : ''}
                    <button type="button" class="map-popup-action" onclick="window.addMapEventToItinerary('${encodedEventId}', ${targetDay})">Add to Itinerary</button>
                </div>
            `, { maxWidth: 280 });

            eventMarkers.push(marker);
        });
    }

    function renderNearbyMarkers(dayNum, bounds) {
        if (!itineraryMap || !Array.isArray(currentNearbyPlaces) || currentNearbyPlaces.length === 0) {
            return;
        }

        const typeStyles = {
            restaurant: { color: '#ef4444', emoji: '🍽️', label: 'Restaurant' },
            cafe: { color: '#f59e0b', emoji: '☕', label: 'Cafe' },
            attraction: { color: '#8b5cf6', emoji: '⭐', label: 'Attraction' },
        };

        currentNearbyPlaces.forEach((place, placeIndex) => {
            const placeDay = parseInt(place.day_suggestion, 10) || 1;
            if (dayNum !== 'all' && placeDay !== dayNum) {
                return;
            }

            const lat = normalizeCoordinate(place.lat);
            const lng = normalizeCoordinate(place.lng);
            if (lat === null || lng === null) {
                return;
            }

            const style = typeStyles[place.type] || typeStyles.attraction;
            const latlng = [lat, lng];
            bounds.push(latlng);

            const icon = L.divIcon({
                className: 'nearby-map-marker',
                html: `<div style="
                    background: ${style.color};
                    color: #fff;
                    width: 24px;
                    height: 24px;
                    border-radius: 50%;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    border: 2px solid #fff;
                    box-shadow: 0 2px 8px rgba(0,0,0,0.25);
                    font-size: 12px;
                ">${style.emoji}</div>`,
                iconSize: [24, 24],
                iconAnchor: [12, 12],
                popupAnchor: [0, -12],
            });

            const encodedPlaceId = encodeURIComponent(String(place.id || `nearby-${placeIndex}`));
            const marker = L.marker(latlng, { icon }).addTo(itineraryMap);
            marker.bindPopup(`
                <div class="map-popup-content">
                    <h4>${style.emoji} ${escapeHtml(place.name || 'Nearby Place')}</h4>
                    <p>📌 ${style.label}${place.distance_m ? ` · ${escapeHtml(`${place.distance_m}m`)}` : ''}</p>
                    ${place.nearest_stop ? `<p>Near ${escapeHtml(place.nearest_stop)}</p>` : ''}
                    ${place.url ? `<p><a href="${escapeHtml(place.url)}" target="_blank" rel="noopener noreferrer">Open map</a></p>` : ''}
                    <button type="button" class="map-popup-action" onclick="window.addNearbyPlaceToItinerary('${encodedPlaceId}', ${placeDay})">Add to Itinerary</button>
                </div>
            `, { maxWidth: 280 });

            nearbyMarkers.push(marker);
        });
    }

    function injectReplanButtons() {
        if (!currentItineraryData || !Array.isArray(currentItineraryData.days)) return;

        const dayCards = document.querySelectorAll('.itin-day');
        dayCards.forEach((card, index) => {
            const dayData = currentItineraryData.days[index];
            if (!dayData || card.querySelector('.replan-day-btn')) return;

            const actions = document.createElement('div');
            actions.className = 'itin-day-actions';

            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'replan-day-btn';
            button.textContent = `🔁 Re-Plan Day ${dayData.day}`;
            button.addEventListener('click', () => openReplanModal(dayData.day));

            actions.appendChild(button);
            const titleEl = card.querySelector('.itin-day-title');
            if (titleEl) {
                titleEl.insertAdjacentElement('afterend', actions);
            } else {
                card.insertBefore(actions, card.firstChild);
            }
        });
    }

    function showReplanStatus(message, isError = false) {
        if (!replanStatus) return;
        replanStatus.textContent = message;
        replanStatus.className = `replan-status ${isError ? 'error' : 'success'}`;
        replanStatus.style.display = 'block';
    }

    function openReplanModal(dayNumber) {
        if (!replanModal) return;

        currentDayToReplan = dayNumber;
        if (replanModalTitle) {
            replanModalTitle.textContent = `🔁 Re-Plan Day ${dayNumber}`;
        }
        if (replanInstruction) {
            replanInstruction.value = '';
            replanInstruction.focus();
        }
        if (replanStatus) {
            replanStatus.style.display = 'none';
            replanStatus.textContent = '';
        }

        replanModal.style.display = 'flex';
    }

    function closeReplanModal() {
        if (!replanModal) return;
        replanModal.style.display = 'none';
        currentDayToReplan = null;
    }

    function highlightReplannedDay(dayNumber) {
        if (!currentItineraryData || !Array.isArray(currentItineraryData.days)) return;
        const dayIndex = currentItineraryData.days.findIndex(day => parseInt(day.day) === parseInt(dayNumber));
        if (dayIndex === -1) return;

        const dayCards = document.querySelectorAll('.itin-day');
        const targetCard = dayCards[dayIndex];
        if (!targetCard) return;

        targetCard.classList.add('replanned-flash');
        setTimeout(() => targetCard.classList.remove('replanned-flash'), 1800);
    }

    async function submitDayReplan() {
        if (!currentItineraryData || !currentDayToReplan) {
            showReplanStatus('No itinerary day selected for re-plan.', true);
            return;
        }

        const instruction = (replanInstruction?.value || '').trim();
        if (instruction.length < 5) {
            showReplanStatus('Please provide at least 5 characters describing the change.', true);
            return;
        }

        const submitBtnText = replanSubmitBtn?.textContent || 'Re-Plan Day';
        if (replanSubmitBtn) {
            replanSubmitBtn.disabled = true;
            replanSubmitBtn.textContent = 'Re-planning...';
        }

        try {
            const response = await fetch('/api/replan-day', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    itinerary_data: currentItineraryData,
                    day_number: currentDayToReplan,
                    instruction,
                    destination: document.getElementById('destination')?.value || '',
                    budget: document.getElementById('budget')?.value || '',
                    purpose: document.getElementById('purpose')?.value || '',
                    preferences: selectedPreferences,
                })
            });

            const payload = await response.json();
            if (!response.ok) {
                throw new Error(payload.error || 'Failed to re-plan day');
            }

            currentItineraryData = payload.itinerary_data || currentItineraryData;
            const itineraryContent = document.getElementById('itinerary-content');
            if (itineraryContent && payload.itinerary) {
                itineraryContent.innerHTML = payload.itinerary;
            }

            renderItineraryMap(currentItineraryData);
            injectReplanButtons();
            highlightReplannedDay(payload.day_number || currentDayToReplan);
            persistOfflineItinerary('Replanned');
            if (lastSavedItineraryId) {
                await syncSavedItineraryToServer('day-replan');
            }
            closeReplanModal();
        } catch (error) {
            showReplanStatus(error.message || 'Failed to re-plan day. Please try again.', true);
        } finally {
            if (replanSubmitBtn) {
                replanSubmitBtn.disabled = false;
                replanSubmitBtn.textContent = submitBtnText;
            }
        }
    }

    if (replanCancelBtn) {
        replanCancelBtn.addEventListener('click', closeReplanModal);
    }

    if (replanSubmitBtn) {
        replanSubmitBtn.addEventListener('click', submitDayReplan);
    }

    if (replanInstruction) {
        replanInstruction.addEventListener('keydown', function (event) {
            if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
                submitDayReplan();
            }
        });
    }

    if (replanModal) {
        replanModal.addEventListener('click', function (event) {
            if (event.target === replanModal) {
                closeReplanModal();
            }
        });
    }

    document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape' && replanModal && replanModal.style.display === 'flex') {
            closeReplanModal();
        }
    });

    // ============================================
    // PDF EXPORT (jsPDF + html2canvas)
    // ============================================
    const exportPdfBtn = document.getElementById("exportPdfBtn");
    if (exportPdfBtn) {
        exportPdfBtn.addEventListener("click", async function () {
            const itineraryContent = document.getElementById("itinerary-content");
            if (!itineraryContent || !itineraryContent.innerText.trim()) {
                alert("No itinerary to export.");
                return;
            }

            exportPdfBtn.textContent = "⏳ Generating PDF...";
            exportPdfBtn.disabled = true;

            try {
                const canvas = await html2canvas(itineraryContent, {
                    scale: 2,
                    useCORS: true,
                    logging: false,
                    backgroundColor: '#ffffff'
                });

                const { jsPDF } = window.jspdf;
                const pdf = new jsPDF('p', 'mm', 'a4');
                const pageWidth = pdf.internal.pageSize.getWidth();
                const pageHeight = pdf.internal.pageSize.getHeight();
                const margin = 10;

                // Add header
                pdf.setFontSize(20);
                pdf.setTextColor(255, 127, 80);
                const destination = document.getElementById("destination")?.value || "Trip";
                pdf.text(`ITENARO - ${destination} Itinerary`, margin, 18);

                pdf.setFontSize(10);
                pdf.setTextColor(150, 150, 150);
                pdf.text(`Generated on ${new Date().toLocaleDateString()}`, margin, 25);

                pdf.setDrawColor(255, 127, 80);
                pdf.line(margin, 28, pageWidth - margin, 28);

                // Add itinerary content as image
                const imgData = canvas.toDataURL('image/jpeg', 0.85);
                const imgWidth = pageWidth - (margin * 2);
                const imgHeight = (canvas.height * imgWidth) / canvas.width;

                let yPosition = 32;
                let remainingHeight = imgHeight;
                let sourceY = 0;

                while (remainingHeight > 0) {
                    const availableHeight = pageHeight - yPosition - margin;
                    const sliceHeight = Math.min(remainingHeight, availableHeight);
                    const sliceRatio = sliceHeight / imgHeight;

                    // Create a slice of the canvas
                    const sliceCanvas = document.createElement('canvas');
                    sliceCanvas.width = canvas.width;
                    sliceCanvas.height = canvas.height * sliceRatio;
                    const ctx = sliceCanvas.getContext('2d');
                    ctx.drawImage(canvas, 0, sourceY, canvas.width, sliceCanvas.height, 0, 0, sliceCanvas.width, sliceCanvas.height);

                    const sliceData = sliceCanvas.toDataURL('image/jpeg', 0.85);
                    pdf.addImage(sliceData, 'JPEG', margin, yPosition, imgWidth, sliceHeight);

                    remainingHeight -= sliceHeight;
                    sourceY += sliceCanvas.height;

                    if (remainingHeight > 0) {
                        pdf.addPage();
                        yPosition = margin;
                    }
                }

                pdf.save(`ITENARO_${destination.replace(/\s+/g, '_')}_Itinerary.pdf`);
            } catch (error) {
                console.error("PDF generation error:", error);
                alert("Error generating PDF. Please try again.");
            } finally {
                exportPdfBtn.innerHTML = '<span class="export-icon">📄</span> Export PDF';
                exportPdfBtn.disabled = false;
            }
        });
    }

    // ============================================
    // CALENDAR EXPORT (.ics file)
    // ============================================
    const exportCalendarBtn = document.getElementById("exportCalendarBtn");
    if (exportCalendarBtn) {
        exportCalendarBtn.addEventListener("click", function () {
            if (!currentItineraryData || !currentItineraryData.days) {
                alert("No itinerary data available. Please generate an itinerary first.");
                return;
            }

            const destination = document.getElementById("destination")?.value || "Trip";
            const startDateInput = prompt("Enter your trip start date (YYYY-MM-DD):", new Date().toISOString().split('T')[0]);

            if (!startDateInput) return;

            const startDate = new Date(startDateInput);
            if (isNaN(startDate.getTime())) {
                alert("Invalid date format. Please use YYYY-MM-DD.");
                return;
            }

            let icsContent = [
                'BEGIN:VCALENDAR',
                'VERSION:2.0',
                'PRODID:-//ITENARO//Travel Itinerary//EN',
                'CALSCALE:GREGORIAN',
                'METHOD:PUBLISH',
                `X-WR-CALNAME:${destination} Trip - ITENARO`,
            ];

            currentItineraryData.days.forEach(day => {
                const eventDate = new Date(startDate);
                eventDate.setDate(eventDate.getDate() + day.day - 1);

                const dateStr = eventDate.toISOString().replace(/[-:]/g, '').split('.')[0] + 'Z';
                const endDate = new Date(eventDate);
                endDate.setHours(endDate.getHours() + 12);
                const endDateStr = endDate.toISOString().replace(/[-:]/g, '').split('.')[0] + 'Z';

                const places = day.places.map(p => `• ${p.name} (${p.time || 'TBD'})`).join('\\n');
                const foods = (day.food_recommendations || []).map(f => `🍽️ ${f.name} - ${f.cuisine || ''}`).join('\\n');

                let description = `${day.title || ''}\\n\\nPlaces:\\n${places}`;
                if (foods) description += `\\n\\nFood Recommendations:\\n${foods}`;
                if (day.tips) description += `\\n\\nTips: ${day.tips}`;

                icsContent.push(
                    'BEGIN:VEVENT',
                    `DTSTART:${dateStr}`,
                    `DTEND:${endDateStr}`,
                    `SUMMARY:${day.title || `Day ${day.day} - ${destination}`}`,
                    `DESCRIPTION:${description}`,
                    `LOCATION:${destination}`,
                    `UID:itenaro-${Date.now()}-day${day.day}@itenaro.app`,
                    'END:VEVENT'
                );
            });

            icsContent.push('END:VCALENDAR');

            const blob = new Blob([icsContent.join('\r\n')], { type: 'text/calendar;charset=utf-8' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `ITENARO_${destination.replace(/\s+/g, '_')}_Calendar.ics`;
            a.click();
            URL.revokeObjectURL(url);
        });
    }

    // ============================================
    // SHARE ITINERARY
    // ============================================
    const shareBtn = document.getElementById("shareBtn");
    if (shareBtn) {
        shareBtn.addEventListener("click", function () {
            const itineraryContent = document.getElementById("itinerary-content");
            if (!itineraryContent || !itineraryContent.innerText.trim()) {
                alert("No itinerary to share.");
                return;
            }

            // Try Web Share API first
            if (navigator.share) {
                navigator.share({
                    title: 'My ITENARO Travel Itinerary',
                    text: itineraryContent.innerText.substring(0, 500) + '...',
                    url: window.location.href
                }).catch(err => {
                    // Fallback to download
                    downloadAsText(itineraryContent.innerText);
                });
            } else {
                downloadAsText(itineraryContent.innerText);
            }
        });
    }

    function downloadAsText(text) {
        const blob = new Blob([text], { type: "text/plain" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "ITENARO_itinerary.txt";
        a.click();
        URL.revokeObjectURL(url);
    }

    // ============================================
    // AI PACKING LIST
    // ============================================
    const packingListBtn = document.getElementById("packingListBtn");
    const closePackingBtn = document.getElementById("closePackingBtn");
    const sharePackingBtn = document.getElementById("sharePackingBtn");
    const packingListPanel = document.getElementById("packingListPanel");
    const packingListContent = document.getElementById("packingListContent");
    let currentPackingListData = null;
    let currentPackingCheckedState = {};
    let packingStateSaveTimer = null;

    function getPackingTripKey() {
        const destination = (document.getElementById("destination")?.value || "trip").trim().toLowerCase();
        const duration = (document.getElementById("duration")?.value || "na").trim().toLowerCase();
        const purpose = (document.getElementById("purpose")?.value || "na").trim().toLowerCase();
        return `${destination}|${duration}|${purpose}`;
    }

    function getPackingStorageKey(tripKey) {
        return `packing_${tripKey}`;
    }

    async function loadPackingState(tripKey) {
        const storageKey = getPackingStorageKey(tripKey);
        const localState = JSON.parse(localStorage.getItem(storageKey) || '{}');
        const user = getCurrentUser();

        if (!user) {
            return { checkedState: localState, packingData: null };
        }

        try {
            const response = await authJsonFetch(
                `/api/packing-list-state/${encodeURIComponent(user.uid)}?trip_key=${encodeURIComponent(tripKey)}`,
                { method: 'GET', forceJsonHeader: false }
            );
            const payload = await response.json();
            if (!response.ok) {
                throw new Error(payload.error || 'Failed to load packing state');
            }

            const serverCheckedState = payload.checked_state && typeof payload.checked_state === 'object'
                ? payload.checked_state
                : {};
            const mergedState = { ...localState, ...serverCheckedState };
            localStorage.setItem(storageKey, JSON.stringify(mergedState));

            return {
                checkedState: mergedState,
                packingData: payload.packing_data && typeof payload.packing_data === 'object' ? payload.packing_data : null,
            };
        } catch (error) {
            console.error('Error loading synced packing state:', error);
            return { checkedState: localState, packingData: null };
        }
    }

    async function savePackingState(tripKey, checkedState, packingData = null) {
        const storageKey = getPackingStorageKey(tripKey);
        localStorage.setItem(storageKey, JSON.stringify(checkedState));

        const user = getCurrentUser();
        if (!user) {
            return;
        }

        try {
            await authJsonFetch('/api/packing-list-state', {
                method: 'POST',
                body: JSON.stringify({
                    trip_key: tripKey,
                    checked_state: checkedState,
                    packing_data: packingData,
                }),
            });
        } catch (error) {
            console.error('Error saving synced packing state:', error);
        }
    }

    function schedulePackingStateSave(tripKey) {
        if (packingStateSaveTimer) {
            clearTimeout(packingStateSaveTimer);
        }

        packingStateSaveTimer = setTimeout(() => {
            savePackingState(tripKey, currentPackingCheckedState, currentPackingListData);
        }, 250);
    }

    function buildPackingListShareText(data, checkedState) {
        const destination = document.getElementById("destination")?.value || 'Your Trip';
        const lines = [`ITENARO Packing List - ${destination}`, ''];

        (data.categories || []).forEach((category, catIdx) => {
            lines.push(`${category.icon || '📦'} ${category.name}`);
            (category.items || []).forEach((item, itemIdx) => {
                const itemKey = `${catIdx}_${itemIdx}`;
                const mark = checkedState[itemKey] ? '[x]' : '[ ]';
                const notePart = item.note ? ` (${item.note})` : '';
                lines.push(`  ${mark} ${item.item} x${item.quantity || 1}${notePart}`);
            });
            lines.push('');
        });

        if (Array.isArray(data.pro_tips) && data.pro_tips.length > 0) {
            lines.push('Pro Tips');
            data.pro_tips.forEach((tip, idx) => lines.push(`  ${idx + 1}. ${tip}`));
            lines.push('');
        }

        return lines.join('\n');
    }

    if (packingListBtn) {
        packingListBtn.addEventListener("click", function () {
            const destination = document.getElementById("destination")?.value;
            const duration = document.getElementById("duration")?.value;
            const purpose = document.getElementById("purpose")?.value;

            if (!destination || !duration) {
                alert("Please fill in your destination and duration first.");
                return;
            }

            // Show panel with loading state
            packingListPanel.style.display = "block";
            packingListContent.innerHTML = `
                <div class="packing-loading">
                    <div class="spinner"></div>
                    <p>🧳 AI is preparing your personalized packing list...</p>
                    <p style="font-size: 0.85rem; color: #aaa;">Analyzing weather, activities, and destination...</p>
                </div>
            `;
            packingListPanel.scrollIntoView({ behavior: 'smooth', block: 'start' });

            fetch("/generate-packing-list", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ destination, duration, purpose, preferences: selectedPreferences })
            })
            .then(response => {
                if (!response.ok) {
                    return response.json().then(err => { throw new Error(err.error || "Failed to generate packing list"); });
                }
                return response.json();
            })
            .then(async data => {
                if (data.packing_list) {
                    await renderPackingList(data.packing_list);
                } else {
                    packingListContent.innerHTML = '<p class="packing-placeholder">❌ Could not generate packing list. Please try again.</p>';
                }
            })
            .catch(error => {
                console.error("Packing list error:", error);
                packingListContent.innerHTML = `<p class="packing-placeholder">❌ ${error.message}</p>`;
            });
        });
    }

    if (closePackingBtn) {
        closePackingBtn.addEventListener("click", function () {
            packingListPanel.style.display = "none";
        });
    }

    if (sharePackingBtn) {
        sharePackingBtn.addEventListener("click", async function () {
            if (!currentPackingListData || !Array.isArray(currentPackingListData.categories)) {
                alert("Generate a packing list first.");
                return;
            }

            const text = buildPackingListShareText(currentPackingListData, currentPackingCheckedState);
            const destination = document.getElementById("destination")?.value || 'Trip';

            if (navigator.share) {
                try {
                    await navigator.share({
                        title: `Packing List - ${destination}`,
                        text,
                    });
                    return;
                } catch (shareError) {
                    console.warn('Web Share canceled/unavailable, falling back to download.', shareError);
                }
            }

            const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `ITENARO_${destination.replace(/\s+/g, '_')}_Packing_List.txt`;
            a.click();
            URL.revokeObjectURL(url);
        });
    }

    async function renderPackingList(data) {
        const tripKey = getPackingTripKey();
        const { checkedState, packingData } = await loadPackingState(tripKey);

        const resolvedData = data && Array.isArray(data.categories)
            ? data
            : (packingData && Array.isArray(packingData.categories) ? packingData : data);

        currentPackingListData = resolvedData;
        currentPackingCheckedState = checkedState;

        if (!resolvedData || !Array.isArray(resolvedData.categories)) {
            packingListContent.innerHTML = '<p class="packing-placeholder">❌ Could not render packing list data.</p>';
            return;
        }

        let totalItems = 0;
        let checkedItems = 0;

        let html = '';

        // Categories
        (resolvedData.categories || []).forEach((category, catIdx) => {
            const itemCount = category.items ? category.items.length : 0;
            totalItems += itemCount;

            html += `<div class="packing-category">`;
            html += `<div class="packing-category-header">
                        <span>${category.icon || '📦'}</span>
                        <span>${category.name}</span>
                        <span class="cat-count">${itemCount} items</span>
                     </div>`;
            html += `<div class="packing-items">`;

            (category.items || []).forEach((item, itemIdx) => {
                const itemKey = `${catIdx}_${itemIdx}`;
                const isChecked = currentPackingCheckedState[itemKey] || false;
                if (isChecked) checkedItems++;

                html += `<div class="packing-item ${isChecked ? 'checked' : ''}" data-key="${itemKey}">
                    <input type="checkbox" ${isChecked ? 'checked' : ''} data-key="${itemKey}">
                    <div class="packing-item-info">
                        <span class="packing-item-name">${item.item}</span>
                        ${item.note ? `<span class="packing-item-note">${item.note}</span>` : ''}
                    </div>
                    <span class="packing-item-qty">×${item.quantity || 1}</span>
                </div>`;
            });

            html += `</div></div>`;
        });

        // Pro Tips
        if (resolvedData.pro_tips && resolvedData.pro_tips.length > 0) {
            html += `<div class="packing-pro-tips">
                <h4>💡 Pro Tips</h4>
                <ul>${resolvedData.pro_tips.map(tip => `<li>${tip}</li>`).join('')}</ul>
            </div>`;
        }

        packingListContent.innerHTML = html;

        // Show progress
        const packingProgress = document.getElementById("packingProgress");
        if (packingProgress) {
            packingProgress.style.display = "flex";
            updatePackingProgress(checkedItems, totalItems);
        }

        // Attach checkbox listeners
        packingListContent.querySelectorAll('.packing-item input[type="checkbox"]').forEach(checkbox => {
            checkbox.addEventListener('change', function () {
                const key = this.dataset.key;
                const item = this.closest('.packing-item');

                if (this.checked) {
                    currentPackingCheckedState[key] = true;
                    item.classList.add('checked');
                    checkedItems++;
                } else {
                    delete currentPackingCheckedState[key];
                    item.classList.remove('checked');
                    checkedItems--;
                }

                schedulePackingStateSave(tripKey);
                updatePackingProgress(checkedItems, totalItems);
            });
        });

        schedulePackingStateSave(tripKey);
    }

    function updatePackingProgress(checked, total) {
        const progressFill = document.getElementById("progressFill");
        const progressText = document.getElementById("progressText");
        if (progressFill && progressText) {
            const pct = total > 0 ? Math.round((checked / total) * 100) : 0;
            progressFill.style.width = `${pct}%`;
            progressText.textContent = `${checked} / ${total} items packed (${pct}%)`;
        }
    }

    // ============================================
    // SAVE & SHARE LINK
    // ============================================
    const saveLinkBtn = document.getElementById("saveLinkBtn");
    if (saveLinkBtn) {
        saveLinkBtn.addEventListener("click", async function () {
            const itineraryContent = document.getElementById("itinerary-content");
            if (!itineraryContent || !itineraryContent.innerText.trim()) {
                alert("No itinerary to save. Generate one first.");
                return;
            }

            const user = getCurrentUser();
            if (!user) {
                alert("Please log in to save and share your itinerary.");
                return;
            }

            saveLinkBtn.innerHTML = '<span class="export-icon">⏳</span> Saving...';
            saveLinkBtn.disabled = true;

            try {
                const response = await authJsonFetch("/api/save-itinerary", {
                    method: "POST",
                    body: JSON.stringify({
                        destination: document.getElementById("destination")?.value || '',
                        duration: document.getElementById("duration")?.value || '',
                        budget: document.getElementById("budget")?.value || '',
                        purpose: document.getElementById("purpose")?.value || '',
                        preferences: selectedPreferences,
                        itinerary_html: itineraryContent.innerHTML,
                        itinerary_data: currentItineraryData || {},
                        is_public: true
                    })
                });

                const data = await response.json();
                if (response.ok && data.share_url) {
                    if (data.itinerary_id) {
                        lastSavedItineraryId = data.itinerary_id;
                    }
                    if (data.revision) {
                        currentItineraryRevision = Number(data.revision) || currentItineraryRevision;
                    }
                    hideSyncConflictBanner();
                    startPresenceHeartbeat();
                    await pushPresenceHeartbeat('editing', {
                        reason: 'saved-link',
                        revision: currentItineraryRevision,
                    });
                    persistOfflineItinerary('Saved');
                    // Copy to clipboard
                    try {
                        await navigator.clipboard.writeText(data.share_url);
                        alert(`✅ Itinerary saved!\n\n🔗 Shareable link copied to clipboard:\n${data.share_url}`);
                    } catch (clipErr) {
                        prompt("Shareable link (copy it):", data.share_url);
                    }
                } else {
                    alert("❌ " + (data.error || "Failed to save itinerary"));
                }
            } catch (error) {
                console.error("Save error:", error);
                alert("❌ Failed to save itinerary. Please try again.");
            } finally {
                saveLinkBtn.innerHTML = '<span class="export-icon">💾</span> Save Link';
                saveLinkBtn.disabled = false;
            }
        });
    }

    // ============================================
    // CURRENCY CONVERTER
    // ============================================
    const currencyBtn = document.getElementById("currencyBtn");
    const closeCurrencyBtn = document.getElementById("closeCurrencyBtn");
    const currencyPanel = document.getElementById("currencyPanel");
    let exchangeRates = null;

    async function getExchangeRatesForBase(base = 'USD') {
        const normalizedBase = String(base || 'USD').toUpperCase();
        if (exchangeRatesByBase[normalizedBase]) {
            return exchangeRatesByBase[normalizedBase];
        }

        const response = await fetch(`/api/exchange-rates?base=${encodeURIComponent(normalizedBase)}`);
        const payload = await response.json();
        if (!response.ok || !payload.rates) {
            throw new Error(payload.error || `Failed to load rates for ${normalizedBase}`);
        }

        exchangeRatesByBase[normalizedBase] = payload;
        return payload;
    }

    async function convertAmount(amount, fromCurrency, toCurrency) {
        const source = String(fromCurrency || 'USD').toUpperCase();
        const target = String(toCurrency || 'USD').toUpperCase();
        const safeAmount = Number.isFinite(Number(amount)) ? Number(amount) : 0;

        if (source === target) {
            return safeAmount;
        }

        try {
            const ratesPayload = await getExchangeRatesForBase(source);
            const rate = Number(ratesPayload.rates?.[target]);
            if (!Number.isFinite(rate) || rate <= 0) {
                return safeAmount;
            }
            return safeAmount * rate;
        } catch (_rateError) {
            return safeAmount;
        }
    }

    if (currencyBtn) {
        currencyBtn.addEventListener("click", function () {
            currencyPanel.style.display = "block";
            currencyPanel.scrollIntoView({ behavior: 'smooth', block: 'start' });
            fetchExchangeRates();
        });
    }

    if (closeCurrencyBtn) {
        closeCurrencyBtn.addEventListener("click", function () {
            currencyPanel.style.display = "none";
        });
    }

    async function fetchExchangeRates() {
        const resultDiv = document.getElementById("currencyResult");
        resultDiv.innerHTML = '<span style="color:#aaa;">Loading rates...</span>';

        try {
            exchangeRates = await getExchangeRatesForBase('USD');
            convertCurrency(); // Auto-convert on load
        } catch (error) {
            resultDiv.innerHTML = '<span style="color:#e74c3c;">Failed to load rates</span>';
        }
    }

    function convertCurrency() {
        if (!exchangeRates || !exchangeRates.rates) return;

        const amount = parseFloat(document.getElementById("currencyAmount")?.value || 0);
        const from = document.getElementById("currencyFrom")?.value || "USD";
        const to = document.getElementById("currencyTo")?.value || "EUR";
        const resultDiv = document.getElementById("currencyResult");

        // Convert through USD as base
        const fromRate = exchangeRates.rates[from] || 1;
        const toRate = exchangeRates.rates[to] || 1;
        const converted = (amount / fromRate) * toRate;
        const rate = toRate / fromRate;

        resultDiv.innerHTML = `
            <div>
                <span>${amount.toLocaleString()} ${from} = <strong>${converted.toFixed(2)} ${to}</strong></span>
                <span class="rate-info">1 ${from} = ${rate.toFixed(4)} ${to} ${exchangeRates.note ? '(' + exchangeRates.note + ')' : ''}</span>
            </div>
        `;
    }

    // Live conversion on input change
    ['currencyAmount', 'currencyFrom', 'currencyTo'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.addEventListener('input', convertCurrency);
        if (el) el.addEventListener('change', convertCurrency);
    });

    // Swap button
    const currencySwapBtn = document.getElementById("currencySwapBtn");
    if (currencySwapBtn) {
        currencySwapBtn.addEventListener("click", function () {
            const fromSelect = document.getElementById("currencyFrom");
            const toSelect = document.getElementById("currencyTo");
            const temp = fromSelect.value;
            fromSelect.value = toSelect.value;
            toSelect.value = temp;
            convertCurrency();
        });
    }

    // ============================================
    // BUDGET TRACKER
    // ============================================
    const budgetBtn = document.getElementById("budgetBtn");
    const closeBudgetBtn = document.getElementById("closeBudgetBtn");
    const budgetPanel = document.getElementById("budgetPanel");
    const budgetDisplayCurrencySelect = document.getElementById("budgetDisplayCurrency");
    const expenseCurrencySelect = document.getElementById("expenseCurrency");

    function getBudgetDisplayCurrency() {
        return String(budgetDisplayCurrencySelect?.value || 'USD').toUpperCase();
    }

    async function fetchExpensesFromApi() {
        const user = getCurrentUser();
        if (!user) {
            return { expenses: [], total: 0, by_category: {} };
        }

        const response = await authJsonFetch(`/api/expenses/${encodeURIComponent(user.uid)}`, {
            method: 'GET',
            forceJsonHeader: false,
        });

        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.error || 'Failed to load expenses');
        }

        return data;
    }

    if (budgetBtn) {
        budgetBtn.addEventListener("click", async function () {
            budgetPanel.style.display = "block";
            budgetPanel.scrollIntoView({ behavior: 'smooth', block: 'start' });
            await loadAndRenderBudgetTracker();
        });
    }

    if (closeBudgetBtn) {
        closeBudgetBtn.addEventListener("click", function () {
            budgetPanel.style.display = "none";
        });
    }

    // Add expense button
    const addExpenseBtn = document.getElementById("addExpenseBtn");
    if (addExpenseBtn) {
        addExpenseBtn.addEventListener("click", async function () {
            const user = getCurrentUser();
            if (!user) {
                alert("Please log in to track expenses.");
                return;
            }

            const amount = parseFloat(document.getElementById("expenseAmount")?.value || 0);
            const category = document.getElementById("expenseCategory")?.value || 'other';
            const note = document.getElementById("expenseNote")?.value?.trim() || '';
            const expenseCurrency = String(expenseCurrencySelect?.value || getBudgetDisplayCurrency() || 'USD').toUpperCase();
            const description = note || `${category.charAt(0).toUpperCase() + category.slice(1)} expense`;

            if (!amount || amount <= 0) {
                alert("Please enter a valid amount.");
                return;
            }

            try {
                const response = await authJsonFetch('/api/expenses', {
                    method: 'POST',
                    body: JSON.stringify({
                        category,
                        description,
                        amount,
                        currency: expenseCurrency,
                        date: new Date().toISOString().split('T')[0]
                    })
                });

                const payload = await response.json();
                if (!response.ok) {
                    throw new Error(payload.error || 'Failed to add expense');
                }

                document.getElementById("expenseAmount").value = '';
                document.getElementById("expenseNote").value = '';
                await loadAndRenderBudgetTracker();
                document.getElementById("expenseAmount")?.focus();
            } catch (error) {
                alert(`Could not add expense: ${error.message}`);
            }
        });
    }

    ['expenseAmount', 'expenseNote'].forEach(id => {
        const field = document.getElementById(id);
        if (!field) return;
        field.addEventListener('keydown', function (event) {
            if (event.key === 'Enter') {
                event.preventDefault();
                addExpenseBtn?.click();
            }
        });
    });

    if (budgetDisplayCurrencySelect) {
        budgetDisplayCurrencySelect.addEventListener('change', function () {
            loadAndRenderBudgetTracker();
        });
    }

    async function loadAndRenderBudgetTracker() {
        const expensesList = document.getElementById("expensesList");
        if (expensesList) {
            expensesList.innerHTML = '<p style="text-align:center;color:#888;padding:20px;">Loading expenses...</p>';
        }

        try {
            const data = await fetchExpensesFromApi();
            await renderBudgetTracker(data.expenses || []);
        } catch (error) {
            if (expensesList) {
                expensesList.innerHTML = `<p style="text-align:center;color:#e74c3c;padding:20px;">${error.message}</p>`;
            }
        }
    }

    async function renderBudgetTracker(expenses) {
        const displayCurrency = getBudgetDisplayCurrency();
        const budgetInput = document.getElementById("budget")?.value || '';
        const budgetAmountUsd = parseBudgetInput(budgetInput);
        const budgetAmountConverted = await convertAmount(budgetAmountUsd, 'USD', displayCurrency);

        const normalizedExpenses = await Promise.all((expenses || []).map(async expense => {
            const sourceCurrency = String(expense.currency || 'USD').toUpperCase();
            const sourceAmount = Number(expense.amount || 0);
            const convertedAmount = await convertAmount(sourceAmount, sourceCurrency, displayCurrency);
            return {
                ...expense,
                sourceCurrency,
                sourceAmount,
                convertedAmount,
            };
        }));

        const total = normalizedExpenses.reduce((sum, expense) => sum + expense.convertedAmount, 0);
        const remaining = budgetAmountConverted - total;

        const totalSpent = document.getElementById("budgetTotalSpent");
        const budgetLimit = document.getElementById("budgetLimit");
        const budgetRemaining = document.getElementById("budgetRemaining");

        if (totalSpent) totalSpent.textContent = formatCurrencyValue(total, displayCurrency);
        if (budgetLimit) budgetLimit.textContent = budgetAmountUsd > 0 ? formatCurrencyValue(budgetAmountConverted, displayCurrency) : 'Not set';
        if (budgetRemaining) {
            budgetRemaining.textContent = budgetAmountUsd > 0 ? formatCurrencyValue(remaining, displayCurrency) : '—';
            budgetRemaining.style.color = remaining < 0 ? '#e74c3c' : '#2ecc71';
        }

        const categories = {
            food: 0,
            transport: 0,
            accommodation: 0,
            activities: 0,
            shopping: 0,
            other: 0,
        };

        const dailyTotals = {};
        const catEmojis = { food: '🍽️', transport: '🚗', accommodation: '🏨', activities: '🎭', shopping: '🛍️', other: '📦' };

        normalizedExpenses.forEach(expense => {
            const category = categories.hasOwnProperty(expense.category) ? expense.category : 'other';
            categories[category] += expense.convertedAmount;

            const dateKey = String(expense.date || '').trim() || new Date().toISOString().split('T')[0];
            dailyTotals[dateKey] = (dailyTotals[dateKey] || 0) + expense.convertedAmount;
        });

        if (typeof Chart !== 'undefined') {
            const categoryCtx = document.getElementById("budgetCategoryChart");
            if (categoryCtx) {
                const orderedCategories = ['food', 'transport', 'accommodation', 'activities', 'shopping', 'other'];
                const colorMap = {
                    food: '#f59e0b',
                    transport: '#3b82f6',
                    accommodation: '#ef4444',
                    activities: '#8b5cf6',
                    shopping: '#22c55e',
                    other: '#94a3b8',
                };

                const chartLabels = [];
                const chartValues = [];
                const chartColors = [];

                orderedCategories.forEach(category => {
                    const value = categories[category] || 0;
                    if (value <= 0) return;
                    chartLabels.push(`${catEmojis[category] || '📦'} ${category.charAt(0).toUpperCase() + category.slice(1)}`);
                    chartValues.push(value);
                    chartColors.push(colorMap[category] || '#94a3b8');
                });

                if (!chartValues.length) {
                    chartLabels.push('No expenses yet');
                    chartValues.push(1);
                    chartColors.push('#e5e7eb');
                }

                if (budgetCategoryChart) budgetCategoryChart.destroy();
                budgetCategoryChart = new Chart(categoryCtx, {
                    type: 'doughnut',
                    data: {
                        labels: chartLabels,
                        datasets: [{
                            data: chartValues,
                            backgroundColor: chartColors,
                            borderWidth: 2,
                            borderColor: '#fff'
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: true,
                        cutout: '62%',
                        plugins: {
                            legend: { position: 'bottom', labels: { padding: 14, font: { size: 12 } } },
                            tooltip: {
                                callbacks: {
                                    label: function (context) {
                                        const value = Number(context.parsed || 0);
                                        return `${context.label}: ${formatCurrencyValue(value, displayCurrency)}`;
                                    }
                                }
                            }
                        }
                    }
                });
            }

            const dailyCtx = document.getElementById("budgetDailyChart");
            if (dailyCtx) {
                const sortedDaily = Object.entries(dailyTotals)
                    .sort((a, b) => a[0].localeCompare(b[0]));

                const labels = sortedDaily.length ? sortedDaily.map(([date]) => date) : ['No expenses'];
                const dailySpendValues = sortedDaily.length ? sortedDaily.map(([, amount]) => amount) : [0];

                const datasets = [{
                    type: 'bar',
                    label: `Daily Spend (${displayCurrency})`,
                    data: dailySpendValues,
                    backgroundColor: '#3b82f6',
                    borderRadius: 6,
                    maxBarThickness: 44,
                }];

                if (budgetAmountUsd > 0) {
                    datasets.push({
                        type: 'line',
                        label: `Total Budget (${displayCurrency})`,
                        data: labels.map(() => budgetAmountConverted),
                        borderColor: '#ef4444',
                        borderDash: [7, 6],
                        borderWidth: 2,
                        pointRadius: 0,
                        tension: 0,
                    });
                }

                if (budgetDailyChart) budgetDailyChart.destroy();
                budgetDailyChart = new Chart(dailyCtx, {
                    data: { labels, datasets },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        scales: {
                            x: {
                                grid: { display: false },
                            },
                            y: {
                                beginAtZero: true,
                                ticks: {
                                    callback: function (value) {
                                        return formatCurrencyValue(Number(value), displayCurrency);
                                    }
                                }
                            },
                        },
                        plugins: {
                            legend: { position: 'bottom', labels: { boxWidth: 14 } },
                            tooltip: {
                                callbacks: {
                                    label: function (context) {
                                        return `${context.dataset.label}: ${formatCurrencyValue(Number(context.parsed.y || context.parsed || 0), displayCurrency)}`;
                                    }
                                }
                            }
                        }
                    }
                });
            }
        }

        const expensesList = document.getElementById("expensesList");
        if (expensesList) {
            if (normalizedExpenses.length === 0) {
                expensesList.innerHTML = '<p style="text-align:center;color:#aaa;padding:20px;">No expenses yet. Start tracking!</p>';
            } else {
                expensesList.innerHTML = normalizedExpenses.map(expense => {
                    const category = categories.hasOwnProperty(expense.category) ? expense.category : 'other';
                    const originalAmountLabel = expense.sourceCurrency !== displayCurrency
                        ? ` · ${escapeHtml(formatCurrencyValue(expense.sourceAmount, expense.sourceCurrency))} original`
                        : '';

                    return `
                    <div class="expense-item">
                        <div class="expense-cat-icon expense-cat-${category}">${catEmojis[category] || '📦'}</div>
                        <div class="expense-info">
                            <div class="expense-desc">${escapeHtml(expense.description || 'Expense')}</div>
                            <div class="expense-date">${escapeHtml(expense.date || '')}${originalAmountLabel}</div>
                        </div>
                        <div class="expense-amount">${escapeHtml(formatCurrencyValue(expense.convertedAmount, displayCurrency))}</div>
                        <button class="expense-delete" onclick="deleteExpense(${expense.id})" title="Delete">×</button>
                    </div>
                `;
                }).join('');
            }
        }
    }

    // Make deleteExpense globally available
    window.deleteExpense = async function (id) {
        try {
            const response = await authJsonFetch(`/api/expenses/${id}`, {
                method: 'DELETE',
                forceJsonHeader: false,
            });
            const payload = await response.json();
            if (!response.ok) {
                throw new Error(payload.error || 'Failed to delete expense');
            }
            await loadAndRenderBudgetTracker();
        } catch (error) {
            alert(`Could not delete expense: ${error.message}`);
        }
    };

    // ============================================
    // HEADER SEARCH FUNCTIONALITY
    // ============================================
    const headerSearchInput = document.getElementById("headerSearchInput");
    const headerSearchBtn = document.getElementById("headerSearchBtn");
    if (headerSearchInput && headerSearchBtn) {
        headerSearchBtn.addEventListener("click", function () {
            const query = headerSearchInput.value.trim();
            if (query) {
                window.location.href = `/search?query=${encodeURIComponent(query)}`;
            }
        });
        headerSearchInput.addEventListener("keydown", function (e) {
            if (e.key === "Enter") {
                headerSearchBtn.click();
            }
        });
    }

    // --- Live Search Dropdown ---
    if (headerSearchInput) {
        let searchDropdown = document.createElement('div');
        searchDropdown.id = 'searchDropdown';
        searchDropdown.style.position = 'absolute';
        searchDropdown.style.background = '#fff';
        searchDropdown.style.border = '1px solid #ccc';
        searchDropdown.style.width = '300px';
        searchDropdown.style.zIndex = '2000';
        searchDropdown.style.display = 'none';
        searchDropdown.style.maxHeight = '300px';
        searchDropdown.style.overflowY = 'auto';
        searchDropdown.style.borderRadius = '0 0 8px 8px';
        searchDropdown.style.boxShadow = '0 4px 16px rgba(0,0,0,0.08)';
        document.body.appendChild(searchDropdown);

        headerSearchInput.addEventListener('input', function () {
            const query = this.value.trim();
            if (!query) {
                searchDropdown.style.display = 'none';
                return;
            }
            fetch(`/api/search?query=${encodeURIComponent(query)}`)
                .then(res => res.json())
                .then(results => {
                    if (results.length === 0) {
                        searchDropdown.innerHTML = '<div style="padding:8px;">No results found</div>';
                    } else {
                        searchDropdown.innerHTML = results.map(r =>
                            `<div class="search-result" style="padding:8px;cursor:pointer;" data-url="${r.url}">
                                <b>${r.name}</b> <span style="color:#888;">(${r.type})</span>
                            </div>`
                        ).join('');
                    }
                    const rect = headerSearchInput.getBoundingClientRect();
                    searchDropdown.style.left = rect.left + 'px';
                    searchDropdown.style.top = (rect.bottom + window.scrollY) + 'px';
                    searchDropdown.style.display = 'block';
                })
                .catch(err => console.error('[HeaderSearch] API error:', err));
        });

        document.addEventListener('click', function (e) {
            let resultDiv = e.target.closest('.search-result');
            if (resultDiv) {
                window.location.href = resultDiv.getAttribute('data-url');
            } else if (!headerSearchInput.contains(e.target)) {
                searchDropdown.style.display = 'none';
            }
        });
    }

    // --- Inspiration Pre-fill Logic ---
    function getUrlParams() {
        const params = {};
        window.location.search.replace(/[?&]+([^=&]+)=([^&]*)/gi, function(str,key,value) {
            params[key] = decodeURIComponent(value);
        });
        return params;
    }
    const params = getUrlParams();
    if (params.inspire === '1') {
        if (params.destination && document.getElementById('destination')) {
            document.getElementById('destination').value = params.destination;
        }
    }

    // ============================================
    // FIREBASE AUTHENTICATION FUNCTIONS
    // ============================================
    function initAuthStateListener() {
        onAuthStateChange((user) => {
            if (user) {
                console.log('User is signed in:', user);
                updateUIForUser(user);

                if (window.location.pathname === '/login') {
                    console.log('User already authenticated, redirecting to profile...');
                    window.location.href = '/profile';
                }
            } else {
                console.log('User is signed out');
                updateUIForSignedOut();
            }
        });
    }

    function initFirebaseAuthUI() {
        const loginForm = document.querySelector('.login-form');
        if (loginForm && window.location.pathname === '/login') {
            loginForm.addEventListener('submit', handleLogin);
        }

        const registerForm = document.querySelector('.register-form');
        if (registerForm && window.location.pathname === '/register') {
            registerForm.addEventListener('submit', handleRegister);
        }

        const googleSignInBtns = document.querySelectorAll('.google-signin-btn, .google-btn');
        googleSignInBtns.forEach(btn => {
            btn.addEventListener('click', handleGoogleSignIn);
        });

        const logoutBtns = document.querySelectorAll('.logout-btn, a[href="/logout"]');
        logoutBtns.forEach(btn => {
            btn.addEventListener('click', handleLogout);
        });

        const forgotPasswordForm = document.querySelector('.forgot-password-form');
        if (forgotPasswordForm) {
            forgotPasswordForm.addEventListener('submit', handleForgotPassword);
        }
    }

    async function handleLogin(e) {
        e.preventDefault();
        const email = e.target.querySelector('input[name="username"]').value;
        const password = e.target.querySelector('input[name="password"]').value;

        const result = await signInUser(email, password);
        if (result.success) {
            showMessage('Logged in successfully!', 'success');
            setTimeout(() => { window.location.href = '/profile'; }, 1000);
        } else {
            showMessage(getErrorMessage(result.error), 'error');
        }
    }

    async function handleRegister(e) {
        e.preventDefault();
        const email = e.target.querySelector('input[name="email"]').value;
        const password = e.target.querySelector('input[name="password"]').value;

        const result = await registerUser(email, password);
        if (result.success) {
            showMessage('Registration successful! Please check your email for verification.', 'success');
            setTimeout(() => { window.location.href = '/login'; }, 2000);
        } else {
            showMessage(getErrorMessage(result.error), 'error');
        }
    }

    async function handleGoogleSignIn(e) {
        e.preventDefault();
        const result = await signInWithGoogle();
        if (result.success) {
            showMessage('Signed in with Google successfully!', 'success');
            setTimeout(() => { window.location.href = '/profile'; }, 1000);
        } else {
            showMessage(getErrorMessage(result.error), 'error');
        }
    }

    async function handleLogout(e) {
        e.preventDefault();
        const result = await signOutUser();
        if (result.success) {
            showMessage('Logged out successfully!', 'success');
            setTimeout(() => { window.location.href = '/'; }, 1000);
        } else {
            showMessage('Error signing out', 'error');
        }
    }

    async function handleForgotPassword(e) {
        e.preventDefault();
        const email = e.target.querySelector('input[name="email"]').value;

        const result = await resetPassword(email);
        if (result.success) {
            showMessage('Password reset email sent! Check your inbox.', 'success');
        } else {
            showMessage(getErrorMessage(result.error), 'error');
        }
    }

    // Profile dropdown
    function toggleProfileDropdownLocal() {
        const dropdown = document.querySelector('.profile-dropdown');
        if (dropdown) {
            dropdown.classList.toggle('show');
        }
    }

    document.addEventListener('click', function(event) {
        const dropdown = document.querySelector('.profile-dropdown');
        if (dropdown && !dropdown.contains(event.target)) {
            dropdown.classList.remove('show');
        }
    });

    // Make functions globally available
    window.handleLogin = handleLogin;
    window.handleRegister = handleRegister;
    window.handleGoogleSignIn = handleGoogleSignIn;
    window.handleLogout = handleLogout;
    window.handleForgotPassword = handleForgotPassword;
    window.toggleProfileDropdown = toggleProfileDropdownLocal;
});

