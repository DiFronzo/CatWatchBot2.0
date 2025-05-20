# 🐾 CatWatchBot

CatWatchBot is a maintenance and statistics bot for Norwegian Wikipedia, designed to monitor, log, and report on various maintenance categories and templates. It helps keep track of articles needing cleanup, updates, sources, and more.

## 🚀 Features
- Tracks changes in key maintenance categories (e.g., cleanup, updates, interwiki, sources)
- Logs additions and removals of pages in these categories
- Updates statistics and generates reports for Wikipedia project pages
- Provides a ticker of recent maintenance actions
- Supports dry-run mode for safe testing
- Verbose logging for debugging

## 🛠️ Requirements
- Python 3
- Dependencies listed in `requirements.txt`
- A valid `vedlikehold.db` SQLite database (see `vedlikehold.sql` for schema)
- Environment variables for MediaWiki API credentials and email (see below)

## ⚙️ Setup
1. **Install dependencies:**
   ```sh
   pip install -r requirements.txt
   ```
2. **Set environment variables:**
   Create a `.env` file in the project root with the following (replace with your values):
   ```env
   MW_CONSUMER_TOKEN=your_token
   MW_CONSUMER_SECRET=your_secret
   MW_ACCESS_TOKEN=your_access_token
   MW_ACCESS_SECRET=your_access_secret
   MAIL_FROM=your@email.com
   MAIL_TO=admin@email.com
   ```
3. **Prepare the database:**
   Ensure `vedlikehold.db` exists and is initialized using `vedlikehold.sql`.

## 🏃 Usage
Run the bot with:
```sh
python catwatchbot.py [--simulate] [--verbose]
```
- `--simulate` : Run in dry-run mode (no changes will be written to Wikipedia)
- `--verbose`  : Enable debug output

Example:
```sh
python catwatchbot.py --simulate --verbose
```

## 🛠️ Deployment on Toolforge
TBA

## 📋 What It Does
- Updates maintenance statistics on Wikipedia project pages
- Logs changes in maintenance categories
- Tracks when templates are added or removed from articles
- Generates overview and ticker pages for easy review

## 📝 Notes
- The bot is tailored for Norwegian Wikipedia and may require adjustments for other wikis.
- Make sure your credentials and database are set up correctly before running.

---

Made by [Dan Michael](https://github.com/danmichaelo), maintained by [DiFronzo](https://github.com/DiFronzo).
