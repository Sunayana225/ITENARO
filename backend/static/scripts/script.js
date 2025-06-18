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

                document.getElementById("weather-info").innerHTML = `
                    <p><strong>Weather in ${data.city}:</strong></p>
                    <p>🌡 Temperature: ${data.temperature}°C</p>
                    <p>🌤 Condition: ${data.description}</p>
                    <p>💧 Humidity: ${data.humidity}%</p>
                    <p>💨 Wind Speed: ${data.wind_speed} m/s</p>
                `;
            })
            .catch(error => console.error("Error fetching weather:", error));
    }

    // Generate Itinerary
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
                itineraryContent.innerHTML = "<p>Generating itinerary...</p>";
                itinerarySection.style.display = "block";
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

                // Fetch weather for the selected destination
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
                                <div style="background: white; padding: 15px; border-radius: 8px; margin-top: 15px;">
                                    <h4 style="color: #856404; margin-bottom: 10px;">💡 What you can do:</h4>
                                    <ul style="color: #856404; text-align: left; max-width: 300px; margin: 0 auto; list-style: none; padding: 0;">
                                        <li style="margin: 8px 0;">🕐 Wait a few minutes and try again</li>
                                        <li style="margin: 8px 0;">🗺️ Browse our destinations page</li>
                                        <li style="margin: 8px 0;">📝 Check out travel blogs for inspiration</li>
                                    </ul>
                                </div>
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

    // Share Itinerary
    const shareBtn = document.getElementById("shareBtn");
    if (shareBtn) {
        shareBtn.addEventListener("click", function () {
            const itineraryContent = document.getElementById("itinerary-content");
            if (!itineraryContent || !itineraryContent.innerText.trim()) {
                alert("No itinerary to share.");
                return;
            }
            const blob = new Blob([itineraryContent.innerText], { type: "text/plain" });
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = "itinerary.txt";
            a.click();
            URL.revokeObjectURL(url);
        });
    }

    // Header search functionality
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
        console.log('[HeaderSearch] Input event. Query:', query);
        if (!query) {
            searchDropdown.style.display = 'none';
            return;
        }
        fetch(`/api/search?query=${encodeURIComponent(query)}`)
            .then(res => {
                console.log('[HeaderSearch] API response status:', res.status);
                return res.json();
            })
            .then(results => {
                console.log('[HeaderSearch] API results:', results);
                if (results.length === 0) {
                    searchDropdown.innerHTML = '<div style="padding:8px;">No results found</div>';
                } else {
                    searchDropdown.innerHTML = results.map(r =>
                        `<div class="search-result" style="padding:8px;cursor:pointer;" data-url="${r.url}">
                            <b>${r.name}</b> <span style="color:#888;">(${r.type})</span>
                        </div>`
                    ).join('');
                }
                // Position dropdown under input
                const rect = headerSearchInput.getBoundingClientRect();
                searchDropdown.style.left = rect.left + 'px';
                searchDropdown.style.top = (rect.bottom + window.scrollY) + 'px';
                searchDropdown.style.display = 'block';
            })
            .catch(err => {
                console.error('[HeaderSearch] API error:', err);
            });
    });

    document.addEventListener('click', function (e) {
        // Find the closest parent with class 'search-result'
        let resultDiv = e.target.closest('.search-result');
        if (resultDiv) {
            window.location.href = resultDiv.getAttribute('data-url');
        } else if (!headerSearchInput.contains(e.target)) {
            searchDropdown.style.display = 'none';
        }
    });

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
        // You can add more fields here if you want to pre-fill country, state, etc.
    }

    // Firebase Authentication Functions
    function initAuthStateListener() {
        onAuthStateChange((user) => {
            if (user) {
                console.log('User is signed in:', user);
                updateUIForUser(user);

                // If we're on the login page and user is authenticated, redirect to profile
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
        // Login form handler
        const loginForm = document.querySelector('.login-form');
        if (loginForm && window.location.pathname === '/login') {
            loginForm.addEventListener('submit', handleLogin);
        }

        // Register form handler
        const registerForm = document.querySelector('.register-form');
        if (registerForm && window.location.pathname === '/register') {
            registerForm.addEventListener('submit', handleRegister);
        }

        // Google sign-in buttons
        const googleSignInBtns = document.querySelectorAll('.google-signin-btn, .google-btn');
        googleSignInBtns.forEach(btn => {
            btn.addEventListener('click', handleGoogleSignIn);
        });

        // Logout buttons
        const logoutBtns = document.querySelectorAll('.logout-btn, a[href="/logout"]');
        logoutBtns.forEach(btn => {
            btn.addEventListener('click', handleLogout);
        });

        // Forgot password form
        const forgotPasswordForm = document.querySelector('.forgot-password-form');
        if (forgotPasswordForm) {
            forgotPasswordForm.addEventListener('submit', handleForgotPassword);
        }
    }

    async function handleLogin(e) {
        e.preventDefault();
        const email = e.target.querySelector('input[name="username"]').value; // Using username field as email
        const password = e.target.querySelector('input[name="password"]').value;

        const result = await signInUser(email, password);
        if (result.success) {
            console.log('User signed in:', result.user);
            showMessage('Logged in successfully!', 'success');
            // Redirect to profile or home page
            setTimeout(() => {
                window.location.href = '/profile';
            }, 1000);
        } else {
            console.error('Login error:', result.error);
            showMessage(getErrorMessage(result.error), 'error');
        }
    }

    async function handleRegister(e) {
        e.preventDefault();
        const email = e.target.querySelector('input[name="email"]').value;
        const password = e.target.querySelector('input[name="password"]').value;
        const username = e.target.querySelector('input[name="username"]').value;

        const result = await registerUser(email, password);
        if (result.success) {
            console.log('User registered:', result.user);
            showMessage('Registration successful! Please check your email for verification.', 'success');

            // Redirect to login page
            setTimeout(() => {
                window.location.href = '/login';
            }, 2000);
        } else {
            console.error('Registration error:', result.error);
            showMessage(getErrorMessage(result.error), 'error');
        }
    }

    async function handleGoogleSignIn(e) {
        e.preventDefault();
        const result = await signInWithGoogle();
        if (result.success) {
            console.log('Google sign-in successful:', result.user);
            showMessage('Signed in with Google successfully!', 'success');

            // Redirect to profile page
            setTimeout(() => {
                window.location.href = '/profile';
            }, 1000);
        } else {
            console.error('Google sign-in error:', result.error);
            showMessage(getErrorMessage(result.error), 'error');
        }
    }

    async function handleLogout(e) {
        e.preventDefault();
        const result = await signOutUser();
        if (result.success) {
            console.log('User signed out');
            showMessage('Logged out successfully!', 'success');

            // Redirect to home page
            setTimeout(() => {
                window.location.href = '/';
            }, 1000);
        } else {
            console.error('Logout error:', result.error);
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
            console.error('Password reset error:', result.error);
            showMessage(getErrorMessage(result.error), 'error');
        }
    }



    // Profile dropdown functionality
    function toggleProfileDropdown() {
        const dropdown = document.querySelector('.profile-dropdown');
        if (dropdown) {
            dropdown.classList.toggle('show');
        }
    }

    // Close dropdown when clicking outside
    document.addEventListener('click', function(event) {
        const dropdown = document.querySelector('.profile-dropdown');
        const profileIcon = document.querySelector('.profile-icon');

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
    window.toggleProfileDropdown = toggleProfileDropdown;
});
