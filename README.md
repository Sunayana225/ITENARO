# 🌍 ITENERO - AI-Powered Travel Itinerary Generator

<div align="center">

![ITENERO Logo](backend/static/images/logo.jpg)

**Your Personal AI Travel Companion**

[![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://python.org)
[![Flask](https://img.shields.io/badge/Flask-2.0+-green.svg)](https://flask.palletsprojects.com/)
[![Firebase](https://img.shields.io/badge/Firebase-Auth-orange.svg)](https://firebase.google.com/)
[![Gemini AI](https://img.shields.io/badge/Gemini-AI-purple.svg)](https://ai.google.dev/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

[🚀 Live Demo](#) • [📖 Documentation](#installation) • [🐛 Report Bug](#contributing) • [💡 Request Feature](#contributing)

</div>

---

## 📋 Table of Contents

- [✨ Features](#-features)
- [🎯 Demo](#-demo)
- [🛠️ Tech Stack](#️-tech-stack)
- [⚡ Quick Start](#-quick-start)
- [📦 Installation](#-installation)
- [🔧 Configuration](#-configuration)
- [🎮 Usage](#-usage)
- [📱 Screenshots](#-screenshots)
- [🏗️ Project Structure](#️-project-structure)
- [🔌 API Documentation](#-api-documentation)
- [🤝 Contributing](#-contributing)
- [📄 License](#-license)
- [👥 Authors](#-authors)
- [🙏 Acknowledgments](#-acknowledgments)

---

## ✨ Features

### 🤖 **AI-Powered Planning**
- **Smart Itinerary Generation**: Uses Google's Gemini AI to create personalized travel plans
- **Preference-Based Recommendations**: Tailored suggestions based on your interests
- **Budget-Conscious Planning**: Optimized itineraries within your budget range
- **Multi-Day Planning**: Detailed day-by-day schedules

### 👤 **User Experience**
- **Firebase Authentication**: Secure login with email or Google OAuth
- **Personal Profiles**: Customizable profiles with travel preferences and bio
- **Wishlist Management**: Save and organize favorite destinations with priority levels
- **Travel Style Matching**: Adventure, luxury, budget, cultural, and family options

### 🌐 **Content & Community**
- **Destination Explorer**: Browse curated travel destinations with ratings
- **Travel Blog Platform**: Community-driven travel stories and experiences
- **Interactive Comments**: Engage with fellow travelers
- **Location-Based Content**: Filter by country, state, and category

### 🔧 **Technical Features**
- **Real-Time Weather**: Live weather data for destinations
- **Responsive Design**: Seamless experience on desktop and mobile
- **Rate Limiting**: Smart API usage to prevent quota exhaustion
- **Error Handling**: Graceful error management with user-friendly messages
- **Progressive Enhancement**: Works without JavaScript for basic functionality

---

## 🎯 Demo

### 🎬 **Live Features**

| Feature | Description | Status |
|---------|-------------|--------|
| 🗺️ **Itinerary Generator** | AI-powered travel planning | ✅ Active |
| 👤 **User Profiles** | Personal travel preferences | ✅ Active |
| ❤️ **Wishlist System** | Save favorite destinations | ✅ Active |
| 📝 **Travel Blog** | Community stories | ✅ Active |
| 🌤️ **Weather Integration** | Real-time weather data | ✅ Active |
| 🔐 **Authentication** | Firebase Auth | ✅ Active |

---

## 🛠️ Tech Stack

### **Backend**
- ![Python](https://img.shields.io/badge/Python-3776AB?style=flat&logo=python&logoColor=white) **Python 3.8+**
- ![Flask](https://img.shields.io/badge/Flask-000000?style=flat&logo=flask&logoColor=white) **Flask 2.0+**
- ![SQLite](https://img.shields.io/badge/SQLite-07405E?style=flat&logo=sqlite&logoColor=white) **SQLite Database**

### **Frontend**
- ![HTML5](https://img.shields.io/badge/HTML5-E34F26?style=flat&logo=html5&logoColor=white) **HTML5**
- ![CSS3](https://img.shields.io/badge/CSS3-1572B6?style=flat&logo=css3&logoColor=white) **CSS3**
- ![JavaScript](https://img.shields.io/badge/JavaScript-F7DF1E?style=flat&logo=javascript&logoColor=black) **Vanilla JavaScript**

### **Services & APIs**
- ![Firebase](https://img.shields.io/badge/Firebase-FFCA28?style=flat&logo=firebase&logoColor=black) **Firebase Authentication**
- ![Google](https://img.shields.io/badge/Google-4285F4?style=flat&logo=google&logoColor=white) **Gemini AI API**
- ![OpenWeather](https://img.shields.io/badge/OpenWeather-EA6100?style=flat&logo=openweathermap&logoColor=white) **Weather API**

### **Development Tools**
- ![Git](https://img.shields.io/badge/Git-F05032?style=flat&logo=git&logoColor=white) **Version Control**
- ![VS Code](https://img.shields.io/badge/VS_Code-007ACC?style=flat&logo=visual-studio-code&logoColor=white) **Development Environment**

---

## ⚡ Quick Start

```bash
# Clone the repository
git clone https://github.com/Sunayana225/ITENARO.git
cd ITENARO

# Install dependencies
pip install -r requirements.txt

# Set up environment variables
export GEMINI_API_KEY="your_gemini_api_key"
export WEATHER_API_KEY="your_weather_api_key"

# Initialize database
python init_db.py

# Run the application
python run_localhost.py
```

🎉 **That's it!** Open `http://localhost:5000` in your browser.

---

## 📦 Installation

### **Prerequisites**

- Python 3.8 or higher
- pip (Python package manager)
- Git

### **Step-by-Step Installation**

1. **Clone the Repository**
   ```bash
   git clone https://github.com/Sunayana225/ITENARO.git
   cd ITENARO
   ```

2. **Create Virtual Environment** (Recommended)
   ```bash
   python -m venv venv

   # On Windows
   venv\Scripts\activate

   # On macOS/Linux
   source venv/bin/activate
   ```

3. **Install Dependencies**
   ```bash
   pip install flask
   pip install google-generativeai
   pip install requests
   pip install flask-mail
   pip install flask-dance
   pip install werkzeug
   ```

4. **Set Up Environment Variables**

   Create a `.env` file in the root directory:
   ```env
   GEMINI_API_KEY=your_gemini_api_key_here
   WEATHER_API_KEY=your_openweather_api_key_here
   FLASK_SECRET_KEY=your_secret_key_here
   # Optional integrations
   TICKETMASTER_API_KEY=your_ticketmaster_api_key_here
   LIVE_PRICING_PROVIDER=amadeus
   AMADEUS_API_KEY=your_amadeus_client_id_here
   AMADEUS_API_SECRET=your_amadeus_client_secret_here
   LIVE_PRICING_ORIGIN=NYC
   ```

5. **Initialize Database**
   ```bash
   python init_db.py
   ```

6. **Run the Application**
   ```bash
   python run_localhost.py
   ```

### **Docker Installation** (Optional)

```bash
# Build the Docker image
docker build -t itenero .

# Run the container
docker run -p 5000:5000 itenero
```

---

## 🔧 Configuration

### **🔥 Firebase Setup**

1. **Create Firebase Project**
   - Go to [Firebase Console](https://console.firebase.google.com/)
   - Create a new project
   - Enable Authentication

2. **Configure Authentication**
   - Enable Email/Password authentication
   - Enable Google OAuth (optional)
   - Add your domain to authorized domains

3. **Update Configuration**
   ```javascript
   // backend/static/scripts/firebase-config.js
   const firebaseConfig = {
     apiKey: "your-api-key",
     authDomain: "your-project.firebaseapp.com",
     projectId: "your-project-id",
     // ... other config
   };
   ```

### **🤖 API Keys Setup**

#### **Google Gemini AI**
1. Visit [Google AI Studio](https://makersuite.google.com/app/apikey)
2. Create a new API key
3. Add to environment variables

#### **OpenWeatherMap**
1. Register at [OpenWeatherMap](https://openweathermap.org/api)
2. Get your free API key
3. Add to environment variables

### **⚙️ Application Settings**

```python
# backend/app.py - Rate Limiting Configuration
MAX_CALLS_PER_MINUTE = 2  # Adjust based on your API plan
MAX_CALLS_PER_DAY = 50    # Adjust based on your API plan
```

---

## 🎮 Usage

### **🚀 Getting Started**

1. **Create Account**
   - Visit the registration page
   - Sign up with email or Google
   - Verify your email (if required)

2. **Complete Profile**
   - Add your display name and bio
   - Set travel preferences
   - Choose your travel style

3. **Generate Your First Itinerary**
   - Enter destination
   - Set budget and duration
   - Select travel purpose
   - Choose preferences (hiking, museums, etc.)
   - Click "Generate Itinerary"

### **📱 Key Features Usage**

#### **Itinerary Generation**
```
Step 1: Destination → "Paris, France"
Step 2: Budget → "$2000"
Step 3: Duration → "7 days"
Step 4: Purpose → "Leisure"
Step 5: Preferences → "Museums, Food Tours, Historical Sites"
```

#### **Wishlist Management**
- Browse destinations
- Click "Add to Wishlist"
- Set priority levels (High, Medium, Low)
- Manage from profile page

#### **Blog Interaction**
- Read travel stories
- Filter by location/category
- Add comments
- Share your own experiences

---

## 📱 Screenshots

### **🏠 Home Page - AI Itinerary Generator**
![Home Page](docs/screenshots/home.png)
*Step-by-step itinerary generation with AI-powered recommendations*

### **👤 User Profile & Wishlist**
![Profile Page](docs/screenshots/profile.png)
*Personalized profiles with wishlist management and travel preferences*

### **🗺️ Destinations Explorer**
![Destinations](docs/screenshots/destinations.png)
*Browse curated destinations with ratings and detailed information*

### **📝 Travel Blog Community**
![Blog Page](docs/screenshots/blog.png)
*Community-driven travel stories and experiences*

---

## 🏗️ Project Structure

```
ITENERO/
├── 📁 backend/
│   ├── 📄 app.py                 # Main Flask application
│   ├── 📄 prompts.py             # AI prompt templates
│   ├── 📄 schema.sql             # Database schema
│   ├── 📁 static/
│   │   ├── 📁 scripts/           # JavaScript files
│   │   │   ├── 📄 script.js      # Main application logic
│   │   │   ├── 📄 firebase-auth.js
│   │   │   ├── 📄 firebase-config.js
│   │   │   └── 📄 destinations.js
│   │   ├── 📁 images/            # Static images
│   │   └── 📄 styles.css         # Application styles
│   └── 📁 templates/             # HTML templates
│       ├── 📄 index.html         # Home page
│       ├── 📄 profile.html       # User profile
│       ├── 📄 destinations.html  # Destinations page
│       ├── 📄 blog.html          # Blog page
│       └── 📄 login.html         # Authentication
├── 📁 Database/
│   └── 📄 blog.db               # SQLite database
├── 📁 docs/                     # Documentation
├── 📄 init_db.py               # Database initialization
├── 📄 run_localhost.py         # Local development server
├── 📄 requirements.txt         # Python dependencies
└── 📄 README.md               # This file
```

---

## 🔌 API Documentation

### **Authentication Endpoints**

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/profile` | User profile page |
| `GET` | `/login` | Login page |
| `POST` | `/api/profile` | Create user profile |
| `PUT` | `/api/profile/<uid>` | Update user profile |

### **Itinerary Endpoints**

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/generate-itinerary` | Generate AI itinerary |
| `GET` | `/api/status` | Check API rate limits |

### **Destinations & Wishlist**

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/destinations` | Get all destinations |
| `GET` | `/api/wishlist/<uid>` | Get user wishlist |
| `POST` | `/api/wishlist` | Add to wishlist |
| `DELETE` | `/api/wishlist/<uid>/<id>` | Remove from wishlist |

### **Weather & Blog**

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/get-weather?city=<name>` | Get weather data |
| `GET` | `/blog` | Blog posts page |
| `POST` | `/post-blog` | Create blog post |

---

## 🤝 Contributing

We welcome contributions! Here's how you can help:

### **🐛 Bug Reports**
1. Check existing issues first
2. Create detailed bug report
3. Include steps to reproduce
4. Add screenshots if applicable

### **💡 Feature Requests**
1. Search existing feature requests
2. Describe the feature clearly
3. Explain the use case
4. Consider implementation complexity

### **🔧 Code Contributions**

1. **Fork the Repository**
   ```bash
   git fork https://github.com/yourusername/itenero.git
   ```

2. **Create Feature Branch**
   ```bash
   git checkout -b feature/amazing-feature
   ```

3. **Make Changes**
   - Follow existing code style
   - Add comments for complex logic
   - Update documentation if needed

4. **Test Your Changes**
   ```bash
   python -m pytest tests/
   ```

5. **Submit Pull Request**
   - Clear description of changes
   - Link to related issues
   - Include screenshots for UI changes

### **📝 Development Guidelines**

- **Code Style**: Follow PEP 8 for Python
- **Commits**: Use conventional commit messages
- **Testing**: Add tests for new features
- **Documentation**: Update README for significant changes

---


### **⭐ Star this repository if you found it helpful!**

**Made with ❤️ for travelers around the world**

[⬆ Back to Top](#-itenero---ai-powered-travel-itinerary-generator)

</div>
