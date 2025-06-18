// Firebase Authentication Module
import { auth } from './firebase-config.js';
import {
    signInWithEmailAndPassword,
    createUserWithEmailAndPassword,
    signOut,
    onAuthStateChanged,
    sendPasswordResetEmail,
    sendEmailVerification,
    GoogleAuthProvider,
    signInWithPopup
} from "https://www.gstatic.com/firebasejs/10.7.1/firebase-auth.js";

const googleProvider = new GoogleAuthProvider();

// Authentication Functions
export async function signInUser(email, password) {
    try {
        const userCredential = await signInWithEmailAndPassword(auth, email, password);
        return { success: true, user: userCredential.user };
    } catch (error) {
        return { success: false, error: error };
    }
}

export async function registerUser(email, password) {
    try {
        const userCredential = await createUserWithEmailAndPassword(auth, email, password);
        // Send email verification
        await sendEmailVerification(userCredential.user);
        return { success: true, user: userCredential.user };
    } catch (error) {
        return { success: false, error: error };
    }
}

export async function signInWithGoogle() {
    try {
        const result = await signInWithPopup(auth, googleProvider);
        return { success: true, user: result.user };
    } catch (error) {
        return { success: false, error: error };
    }
}

export async function signOutUser() {
    try {
        await signOut(auth);
        return { success: true };
    } catch (error) {
        return { success: false, error: error };
    }
}

export async function resetPassword(email) {
    try {
        await sendPasswordResetEmail(auth, email);
        return { success: true };
    } catch (error) {
        return { success: false, error: error };
    }
}

export function onAuthStateChange(callback) {
    return onAuthStateChanged(auth, callback);
}

export function getCurrentUser() {
    return auth.currentUser;
}

// Error message helper
export function getErrorMessage(error) {
    switch (error.code) {
        case 'auth/user-not-found':
            return 'No user found with this email address.';
        case 'auth/wrong-password':
            return 'Incorrect password.';
        case 'auth/email-already-in-use':
            return 'An account with this email already exists.';
        case 'auth/weak-password':
            return 'Password should be at least 6 characters.';
        case 'auth/invalid-email':
            return 'Invalid email address.';
        case 'auth/too-many-requests':
            return 'Too many failed attempts. Please try again later.';
        case 'auth/network-request-failed':
            return 'Network error. Please check your connection.';
        case 'auth/popup-closed-by-user':
            return 'Sign-in popup was closed before completing.';
        default:
            return error.message || 'An error occurred. Please try again.';
    }
}

// UI Helper Functions
export function showMessage(message, type = 'info') {
    // Create or update flash message
    let flashContainer = document.querySelector('.flash-container');
    if (!flashContainer) {
        flashContainer = document.createElement('div');
        flashContainer.className = 'flash-container';
        const main = document.querySelector('main');
        if (main) {
            main.insertBefore(flashContainer, main.firstChild);
        }
    }

    const flashDiv = document.createElement('div');
    flashDiv.className = `flash ${type === 'success' ? 'success' : 'danger'}`;
    flashDiv.textContent = message;

    flashContainer.innerHTML = '';
    flashContainer.appendChild(flashDiv);

    // Auto-remove after 5 seconds
    setTimeout(() => {
        flashDiv.remove();
    }, 5000);
}

export function updateUIForUser(user) {
    // Update navigation to show user is logged in
    const profileLinks = document.querySelectorAll('.profile');
    profileLinks.forEach(link => {
        const firstLetter = user.email.charAt(0).toUpperCase();
        link.innerHTML = `
            <div class="profile-dropdown">
                <div class="profile-icon" onclick="toggleProfileDropdown()" title="${user.email}">${firstLetter}</div>
                <div class="profile-dropdown-content" id="profileDropdown">
                    <a href="/profile">Profile</a>
                    <a href="#" class="logout-btn">Logout</a>
                </div>
            </div>
        `;
    });

    // Add event listeners for logout buttons
    setTimeout(() => {
        const logoutBtns = document.querySelectorAll('.logout-btn');
        logoutBtns.forEach(btn => {
            btn.addEventListener('click', async (e) => {
                e.preventDefault();
                const result = await signOutUser();
                if (result.success) {
                    showMessage('Logged out successfully!', 'success');
                    setTimeout(() => {
                        window.location.href = '/';
                    }, 1000);
                } else {
                    showMessage('Error signing out', 'error');
                }
            });
        });
    }, 100);
}

export function updateUIForSignedOut() {
    // Update navigation to show login/register links
    const profileLinks = document.querySelectorAll('.profile');
    profileLinks.forEach(link => {
        link.innerHTML = `
            <a href="/login">Login</a> |
            <a href="/register">Register</a>
        `;
    });
}

// Profile dropdown functionality
export function toggleProfileDropdown() {
    const dropdown = document.querySelector('.profile-dropdown');
    if (dropdown) {
        dropdown.classList.toggle('show');
    }
}

// Initialize dropdown click outside handler
export function initDropdownHandler() {
    document.addEventListener('click', function(event) {
        const dropdown = document.querySelector('.profile-dropdown');

        if (dropdown && !dropdown.contains(event.target)) {
            dropdown.classList.remove('show');
        }
    });
}

// Make toggle function globally available
if (typeof window !== 'undefined') {
    window.toggleProfileDropdown = toggleProfileDropdown;
}
