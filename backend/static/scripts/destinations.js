document.addEventListener("DOMContentLoaded", function () {
    console.log("Destinations page loaded!");

    let currentUser = null;
    let allDestinations = [];
    let userWishlist = [];

    // Initialize Firebase auth state listener
    if (typeof window.firebase !== 'undefined') {
        // Firebase auth state listener will be handled by the main script
        // We'll check for user state periodically
        checkAuthState();
    }

    // Load destinations from API
    loadDestinations();

    async function checkAuthState() {
        // This will be called by the main Firebase auth system
        // For now, we'll check if user is logged in via a simple method
        try {
            const response = await fetch('/api/auth-check');
            if (response.ok) {
                const userData = await response.json();
                currentUser = userData;
                loadUserWishlist();
            }
        } catch (error) {
            console.log('User not authenticated');
        }
    }

    async function loadDestinations() {
        try {
            const response = await fetch('/api/destinations');
            if (response.ok) {
                allDestinations = await response.json();
                displayDestinations(allDestinations);
            }
        } catch (error) {
            console.error('Error loading destinations:', error);
            // Fallback to static destinations
            displayStaticDestinations();
        }
    }

    async function loadUserWishlist() {
        if (!currentUser) return;

        try {
            const response = await fetch(`/api/wishlist/${currentUser.uid}`);
            if (response.ok) {
                userWishlist = await response.json();
                updateWishlistButtons();
            }
        } catch (error) {
            console.error('Error loading wishlist:', error);
        }
    }

    function displayDestinations(destinations) {
        const grid = document.getElementById('destinationsGrid');
        const wishlistDestinationIds = userWishlist.map(item => item.destination_id);

        const destinationsHTML = destinations.map(dest => {
            const isInWishlist = wishlistDestinationIds.includes(dest.id);
            return `
                <div class="destination-card" data-category="${dest.category}" data-id="${dest.id}">
                    <img src="${dest.image_url}" alt="${dest.name}" onerror="this.src='/static/images/placeholder.jpg'">
                    <div class="destination-content">
                        <h3>${dest.name}</h3>
                        <p>${dest.description}</p>
                        <p class="destination-location"><strong>${dest.location}, ${dest.country}</strong></p>
                        <p class="destination-rating">⭐ ${dest.rating}/5</p>
                        <div class="destination-actions">
                            <button class="view-details-btn" onclick="viewDestination('${dest.name}')">
                                View Details
                            </button>
                            ${currentUser ? `
                                <button class="wishlist-btn ${isInWishlist ? 'in-wishlist' : ''}"
                                        onclick="toggleWishlist(${dest.id})"
                                        data-destination-id="${dest.id}">
                                    ${isInWishlist ? '❤️ In Wishlist' : '🤍 Add to Wishlist'}
                                </button>
                            ` : `
                                <button class="wishlist-btn" onclick="redirectToLogin()">
                                    🤍 Login to Save
                                </button>
                            `}
                        </div>
                    </div>
                </div>
            `;
        }).join('');

        grid.innerHTML = destinationsHTML;
    }

    function displayStaticDestinations() {
        const grid = document.getElementById('destinationsGrid');
        grid.innerHTML = `
            <div class="destination-card" data-category="beach">
                <img src="/static/images/maldives.jpg" alt="Maldives">
                <div class="destination-content">
                    <h3>Maldives</h3>
                    <p>Relax on stunning white beaches and explore coral reefs.</p>
                    <div class="destination-actions">
                        <button class="view-details-btn" onclick="viewDestination('Maldives')">View Details</button>
                    </div>
                </div>
            </div>
            <div class="destination-card" data-category="historical">
                <img src="/static/images/rome.jpg" alt="Rome">
                <div class="destination-content">
                    <h3>Rome</h3>
                    <p>Discover ancient history in the heart of Italy.</p>
                    <div class="destination-actions">
                        <button class="view-details-btn" onclick="viewDestination('Rome')">View Details</button>
                    </div>
                </div>
            </div>
            <div class="destination-card" data-category="adventure">
                <img src="/static/images/everest.jpg" alt="Mount Everest">
                <div class="destination-content">
                    <h3>Mount Everest</h3>
                    <p>Experience the ultimate adventure in the Himalayas.</p>
                    <div class="destination-actions">
                        <button class="view-details-btn" onclick="viewDestination('Mount Everest')">View Details</button>
                    </div>
                </div>
            </div>
            <div class="destination-card" data-category="luxury">
                <img src="/static/images/dubai.jpg" alt="Dubai">
                <div class="destination-content">
                    <h3>Dubai</h3>
                    <p>Enjoy luxury shopping, skyscrapers, and desert adventures.</p>
                    <div class="destination-actions">
                        <button class="view-details-btn" onclick="viewDestination('Dubai')">View Details</button>
                    </div>
                </div>
            </div>
        `;
    }

    function updateWishlistButtons() {
        const wishlistDestinationIds = userWishlist.map(item => item.destination_id);

        document.querySelectorAll('.wishlist-btn').forEach(btn => {
            const destId = parseInt(btn.getAttribute('data-destination-id'));
            const isInWishlist = wishlistDestinationIds.includes(destId);

            btn.textContent = isInWishlist ? '❤️ In Wishlist' : '🤍 Add to Wishlist';
            btn.className = `wishlist-btn ${isInWishlist ? 'in-wishlist' : ''}`;
        });
    }

    // Filter destinations by category
    function filterDestinations(category) {
        const destinationCards = document.querySelectorAll(".destination-card");
        const filterButtons = document.querySelectorAll(".filter-btn");

        // Highlight active filter button
        filterButtons.forEach(button => {
            button.classList.remove("active");
            if (button.textContent.toLowerCase() === category) {
                button.classList.add("active");
            }
        });

        // Show/hide destination cards based on category
        destinationCards.forEach(card => {
            if (category === "all" || card.getAttribute("data-category") === category) {
                card.style.display = "block";
            } else {
                card.style.display = "none";
            }
        });
    }

    // Site-wide search with dropdown suggestions for the destinations page
    function siteWideSearchWithDropdown() {
        const searchInput = document.getElementById("search");
        const dropdown = document.getElementById("searchDropdown");
        const query = searchInput.value.trim();
        if (!query) {
            dropdown.style.display = "none";
            // Show all cards if search is empty
            document.querySelectorAll(".destination-card").forEach(card => card.style.display = "block");
            return;
        }
        fetch(`/api/search?query=${encodeURIComponent(query)}`)
            .then(res => res.json())
            .then(results => {
                if (results.length === 0) {
                    dropdown.innerHTML = '<div style="padding:8px;">No results found</div>';
                } else {
                    dropdown.innerHTML = results.map(r =>
                        `<div class="search-result" style="padding:8px;cursor:pointer;" data-url="${r.url}">
                            <b>${r.name}</b> <span style="color:#888;">(${r.type})</span>
                        </div>`
                    ).join('');
                }
                dropdown.style.display = 'block';
                // Hide all cards if searching
                document.querySelectorAll(".destination-card").forEach(card => card.style.display = "none");
            });
    }

    // Click on dropdown result
    document.addEventListener('click', function (e) {
        let resultDiv = e.target.closest('.search-result');
        const searchInput = document.getElementById("search");
        const dropdown = document.getElementById("searchDropdown");
        if (resultDiv) {
            window.location.href = resultDiv.getAttribute('data-url');
        } else if (!searchInput.contains(e.target) && !dropdown.contains(e.target)) {
            dropdown.style.display = 'none';
        }
    });

    // View destination details
    function viewDestination(destinationName) {
        alert(`You clicked on ${destinationName}. Redirecting to details page...`);
        // Redirect to a detailed page or show a modal with more information
    }

    // Wishlist functionality
    async function toggleWishlist(destinationId) {
        if (!currentUser) {
            redirectToLogin();
            return;
        }

        const wishlistDestinationIds = userWishlist.map(item => item.destination_id);
        const isInWishlist = wishlistDestinationIds.includes(destinationId);

        try {
            if (isInWishlist) {
                // Remove from wishlist
                const response = await fetch(`/api/wishlist/${currentUser.uid}/${destinationId}`, {
                    method: 'DELETE'
                });

                if (response.ok) {
                    userWishlist = userWishlist.filter(item => item.destination_id !== destinationId);
                    updateWishlistButtons();
                    showMessage('Removed from wishlist!', 'success');
                } else {
                    showMessage('Error removing from wishlist', 'error');
                }
            } else {
                // Add to wishlist
                const response = await fetch('/api/wishlist', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        user_uid: currentUser.uid,
                        destination_id: destinationId,
                        priority: 2
                    })
                });

                if (response.ok) {
                    // Add to local wishlist array
                    const destination = allDestinations.find(d => d.id === destinationId);
                    if (destination) {
                        userWishlist.push({
                            destination_id: destinationId,
                            ...destination
                        });
                    }
                    updateWishlistButtons();
                    showMessage('Added to wishlist!', 'success');
                } else {
                    showMessage('Error adding to wishlist', 'error');
                }
            }
        } catch (error) {
            console.error('Error toggling wishlist:', error);
            showMessage('Error updating wishlist', 'error');
        }
    }

    function redirectToLogin() {
        window.location.href = '/login';
    }

    function showMessage(message, type) {
        const flashDiv = document.createElement('div');
        flashDiv.className = `flash ${type === 'success' ? 'success' : 'danger'}`;
        flashDiv.textContent = message;
        flashDiv.style.position = 'fixed';
        flashDiv.style.top = '20px';
        flashDiv.style.right = '20px';
        flashDiv.style.zIndex = '9999';
        flashDiv.style.padding = '15px 20px';
        flashDiv.style.borderRadius = '8px';
        flashDiv.style.boxShadow = '0 4px 12px rgba(0,0,0,0.15)';

        document.body.appendChild(flashDiv);

        setTimeout(() => {
            flashDiv.remove();
        }, 3000);
    }

    // Attach event listeners
    document.querySelectorAll(".filter-btn").forEach(button => {
        button.addEventListener("click", function () {
            filterDestinations(this.textContent.toLowerCase());
        });
    });

    const searchInput = document.getElementById("search");
    if (searchInput) {
        searchInput.addEventListener("input", siteWideSearchWithDropdown);
    }

    // Expose functions globally for HTML onclick usage
    window.filterDestinations = filterDestinations;
    window.viewDestination = viewDestination;
    window.toggleWishlist = toggleWishlist;
    window.redirectToLogin = redirectToLogin;
});