# 📚 IUBAC Librarian Bot — بوت أمين مكتبة أيوباك

A Telegram bot that acts as a librarian for the `@iubac4medicin` channel, providing navigable menus to browse medical lectures by system/module and subject.

## Features

- 🧭 **Interactive Menu Navigation** — Browse through modules and subjects using inline keyboards
- 📤 **Direct Lecture Forwarding** — The bot forwards lecture posts with all clickable links preserved
- 🔗 **Fallback Links** — If forwarding fails, sends direct `t.me` links instead
- 🇸🇦 **Arabic Interface** — Fully Arabic UI for IUBAC students
- 📱 **Telegram Bot Commands** — `/start`, `/menu`, `/help`

## Modules Covered

| Module | Arabic Name | Subjects |
|--------|------------|----------|
| 🧠 PNS | الجهاز العصبي الطرفي | 9 subjects |
| 🩸 HLS | الجهاز الدموي اللمفاوي | 8 subjects |
| 🔺 UGS | الجهاز البولي التناسلي | 9 subjects |

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Bot Token

Copy the example env file and add your bot token:

```bash
cp .env.example .env
# Edit .env and add your BOT_TOKEN from @BotFather
```

### 3. Run Locally

```bash
python bot.py
```

## Deployment (24/7 hosting)

### Option A: Railway (Recommended)

1. Push to a GitHub repository
2. Go to [railway.app](https://railway.app)
3. Create a new project → Deploy from GitHub
4. Add environment variable: `BOT_TOKEN=your_token_here`
5. Railway auto-detects the `Procfile` and deploys

### Option B: Render

1. Push to a GitHub repository
2. Go to [render.com](https://render.com)
3. Create a **Background Worker** (not a Web Service)
4. Add environment variable: `BOT_TOKEN=your_token_here`
5. Set build command: `pip install -r requirements.txt`
6. Set start command: `python bot.py`

### Option C: PythonAnywhere

1. Upload files to PythonAnywhere
2. Create an Always-On Task: `python /home/yourname/iubac-librarian-bot/bot.py`
3. Set environment variable in `.env` file

## Updating Lecture Data

Edit `data/lectures.json` to add/modify modules, subjects, or message IDs. The structure is:

```json
{
  "channel": "@iubac4medicin",
  "modules": [
    {
      "id": "module_id",
      "name": "Display name with emoji",
      "name_short": "SHORT",
      "collection_post_id": 1234,
      "subjects": [
        {
          "id": "unique_subject_id",
          "name": "💫 Subject Name",
          "message_id": 5678
        }
      ]
    }
  ]
}
```

## License

MIT — Built for IUBAC Medicine students 🌷
