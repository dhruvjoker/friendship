# Quick Start Guide - Friendship Circle

Get your Friendship Circle application running in 5 minutes!

## Prerequisites

- Windows, macOS, or Linux
- Python 3.8 or higher (download from https://www.python.org/)

## Quick Setup (Windows)

1. **Open Command Prompt** (cmd.exe)

2. **Navigate to the project folder:**
   ```bash
   cd "C:\Users\[YourUsername]\Downloads\New folder\CHAPTER 1\friendship_app"
   ```

3. **Run the setup script:**
   ```bash
   setup.bat
   ```

4. **The setup will:**
   - Create a virtual environment
   - Install all dependencies
   - Create a .env configuration file

5. **Start the server:**
   ```bash
   venv\Scripts\activate.bat
   python run.py
   ```

6. **Open your browser and visit:**
   ```
   http://localhost:5000
   ```

## Quick Setup (macOS/Linux)

1. **Open Terminal**

2. **Navigate to the project folder:**
   ```bash
   cd ~/Downloads/"New folder"/CHAPTER\ 1/friendship_app
   ```

3. **Make the setup script executable and run it:**
   ```bash
   chmod +x setup.sh
   ./setup.sh
   ```

4. **The setup will:**
   - Create a virtual environment
   - Install all dependencies
   - Create a .env configuration file

5. **Start the server:**
   ```bash
   source venv/bin/activate
   python run.py
   ```

6. **Open your browser and visit:**
   ```
   http://localhost:5000
   ```

## Manual Setup (If Scripts Don't Work)

### Windows:
```bash
# Create virtual environment
python -m venv venv

# Activate it
venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy environment file
copy .env.example .env

# Run the app
python run.py
```

### macOS/Linux:
```bash
# Create virtual environment
python3 -m venv venv

# Activate it
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Copy environment file
cp .env.example .env

# Run the app
python run.py
```

## Test the Application

### 1. Create First Account
- Go to `http://localhost:5000`
- Click "Register"
- Username: `alice`
- Email: `alice@example.com`
- Password: `password123`
- Select some problem areas
- Click "Create Account"

### 2. Create Second Account (in another browser or private window)
- Click "Register"
- Username: `bob`
- Email: `bob@example.com`
- Password: `password123`
- Select overlapping problem areas
- Click "Create Account"

### 3. Find Match as First User
- Click "Find New Match"
- Wait for match notification
- Click "Open Chat"
- Start typing your message
- Click "Send"

### 4. Check Message as Second User
- Log in as `bob`
- See the conversation in "Your Conversations"
- Click "Open Chat"
- Reply to the message

## Features to Explore

✅ **Anonymous Matching** - Users are matched by shared problems
✅ **Encrypted Chats** - All messages are encrypted
✅ **Profile Management** - Update your bio and problem areas
✅ **Real-time Updates** - Refresh conversations every 3 seconds
✅ **Privacy Protection** - No personal info shared

## Stopping the Server

Press `Ctrl+C` in the terminal where the server is running.

## Troubleshooting

### "Python not found"
- Install Python from https://www.python.org/
- Make sure to check "Add Python to PATH" during installation
- Restart your terminal after installation

### "Module not found"
```bash
# Make sure virtual environment is activated
# Then reinstall:
pip install -r requirements.txt --force-reinstall
```

### Port 5000 already in use
The server is already running or another app is using port 5000.

Option 1: Close the other application
Option 2: Modify `run.py` to use a different port:
```python
socketio.run(app, debug=True, host='0.0.0.0', port=5001)
```

### Database errors
```bash
# Delete the database file
rm friendship_app.db

# Restart the app (it will recreate the database)
python run.py
```

## Project Structure

```
friendship_app/
├── app/                          # Main application package
│   ├── static/
│   │   ├── css/
│   │   │   └── style.css        # Styling for all pages
│   │   └── js/
│   │       └── main.js          # JavaScript utilities
│   ├── templates/               # HTML templates
│   │   ├── base.html            # Base template
│   │   ├── index.html           # Home page
│   │   ├── login.html           # Login page
│   │   ├── register.html        # Registration page
│   │   ├── dashboard.html       # Main dashboard
│   │   ├── profile.html         # User profile
│   │   └── chat.html            # Chat interface
│   ├── __init__.py              # App initialization
│   ├── models.py                # Database models
│   ├── routes.py                # API routes
│   └── encryption.py            # Message encryption
├── config.py                    # Configuration
├── run.py                       # Entry point
├── requirements.txt             # Python dependencies
├── .env.example                 # Environment template
├── .gitignore                   # Git ignore file
├── setup.bat                    # Windows setup
├── setup.sh                     # Linux/Mac setup
├── README.md                    # Full documentation
└── QUICKSTART.md               # This file
```

## Next Steps

1. **Customize the UI** - Edit `app/static/css/style.css`
2. **Add more problem categories** - Modify database initialization in `app/__init__.py`
3. **Deploy to production** - See README.md for deployment guide
4. **Add more features** - Extend routes.py and add new templates

## Security Notes

⚠️ **For Development Only**: The current setup is for development. Before deploying:
- Change the SECRET_KEY in `config.py`
- Set DEBUG = False
- Use PostgreSQL instead of SQLite
- Enable HTTPS
- Set secure cookies to True

## Support & Documentation

- Full README: Read `README.md` for complete documentation
- Flask Docs: https://flask.palletsprojects.com/
- SQLAlchemy Docs: https://docs.sqlalchemy.org/
- Cryptography Docs: https://cryptography.io/

## Need Help?

1. Check the README.md for detailed information
2. Review the error message carefully
3. Check browser console for JavaScript errors (F12)
4. Look at terminal output for Python errors

---

**Enjoy building Friendship Circle! 💙**

