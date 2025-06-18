# 🔥 Firebase Authentication on Localhost Setup Guide

This guide will help you run the ITENARO project with Firebase authentication on localhost.

## 🚀 Quick Start

### Option 1: Using the Startup Script
```bash
python run_localhost.py
```

### Option 2: Manual Start
```bash
cd backend
python app.py
```

Then visit: `http://localhost:5000/localhost-test`

## 🔧 Firebase Console Configuration

### Step 1: Access Firebase Console
1. Go to [Firebase Console](https://console.firebase.google.com/)
2. Select your project: `realestate-456c4`

### Step 2: Configure Authentication
1. Click **Authentication** in the left sidebar
2. Go to **Sign-in method** tab
3. Enable these providers:
   - ✅ **Email/Password** - Click and enable
   - ✅ **Google** - Click, enable, and add OAuth client ID

### Step 3: Add Localhost to Authorized Domains
1. In Authentication, go to **Settings** tab
2. Scroll down to **Authorized domains**
3. Click **Add domain**
4. Add: `localhost`
5. Click **Save**

### Step 4: Configure Google OAuth (Optional)
1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Select your project
3. Go to **APIs & Services** → **Credentials**
4. Find your OAuth 2.0 client ID
5. Add `http://localhost:5000` to authorized origins
6. Add `http://localhost:5000` to authorized redirect URIs

## 📱 Testing the Implementation

### Available Test URLs:
- **Main App**: `http://localhost:5000/`
- **Localhost Test Page**: `http://localhost:5000/localhost-test`
- **Login Page**: `http://localhost:5000/login`
- **Register Page**: `http://localhost:5000/register`
- **Profile Page**: `http://localhost:5000/profile`

### Test Scenarios:

#### 1. Email/Password Authentication
- Use test email: `test@example.com`
- Use test password: `password123`
- Try both sign up and sign in

#### 2. Google Authentication
- Click "Sign In with Google"
- Use your Google account
- Should redirect back to localhost

#### 3. Password Reset
- Enter an email address
- Check for reset email (may go to spam)

## 🐛 Troubleshooting

### Common Issues:

#### 1. "Firebase: Error (auth/unauthorized-domain)"
**Solution**: Add `localhost` to Firebase authorized domains
1. Firebase Console → Authentication → Settings
2. Add `localhost` to authorized domains

#### 2. "Firebase: Error (auth/operation-not-allowed)"
**Solution**: Enable authentication methods
1. Firebase Console → Authentication → Sign-in method
2. Enable Email/Password and Google

#### 3. Google Sign-in Popup Blocked
**Solution**: Allow popups for localhost
1. Click the popup blocker icon in browser
2. Allow popups for localhost:5000

#### 4. CORS Errors
**Solution**: Firebase automatically handles CORS for localhost

#### 5. Module Import Errors
**Solution**: Ensure you're using a modern browser
- Chrome 61+
- Firefox 60+
- Safari 10.1+
- Edge 16+

### Debug Mode:
1. Open browser Developer Tools (F12)
2. Check Console tab for errors
3. Check Network tab for failed requests

## 🔒 Security Notes

### Development vs Production:
- ✅ Localhost is safe for development
- ✅ Firebase handles all security automatically
- ⚠️ Never expose API keys in production client code
- ⚠️ Use environment variables for sensitive config

### Firebase Security:
- 🔐 All authentication is handled by Firebase
- 🔐 Tokens are automatically managed
- 🔐 User data is encrypted in transit
- 🔐 No passwords stored locally

## 📊 Expected Behavior

### Successful Setup:
1. ✅ Server starts on localhost:5000
2. ✅ Firebase connection established
3. ✅ Authentication methods work
4. ✅ User state persists across page reloads
5. ✅ Error messages are user-friendly

### Test Results:
- **Email Sign Up**: Creates new user + sends verification
- **Email Sign In**: Authenticates existing user
- **Google Sign In**: Uses Google OAuth flow
- **Password Reset**: Sends reset email
- **Sign Out**: Clears user session

## 🎯 Next Steps

Once localhost testing works:
1. ✅ Test all authentication flows
2. ✅ Verify email verification works
3. ✅ Test password reset emails
4. ✅ Check user profile page
5. ✅ Test sign out functionality

## 📞 Support

If you encounter issues:
1. Check browser console for errors
2. Verify Firebase Console settings
3. Ensure localhost is in authorized domains
4. Try different browsers
5. Clear browser cache/cookies

## 🔗 Useful Links

- [Firebase Auth Documentation](https://firebase.google.com/docs/auth/web/start)
- [Firebase Console](https://console.firebase.google.com/)
- [Google Cloud Console](https://console.cloud.google.com/)
- [Firebase Auth Troubleshooting](https://firebase.google.com/docs/auth/web/troubleshooting)

---

**Happy Testing! 🎉**
