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
    let currentDayToReplan = null;
    let itineraryMap = null; // Leaflet map instance
    let mapMarkers = []; // Store map markers
    let mapPolylines = []; // Store route lines

    const replanModal = document.getElementById("replanModal");
    const replanInstruction = document.getElementById("replanInstruction");
    const replanStatus = document.getElementById("replanStatus");
    const replanModalTitle = document.getElementById("replanModalTitle");
    const replanCancelBtn = document.getElementById("replanCancelBtn");
    const replanSubmitBtn = document.getElementById("replanSubmitBtn");

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

    // Initialize Firebase Auth State Listener
    initAuthStateListener();

    // Initialize Firebase Auth UI
    initFirebaseAuthUI();

    // Initialize dropdown handler
    initDropdownHandler();

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

            if (!destination || !budget || !duration || !purpose) {
                alert("Please fill out all fields before generating the itinerary.");
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
                }

                // Store structured data for map/export features
                if (data.itinerary_data) {
                    currentItineraryData = data.itinerary_data;
                    renderItineraryMap(currentItineraryData);
                    injectReplanButtons();
                }

                // Fetch weather for destination
                fetchWeather(destination);
            })
            .catch(error => {
                console.error("Error:", error);
                if (itineraryContent) {
                    const errorMessage = error.message;
                    if (errorMessage.includes("quota") || errorMessage.includes("limit") || errorMessage.includes("429")) {
                        itineraryContent.innerHTML = `
                            <div style="text-align: center; padding: 30px; background: #fff3cd; border: 1px solid #ffeaa7; border-radius: 12px; margin: 20px 0;">
                                <div style="font-size: 48px; margin-bottom: 15px;">⏰</div>
                                <h3 style="color: #856404; margin-bottom: 15px;">Rate Limit Reached</h3>
                                <p style="color: #856404; margin-bottom: 10px;">We've reached the daily limit for AI-generated itineraries.</p>
                                <p style="color: #856404; font-size: 14px; margin-bottom: 20px;">
                                    <em>This helps us keep the service free for everyone!</em>
                                </p>
                            </div>
                        `;
                    } else {
                        itineraryContent.innerHTML = `
                            <div style="text-align: center; padding: 20px; background: #f8d7da; border: 1px solid #f5c6cb; border-radius: 8px; margin: 20px 0;">
                                <h3 style="color: #721c24;">❌ Error Generating Itinerary</h3>
                                <p style="color: #721c24;">We encountered an issue while creating your itinerary.</p>
                                <p style="color: #721c24; font-size: 14px;">Please try again in a few moments.</p>
                            </div>
                        `;
                    }
                }
            });
        });
    }

    // ============================================
    // INTERACTIVE MAP (Leaflet.js)
    // ============================================
    function renderItineraryMap(data) {
        const mapSection = document.getElementById("mapSection");
        const mapContainer = document.getElementById("itineraryMap");
        const dayFilterBar = document.getElementById("dayFilterBar");

        if (!mapSection || !mapContainer || !data || !data.days) return;

        mapSection.style.display = "block";

        // Initialize map if not already done
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

        // Build day filter buttons
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

        // Show all days initially
        showDayOnMap('all');

        // Force map to redraw (fixes rendering in hidden containers)
        setTimeout(() => {
            itineraryMap.invalidateSize();
        }, 300);
    }

    function showDayOnMap(dayNum) {
        if (!itineraryMap || !currentItineraryData) return;

        // Update filter button states
        document.querySelectorAll('.day-filter-btn').forEach(btn => {
            btn.classList.remove('active');
            if ((dayNum === 'all' && btn.textContent === 'All Days') ||
                (btn.dataset.day && parseInt(btn.dataset.day) === dayNum)) {
                btn.classList.add('active');
            }
        });

        // Clear existing markers and lines
        mapMarkers.forEach(m => m.remove());
        mapPolylines.forEach(p => p.remove());
        mapMarkers = [];
        mapPolylines = [];

        const bounds = [];
        const dayColors = ['#e74c3c', '#3498db', '#2ecc71', '#9b59b6', '#f39c12', '#1abc9c', '#e67e22', '#34495e', '#e91e63', '#00bcd4'];

        const daysToShow = dayNum === 'all'
            ? currentItineraryData.days
            : currentItineraryData.days.filter(d => d.day === dayNum);

        daysToShow.forEach((day, dayIndex) => {
            const color = dayColors[dayIndex % dayColors.length];
            const dayPoints = [];

            day.places.forEach((place, placeIndex) => {
                if (!place.lat || !place.lng) return;

                const latlng = [place.lat, place.lng];
                bounds.push(latlng);
                dayPoints.push(latlng);

                // Create numbered marker
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

                // Popup content
                const popupContent = `
                    <div class="map-popup-content">
                        <h4>📍 ${place.name}</h4>
                        <p class="popup-time">🕐 ${place.time || ''}</p>
                        <p>${place.description || ''}</p>
                        ${place.cost_estimate ? `<p>💰 ${place.cost_estimate}</p>` : ''}
                        <p style="color: ${color}; font-weight: 600; margin-top: 4px;">Day ${day.day}</p>
                    </div>
                `;
                marker.bindPopup(popupContent, { maxWidth: 280 });
                mapMarkers.push(marker);
            });

            // Draw route line for the day
            if (dayPoints.length > 1) {
                const polyline = L.polyline(dayPoints, {
                    color: color,
                    weight: 3,
                    opacity: 0.7,
                    dashArray: '8, 6',
                    smoothFactor: 1
                }).addTo(itineraryMap);
                mapPolylines.push(polyline);
            }
        });

        // Fit map to bounds
        if (bounds.length > 0) {
            itineraryMap.fitBounds(bounds, { padding: [40, 40], maxZoom: 14 });
        }
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
    const packingListPanel = document.getElementById("packingListPanel");
    const packingListContent = document.getElementById("packingListContent");

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
            .then(data => {
                if (data.packing_list) {
                    renderPackingList(data.packing_list);
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

    function renderPackingList(data) {
        const storageKey = `packing_${document.getElementById("destination")?.value || 'trip'}`;
        const savedState = JSON.parse(localStorage.getItem(storageKey) || '{}');
        let totalItems = 0;
        let checkedItems = 0;

        let html = '';

        // Categories
        (data.categories || []).forEach((category, catIdx) => {
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
                const isChecked = savedState[itemKey] || false;
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
        if (data.pro_tips && data.pro_tips.length > 0) {
            html += `<div class="packing-pro-tips">
                <h4>💡 Pro Tips</h4>
                <ul>${data.pro_tips.map(tip => `<li>${tip}</li>`).join('')}</ul>
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
                const savedState = JSON.parse(localStorage.getItem(storageKey) || '{}');

                if (this.checked) {
                    savedState[key] = true;
                    item.classList.add('checked');
                    checkedItems++;
                } else {
                    delete savedState[key];
                    item.classList.remove('checked');
                    checkedItems--;
                }

                localStorage.setItem(storageKey, JSON.stringify(savedState));
                updatePackingProgress(checkedItems, totalItems);
            });
        });
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
            const resp = await fetch("/api/exchange-rates?base=USD");
            exchangeRates = await resp.json();
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
    let budgetChart = null;

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

            const desc = document.getElementById("expenseDesc")?.value?.trim();
            const amount = parseFloat(document.getElementById("expenseAmount")?.value || 0);
            const category = document.getElementById("expenseCategory")?.value || 'other';

            if (!desc || !amount || amount <= 0) {
                alert("Please enter a description and valid amount.");
                return;
            }

            try {
                const response = await authJsonFetch('/api/expenses', {
                    method: 'POST',
                    body: JSON.stringify({
                        category,
                        description: desc,
                        amount,
                        currency: 'USD',
                        date: new Date().toISOString().split('T')[0]
                    })
                });

                const payload = await response.json();
                if (!response.ok) {
                    throw new Error(payload.error || 'Failed to add expense');
                }

                document.getElementById("expenseDesc").value = '';
                document.getElementById("expenseAmount").value = '';
                await loadAndRenderBudgetTracker();
            } catch (error) {
                alert(`Could not add expense: ${error.message}`);
            }
        });
    }

    async function loadAndRenderBudgetTracker() {
        const expensesList = document.getElementById("expensesList");
        if (expensesList) {
            expensesList.innerHTML = '<p style="text-align:center;color:#888;padding:20px;">Loading expenses...</p>';
        }

        try {
            const data = await fetchExpensesFromApi();
            renderBudgetTracker(data.expenses || []);
        } catch (error) {
            if (expensesList) {
                expensesList.innerHTML = `<p style="text-align:center;color:#e74c3c;padding:20px;">${error.message}</p>`;
            }
        }
    }

    function renderBudgetTracker(expenses) {
        const budgetInput = document.getElementById("budget")?.value || '';

        // Parse budget (extract number)
        let budgetAmount = 0;
        const budgetMatch = budgetInput.match(/[\d,]+/);
        if (budgetMatch) {
            budgetAmount = parseFloat(budgetMatch[0].replace(/,/g, ''));
        }

        // Calculate totals
        const total = expenses.reduce((sum, e) => sum + e.amount, 0);
        const remaining = budgetAmount - total;

        // Update summary cards
        const totalSpent = document.getElementById("budgetTotalSpent");
        const budgetLimit = document.getElementById("budgetLimit");
        const budgetRemaining = document.getElementById("budgetRemaining");

        if (totalSpent) totalSpent.textContent = `$${total.toFixed(2)}`;
        if (budgetLimit) budgetLimit.textContent = budgetAmount > 0 ? `$${budgetAmount.toFixed(2)}` : 'Not set';
        if (budgetRemaining) {
            budgetRemaining.textContent = budgetAmount > 0 ? `$${remaining.toFixed(2)}` : '—';
            budgetRemaining.style.color = remaining < 0 ? '#e74c3c' : '#2ecc71';
        }

        // Category breakdown
        const categories = {};
        const catEmojis = { food: '🍽️', transport: '🚗', accommodation: '🏨', activities: '🎭', shopping: '🛍️', other: '📦' };
        expenses.forEach(e => {
            categories[e.category] = (categories[e.category] || 0) + e.amount;
        });

        // Render chart (only if Chart.js is loaded)
        if (typeof Chart !== 'undefined' && Object.keys(categories).length > 0) {
            const ctx = document.getElementById("budgetChart");
            if (ctx) {
                if (budgetChart) budgetChart.destroy();
                budgetChart = new Chart(ctx, {
                    type: 'doughnut',
                    data: {
                        labels: Object.keys(categories).map(k => `${catEmojis[k] || '📦'} ${k.charAt(0).toUpperCase() + k.slice(1)}`),
                        datasets: [{
                            data: Object.values(categories),
                            backgroundColor: ['#ffeaa7', '#dfe6e9', '#fab1a0', '#c3aed6', '#a8e6cf', '#f0f0f0'],
                            borderWidth: 2,
                            borderColor: '#fff'
                        }]
                    },
                    options: {
                        responsive: true,
                        plugins: {
                            legend: { position: 'bottom', labels: { padding: 16, font: { size: 13 } } }
                        }
                    }
                });
            }
        }

        // Render expenses list
        const expensesList = document.getElementById("expensesList");
        if (expensesList) {
            if (expenses.length === 0) {
                expensesList.innerHTML = '<p style="text-align:center;color:#aaa;padding:20px;">No expenses yet. Start tracking!</p>';
            } else {
                expensesList.innerHTML = expenses.slice().reverse().map(e => `
                    <div class="expense-item">
                        <div class="expense-cat-icon expense-cat-${e.category}">${catEmojis[e.category] || '📦'}</div>
                        <div class="expense-info">
                            <div class="expense-desc">${e.description}</div>
                            <div class="expense-date">${e.date}</div>
                        </div>
                        <div class="expense-amount">$${e.amount.toFixed(2)}</div>
                        <button class="expense-delete" onclick="deleteExpense(${e.id})" title="Delete">×</button>
                    </div>
                `).join('');
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

