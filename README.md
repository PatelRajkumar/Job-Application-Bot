# Resume Tailor Telegram Bot

A powerful Telegram bot designed to automatically tailor your resume to specific job descriptions using Gemini AI. The bot generates personalized resumes (HTML & PDF), writes cover letters, drafts cold emails to recruiters, and automatically uploads the artifacts to Google Drive.

This guide will walk you through setting up the project from scratch.

---

## 📋 Prerequisites

Before you begin, ensure you have the following installed:
- **Python 3.8+** (for the Telegram bot and AI logic)
- **Node.js 18+** (for generating PDFs via Puppeteer and Google Drive scripts)
- **Git**

---

## 🚀 Step 1: Installation & Setup

1. **Clone the repository**:
   ```bash
   git clone <your-repo-url>
   cd resume-tweaker
   ```

2. **Install Python dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Install Node.js dependencies**:
   ```bash
   npm install
   ```

4. **Environment Variables**:
   Create a `.env` file from the example template:
   ```bash
   cp .env.example .env
   ```

---

## 🤖 Step 2: Telegram Bot Setup

1. Open Telegram and search for [@BotFather](https://t.me/BotFather).
2. Send the `/newbot` command and follow the prompts to create your bot.
3. Once created, BotFather will give you a **Bot Token**.
4. Paste this token into your `.env` file as `TELEGRAM_BOT_TOKEN`.
5. To restrict the bot so only you can use it, you need your Telegram User ID. Search for `@userinfobot` or `@RawDataBot` in Telegram, start it, and get your numeric **User ID**.
6. Paste this ID into your `.env` file as `ALLOWED_USER_ID`.

---

## 🧠 Step 3: Gemini API Setup

1. Go to [Google AI Studio](https://aistudio.google.com/app/apikey).
2. Click **Create API Key**.
3. Paste the key into your `.env` file as `GEMINI_API_KEY`.

---

## ☁️ Step 4: Google Drive Integration

The bot automatically uploads generated resumes, guides, and cover letters to a specific Google Drive folder.

1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
2. Create a new project or select an existing one.
3. Navigate to **APIs & Services > Library** and enable the **Google Drive API**.
4. Go to **APIs & Services > Credentials**.
5. Click **Create Credentials** -> **OAuth client ID**.
6. Select **Desktop app** as the Application type.
7. Copy the **Client ID** and **Client Secret** into your `.env` file as `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`.
8. Generate your Refresh Token by running:
   ```bash
   node upload_to_drive.js --setup
   ```
   Follow the authorization link, grant access, and copy the provided refresh token into your `.env` file as `GOOGLE_REFRESH_TOKEN` (or allow it to save to `token.json`).
9. Create a folder in your Google Drive where you want the resumes saved.
10. Open the folder in your browser and look at the URL: `https://drive.google.com/drive/folders/<THIS_IS_YOUR_FOLDER_ID>`.
11. Paste that ID into your `.env` file as `DRIVE_FOLDER_ID`.

---

## 📊 Step 5: Supabase Setup (Analytics Logging)

The bot logs analytics (session data, token usage, evaluations) to a PostgreSQL database. 

1. Create a free project on [Supabase](https://supabase.com/).
2. Go to your Project Settings -> Database.
3. Copy the **Connection String** (URI) and add it to your `.env` file:
   ```env
   SUPABASE_DB_URL=postgres://user:password@host:port/postgres
   ```
4. Initialize the database tables by running:
   ```bash
   python init_supabase.py
   ```

---

## 📧 Step 6: Email Finder Integration (Optional)

If you want the bot to automatically find recruiter emails, you need API keys for the email waterfall logic. Add these to your `.env` file:

- **Tomba.io**: Sign up for free credits and add `TOMBA_API_KEY` and `TOMBA_API_SECRET`.
- **Snov.io**: Sign up for free credits and add `SNOV_CLIENT_ID` and `SNOV_CLIENT_SECRET`.
- **Hunter.io**: Sign up for free credits and add `HUNTER_API_KEY`.
- **Zerobounce.net**: Sign up (requires business email) and add `ZEROBOUNCE_KEY`.

*To send emails directly via Gmail, ensure you have set up Gmail API OAuth credentials (`credentials.json`) in the project root.*

---

## 📄 Step 7: Creating Your Master Profile

The AI uses a `master_profile.json` file as the ground truth for your resume. You must create this file in the project root.

1. Create a file named `master_profile.json` in the root directory.
2. Structure it to contain your comprehensive details. Example structure:
   ```json
   {
     "basics": {
       "name": "Your Name",
       "role": "Your Target Role",
       "phone": "Your Phone",
       "email": "your.email@example.com",
       "profiles": {
         "linkedin": "...",
         "github": "..."
       }
     },
     "skills": {
       "languages": ["JavaScript", "Python"],
       "frameworks": ["React", "Node.js"]
     },
     "experience": [
       {
         "company": "Company Name",
         "role": "Software Engineer",
         "startDate": "Jan 2022",
         "endDate": "Present",
         "general_responsibilities": [
           "Comprehensive list of everything you did...",
           "The AI will cherry-pick relevant bullets from here..."
         ],
         "projects": [
           {
             "name": "Project Name",
             "tech_stack": ["React", "Node"],
             "impact_bullets": ["What you achieved..."]
           }
         ]
       }
     ],
     "education": [...]
   }
   ```
*Note: Make sure `resume_template.html` is present in the root directory. This acts as the visual template for your PDF output.*

---

## 💻 Step 8: Running Locally

Once everything is configured, start the bot:

```bash
python bot/bot.py
```
Open Telegram, go to your bot, and type `/start`. Then use `/tailor` to begin tailoring your resume!

---

## ☁️ Step 9: Deploying to Render (Free Tier)

If Render's Infrastructure as Code (Blueprint) with `render.yaml` causes billing prompts, you can deploy manually on the Free Tier using these steps:

1. Push your code to a private GitHub repository.
2. Create an account on [Render](https://render.com/).
3. Go to the Render Dashboard and click **New+ -> Web Service**.
4. Select **Build and deploy from a Git repository**.
5. Connect your GitHub account and select your repository.
6. Configure the service with the following settings:
   - **Name**: `resume-tailor-bot` (or any name)
   - **Region**: Choose the closest region
   - **Branch**: `main` (or your primary branch)
   - **Runtime**: `Docker` (This is crucial because the app requires both Python and Node.js)
   - **Instance Type**: Select **Free**
7. Expand the **Environment Variables** section and click **Add Environment Variable**. Add all the variables from your `.env` file one by one:
   - `TELEGRAM_BOT_TOKEN`
   - `ALLOWED_USER_ID`
   - `GEMINI_API_KEY`
   - `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REFRESH_TOKEN`, `DRIVE_FOLDER_ID`
   - `SUPABASE_DB_URL` (if configured)
   - Any optional Email API keys.
   - Also add `PORT` with the value `8080`.
8. Click **Create Web Service**.
9. Render will automatically build the Docker container and deploy the bot.
10. **Note**: The bot exposes a simple HTTP endpoint on `$PORT`. To prevent Render's free tier from spinning down due to inactivity, you can use a free service like [UptimeRobot](https://uptimerobot.com/) to ping your Render Web Service URL (e.g., `https://resume-tailor-bot.onrender.com/health`) every 14 minutes.
