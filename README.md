# 🚨 Smart Automated Notification & Alerts System

> **A production-grade Python automation pipeline that monitors any product page for price drops or stock changes — then fires instant alerts via SMS, Discord, or Telegram.**

[![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://python.org)
[![GitHub Actions](https://img.shields.io/badge/Scheduled_by-GitHub_Actions-2088FF?logo=githubactions&logoColor=white)](https://github.com/features/actions)
[![Twilio](https://img.shields.io/badge/SMS-Twilio-F22F46?logo=twilio&logoColor=white)](https://twilio.com)
[![Discord](https://img.shields.io/badge/Chat-Discord-5865F2?logo=discord&logoColor=white)](https://discord.com)
[![Telegram](https://img.shields.io/badge/Chat-Telegram-26A5E4?logo=telegram&logoColor=white)](https://telegram.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-22c55e.svg)](LICENSE)

---

## 📋 Table of Contents

- [Overview](#-overview)
- [Architecture](#-architecture)
- [Project Structure](#-project-structure)
- [Quick Start](#-quick-start)
- [Environment Variables](#-environment-variables)
- [Notification Channels](#-notification-channels)
- [GitHub Actions Setup](#-github-actions-setup)
- [Adding Repository Secrets](#-adding-repository-secrets)
- [Extending the System](#-extending-the-system)
- [Security Philosophy](#-security-philosophy)
- [Tech Stack](#-tech-stack)

---

## 🎯 Overview

This system solves a real-world problem: **manually checking a product page dozens of times a day is tedious and error-prone.** Instead, this pipeline runs on a schedule, scrapes the page silently, compares the result against your threshold, and pushes an instant notification the moment your criteria are met.

**Key highlights:**

| Feature | Implementation |
|---|---|
| User-agent rotation | Pool of 5 realistic browser strings, picked randomly per request |
| Retry logic | Exponential backoff, up to 3 attempts, skips unrecoverable 4xx errors |
| State tracking | JSON file persists last-known price/stock so only *changes* trigger alerts |
| Dual-mode notification | Broadcast to every configured channel simultaneously |
| Zero hardcoded secrets | All credentials live in `.env` (local) or GitHub Secrets (CI) |
| CI-native | Designed for GitHub Actions with artefact caching for state persistence |

---

## 🏗 Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        tracker.py  (orchestrator)               │
│                                                                 │
│  1. Load env vars & detect selector profile for the target URL  │
│  2. Restore previous state from .state.json                     │
│  3. Call scraper.py → get ProductSnapshot                       │
│  4. Compare snapshot against threshold & previous state         │
│  5. If alert triggered → call notifier.py → broadcast()        │
│  6. Persist new state                                           │
└───────────────┬──────────────────────┬──────────────────────────┘
                │                      │
                ▼                      ▼
   ┌────────────────────┐   ┌──────────────────────────────────┐
   │    scraper.py      │   │         notifier.py              │
   │                    │   │                                  │
   │  requests          │   │  Notifier.send_sms()   → Twilio │
   │  BeautifulSoup     │   │  Notifier.send_discord()→ Webhook│
   │  User-agent pool   │   │  Notifier.send_telegram()→ Bot  │
   │  Retry + backoff   │   │  Notifier.broadcast()  → all ✓  │
   │  Price parser      │   │                                  │
   └────────────────────┘   └──────────────────────────────────┘
                │
                ▼
   ┌────────────────────┐
   │   Target webpage   │
   │  (Amazon, BestBuy, │
   │   or any URL)      │
   └────────────────────┘
```

### Alert Decision Flow

```
Scrape snapshot
      │
      ├─ price ≤ PRICE_THRESHOLD  AND  price < last_known_price?  ──► 🚨 ALERT
      │
      └─ ALERT_ON_STOCK=true  AND  in_stock=True  AND  was False?  ──► 🚨 ALERT
                │
                └─ None of the above?  ──► 💤 No alert, update state
```

---

## 📁 Project Structure

```
smart-alert-system/
│
├── tracker.py                  # Orchestrator & CLI entry point
├── scraper.py                  # Web scraping module
├── notifier.py                 # Notification handlers (SMS / Discord / Telegram)
│
├── requirements.txt            # Pinned dependencies
├── .env.example                # Template for local credentials
├── .gitignore                  # Excludes .env, .state.json, __pycache__
│
└── .github/
    └── workflows/
        └── scheduled_run.yml   # GitHub Actions cron job
```

---

## ⚡ Quick Start

### 1 — Clone & install

```bash
git clone https://github.com/YOUR_HANDLE/smart-alert-system.git
cd smart-alert-system

python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

### 2 — Configure credentials

```bash
cp .env.example .env
# Open .env in your editor and fill in every value you need
```

### 3 — Run a dry-run first (no alerts sent)

```bash
python tracker.py --dry-run
```

### 4 — Run a live check

```bash
python tracker.py
```

### 5 — Run continuously (poll every hour)

```bash
python tracker.py --loop
# Override the interval: POLL_INTERVAL_SECONDS=1800 python tracker.py --loop
```

---

## 🔑 Environment Variables

Copy `.env.example` to `.env` and populate it. The table below explains every variable.

### Product settings

| Variable | Required | Example | Description |
|---|---|---|---|
| `TARGET_URL` | ✅ | `https://amazon.com/dp/B0...` | Full URL of the product page |
| `PRICE_THRESHOLD` | ⚠️* | `799.99` | Alert when price ≤ this value |
| `ALERT_ON_STOCK` | ⚠️* | `true` | Also alert on back-in-stock event |

*At least one alert condition must be enabled.

### Twilio (SMS)

| Variable | Description |
|---|---|
| `TWILIO_ACCOUNT_SID` | Found on your Twilio Console dashboard |
| `TWILIO_AUTH_TOKEN` | Found on your Twilio Console dashboard |
| `TWILIO_FROM_NUMBER` | Your Twilio phone number (E.164 format, e.g. `+15550001234`) |
| `TWILIO_TO_NUMBER` | Destination phone number |

### Discord

| Variable | Description |
|---|---|
| `DISCORD_WEBHOOK_URL` | Server Settings → Integrations → Webhooks → Copy URL |

### Telegram

| Variable | Description |
|---|---|
| `TELEGRAM_BOT_TOKEN` | From [@BotFather](https://t.me/BotFather) → `/newbot` |
| `TELEGRAM_CHAT_ID` | Your chat / channel ID (message [@userinfobot](https://t.me/userinfobot)) |

### Optional

| Variable | Default | Description |
|---|---|---|
| `STATE_FILE` | `.state.json` | Path for price/stock history |
| `POLL_INTERVAL_SECONDS` | `3600` | Seconds between checks in `--loop` mode |
| `LOG_LEVEL` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |

---

## 📣 Notification Channels

You can configure **one, two, or all three** channels simultaneously. The `Notifier.broadcast()` method automatically skips channels whose credentials are absent.

### Twilio SMS

```
🚨 PRICE ALERT — Sony WH-1000XM5

Price dropped to $279.99 (threshold: $299.99).

💰 Current price : $279.99
🎯 Your threshold: $299.99
📦 Availability: ✅ IN STOCK

🔗 https://www.amazon.com/dp/B09XS7JWHH
```

### Discord (Rich Embed)

The Discord notification renders as a colour-coded embed card with inline fields for current price, threshold, and availability status.

### Telegram

Same message format as SMS, delivered to your bot chat or channel.

---

## ⚙️ GitHub Actions Setup

The workflow file at `.github/workflows/scheduled_run.yml` runs the tracker **automatically at 09:00 UTC every day**.

### How it works

1. `actions/setup-python@v5` installs Python 3.12 and caches `pip` packages.
2. `actions/cache@v4` restores `.state.json` from the previous run — this is how price history persists across scheduled jobs.
3. All secrets are injected as environment variables via `env:` — they never appear in logs.
4. A dry-run option is available via **workflow_dispatch** for safe manual testing.
5. On job failure, a Discord webhook fires automatically to notify you.

### Triggering modes

| Trigger | How |
|---|---|
| Automatic (daily) | cron: `"0 9 * * *"` |
| Manual (any time) | Actions tab → `Smart Alert` → **Run workflow** |
| On push to `main` | Fires automatically when `.py` or workflow files change |

---

## 🔐 Adding Repository Secrets

> **This is the correct way to pass credentials into GitHub Actions. Never commit secrets to your code.**

1. Open your repository on GitHub.
2. Go to **Settings → Secrets and variables → Actions**.
3. Click **New repository secret** for each variable below:

```
TARGET_URL
PRICE_THRESHOLD
ALERT_ON_STOCK
TWILIO_ACCOUNT_SID
TWILIO_AUTH_TOKEN
TWILIO_FROM_NUMBER
TWILIO_TO_NUMBER
DISCORD_WEBHOOK_URL
TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID
```

4. Push your code — the workflow will pick them up automatically on the next run.

> 💡 **Tip:** You only need to add secrets for the channels you intend to use. Unused channels are gracefully skipped.

---

## 🧩 Extending the System

### Add a new retailer profile

Open `tracker.py` and add an entry to `SELECTOR_PROFILES`:

```python
SELECTOR_PROFILES["newegg"] = {
    "price_selector": "li.price-current strong",
    "title_selector": "h1.product-title",
    "stock_selector": "div.product-inventory",
    "in_stock_text": "in stock",
}
```

The URL auto-detection in `_detect_profile()` will pick it up automatically when `"newegg."` appears in the target URL.

### Add a new notification channel

1. Add a `send_slack()` (or similar) method to the `Notifier` class in `notifier.py`.
2. Register it in the `channels` dict inside `Notifier.broadcast()`.
3. Add the required env vars to `.env.example` and the GitHub Actions workflow.

### Add email via SendGrid

```python
# In notifier.py — send_email() sketch
import sendgrid
from sendgrid.helpers.mail import Mail

def send_email(self, payload: AlertPayload) -> None:
    api_key = self._require_env("SENDGRID_API_KEY")
    sg = sendgrid.SendGridAPIClient(api_key=api_key)
    message = Mail(
        from_email=self._require_env("EMAIL_FROM"),
        to_emails=self._require_env("EMAIL_TO"),
        subject=f"Price Alert: {payload.product_title}",
        plain_text_content=_build_message(payload),
    )
    sg.send(message)
```

---

## 🔒 Security Philosophy

| Principle | Implementation |
|---|---|
| **Zero hardcoded secrets** | All credentials via `os.environ` / `python-dotenv` |
| **`.env` never committed** | Enforced by `.gitignore` |
| **Least-privilege CI** | Workflow only requests `contents: write` |
| **No secret echoing** | `LOG_LEVEL=DEBUG` never prints credential values |
| **Dependency pinning** | Major versions pinned in `requirements.txt` |

---

## 🛠 Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.12 |
| HTTP client | `requests` 2.31+ |
| HTML parsing | `beautifulsoup4` 4.12+ with `lxml` backend |
| SMS | Twilio Python Helper Library 9.x |
| Chat | Discord Webhooks · Telegram Bot API (pure HTTP) |
| Config | `python-dotenv` 1.x |
| CI / Scheduling | GitHub Actions (Ubuntu latest, Python 3.12) |
| State persistence | JSON file + `actions/cache` |

---

## 📄 License

This project is licensed under the **MIT License**. See [LICENSE](LICENSE) for details.

---

<div align="center">

**Built with Python · Automated by GitHub Actions · Secured by environment variables**

*A portfolio project demonstrating real-world automation, API integration, and DevOps practices.*

</div>
