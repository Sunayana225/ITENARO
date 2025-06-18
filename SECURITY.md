# 🔒 Security Guide for ITENERO

## 🚨 IMMEDIATE ACTION REQUIRED

**If you're reading this because API keys were exposed in Git, follow these steps immediately:**

### 1. **Revoke All Exposed API Keys**

#### Google Gemini AI
- Go to [Google AI Studio](https://makersuite.google.com/app/apikey)
- Delete the exposed key: `AIzaSyC1T02_042JU0N0UMVPEVu3TFXYPUR4DEo`
- Generate a new API key

#### OpenWeatherMap
- Go to [OpenWeatherMap API Keys](https://openweathermap.org/api_keys)
- Delete the exposed key: `aa52feefad1f400a14fa236928f73356`
- Generate a new API key

#### Firebase
- Go to [Firebase Console](https://console.firebase.google.com/)
- Regenerate all API keys and configuration
- Update authorized domains

#### Google OAuth
- Go to [Google Cloud Console](https://console.cloud.google.com/)
- Regenerate OAuth client secrets

### 2. **Clean Git History**

```bash
# Remove sensitive files from Git history
git filter-branch --force --index-filter \
  'git rm --cached --ignore-unmatch backend/static/scripts/firebase-config.js' \
  --prune-empty --tag-name-filter cat -- --all

# Force push to overwrite history (DANGEROUS - only if repository is private)
git push origin --force --all
```

### 3. **Secure Configuration**

#### Create `.env` file:
```bash
cp .env.example .env
# Edit .env with your new API keys
```

#### Update Firebase Config:
```javascript
// backend/static/scripts/firebase-config.js
const firebaseConfig = {
    apiKey: "YOUR_NEW_FIREBASE_API_KEY",
    authDomain: "your-project.firebaseapp.com",
    projectId: "your-project-id",
    // ... other config
};
```

## 🛡️ Security Best Practices

### **Environment Variables**
- ✅ Use `.env` files for local development
- ✅ Use platform environment variables for production
- ❌ Never hardcode API keys in source code
- ❌ Never commit `.env` files to Git

### **API Key Management**
- 🔄 Rotate API keys regularly
- 🔒 Use least-privilege access
- 📊 Monitor API usage for anomalies
- 🚫 Restrict API keys by domain/IP when possible

### **Git Security**
- ✅ Use `.gitignore` for sensitive files
- ✅ Review commits before pushing
- ✅ Use pre-commit hooks to scan for secrets
- ❌ Never force push to shared repositories

### **Firebase Security**
- 🔒 Configure security rules properly
- 🌐 Restrict authorized domains
- 👥 Use proper user authentication
- 📱 Enable App Check for production

## 🔧 Secure Development Setup

### 1. **Install Secret Scanner**
```bash
# Install git-secrets
git secrets --install
git secrets --register-aws
```

### 2. **Pre-commit Hook**
```bash
# Install pre-commit
pip install pre-commit

# Add to .pre-commit-config.yaml
repos:
  - repo: https://github.com/Yelp/detect-secrets
    rev: v1.4.0
    hooks:
      - id: detect-secrets
```

### 3. **Environment Validation**
```python
# Add to app.py startup
required_env_vars = [
    'GEMINI_API_KEY',
    'WEATHER_API_KEY',
    'GOOGLE_OAUTH_CLIENT_ID',
    'GOOGLE_OAUTH_CLIENT_SECRET'
]

for var in required_env_vars:
    if not os.getenv(var):
        raise ValueError(f"Required environment variable {var} is not set")
```

## 📞 Security Incident Response

If you discover a security vulnerability:

1. **Do NOT** create a public GitHub issue
2. **Email**: security@itenero.com (if available)
3. **Include**: 
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if any)

## 🔍 Security Checklist

- [ ] All API keys moved to environment variables
- [ ] `.env` file added to `.gitignore`
- [ ] Old API keys revoked and regenerated
- [ ] Firebase security rules configured
- [ ] Git history cleaned (if necessary)
- [ ] Monitoring set up for API usage
- [ ] Team educated on security practices

## 📚 Additional Resources

- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [GitHub Security Best Practices](https://docs.github.com/en/code-security)
- [Firebase Security Rules](https://firebase.google.com/docs/rules)
- [Google Cloud Security](https://cloud.google.com/security)

---

**Remember: Security is everyone's responsibility!** 🛡️
