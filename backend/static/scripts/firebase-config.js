// Firebase configuration and initialization
import { initializeApp } from "https://www.gstatic.com/firebasejs/10.7.1/firebase-app.js";
import { getAuth } from "https://www.gstatic.com/firebasejs/10.7.1/firebase-auth.js";

// Your web app's Firebase configuration
const firebaseConfig = {
    apiKey: "AIzaSyA9_HiVzTQNxTYWcf0I_p6ZztGVNIJwHbU",
    authDomain: "realestate-456c4.firebaseapp.com",
    projectId: "realestate-456c4",
    storageBucket: "realestate-456c4.firebasestorage.app",
    messagingSenderId: "628551361975",
    appId: "1:628551361975:web:b1b142fc82678d11af3432",
    measurementId: "G-VT0F7YRT1H"
};

// Initialize Firebase
const app = initializeApp(firebaseConfig);
const auth = getAuth(app);

export { app, auth };
