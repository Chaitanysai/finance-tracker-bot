import os
import json
import datetime
import logging
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

# ---------------------------
# LOGGING
# ---------------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# ---------------------------
# CONFIG: ENV VARIABLES
# ---------------------------
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
SHEET_ID = os.getenv("SHEET_ID")
GOOGLE_CREDENTIALS = os.getenv("GOOGLE_CREDENTIALS")
CHAT_ID = os.getenv("CHAT_ID")  # your Telegram ID for auto-summary

if not TELEGRAM_TOKEN or not SHEET_ID or not GOOGLE_CREDENTIALS:
    raise ValueError("❌ Missing required environment variables.")

# ---------------------------
# GOOGLE SHEETS SETUP
# ---------------------------
try:
    creds_dict = json.loads(GOOGLE_CREDENTIALS)
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
except Exception as e:
    raise ValueError(f"❌ Could not load Google credentials: {e}")

expenses_sheet = client.open_by_key(SHEET_ID).worksheet("Expenses")
earnings_sheet = client.open_by_key(SHEET_ID).worksheet("Earnings")

# ---------------------------
# HELPERS
# ---------------------------

def get_week_range(date):
    """Get Monday–Sunday range for the week of given date"""
    start = date - datetime.timedelta(days=date.weekday())  # Monday
    end = start + datetime.timedelta(days=6)                # Sunday
    return start, end

def safe_parse_date(date_str):
    """Try multiple formats for date parsing"""
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.datetime.strptime(date_str, fmt).date()
        except Exception:
            continue
    raise ValueError(f"Unrecognized date format: {date_str}")

def calculate_summary(week_start, week_end):
    """Calculate weekly earnings, expenses, balance"""
    # Earnings
    earnings_data = earnings_sheet.get_all_records()
    total_earnings = 0
    for row in earnings_data:
        try:
            row_date = safe_parse_date(row['Date'])
            if week_start <= row_date <= week_end:
                total_earnings += float(row['Amount'])
        except Exception as e:
            logging.error(f"Skipping earnings row {row}: {e}")

    # Expenses
    expenses_data = expenses_sheet.get_all_records()
    total_expenses = 0
    for row in expenses_data:
        try:
            row_date = safe_parse_date(row['Date'])
            if week_start <= row_date <= week_end:
                total_expenses += float(row['Amount'])
        except Exception as e:
            logging.error(f"Skipping expenses row {row}: {e}")

    balance = total_earnings - total_expenses
    return total_earnings, total_expenses, balance

# ---------------------------
# COMMANDS
# ---------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome to Finance Tracker!\n\n"
        "Commands:\n"
        "/spend <amount> <category> <notes>\n"
        "/earn <amount> <notes>\n"
        "/summary"
    )

async def spend(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(context.args[0])
        category = context.args[1]
        notes = " ".join(context.args[2:]) if len(context.args) > 2 else ""

        now = datetime.datetime.now()
        date = now.strftime("%Y-%m-%d")
        day = now.strftime("%A")

        expenses_sheet.append_row([date, day, category, amount, notes])
        await update.message.reply_text(f"✅ Expense logged: ₹{amount} ({category}) - {notes}")
    except Exception as e:
        logging.error(f"Error in /spend: {e}")
        await update.message.reply_text("⚠️ Usage: /spend <amount> <category> <notes>")

async def earn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(context.args[0])
        notes = " ".join(context.args[1:]) if len(context.args) > 1 else ""

        now = datetime.datetime.now()
        date = now.strftime("%Y-%m-%d")
        day = now.strftime("%A")

        earnings_sheet.append_row([date, day, amount, notes])
        await update.message.reply_text(f"✅ Earning logged: ₹{amount} - {notes}")
    except Exception as e:
        logging.error(f"Error in /earn: {e}")
        await update.message.reply_text("⚠️ Usage: /earn <amount> <notes>")

async def summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        today = datetime.date.today()
        week_start, week_end = get_week_range(today)
        earnings, expenses, balance = calculate_summary(week_start, week_end)

        await update.message.reply_text(
            f"📊 Weekly Summary ({week_start} → {week_end})\n"
            f"Earnings: ₹{earnings}\n"
            f"Expenses: ₹{expenses}\n"
            f"Balance Left: ₹{balance}"
        )
    except Exception as e:
        logging.error(f"Error in /summary: {e}")
        await update.message.reply_text("⚠️ Error while calculating summary.")

# ---------------------------
# AUTO SUMMARY (Every Monday 10AM IST)
# ---------------------------

async def send_weekly_summary(app: Application):
    try:
        today = datetime.date.today()
        last_week_end = today - datetime.timedelta(days=1)  # Sunday before today (Monday)
        week_start, week_end = get_week_range(last_week_end)
        earnings, expenses, balance = calculate_summary(week_start, week_end)

        await app.bot.send_message(
            chat_id=CHAT_ID,
            text=(
                f"📊 Weekly Summary ({week_start} → {week_end})\n"
                f"Earnings: ₹{earnings}\n"
                f"Expenses: ₹{expenses}\n"
                f"Balance Left: ₹{balance}"
            )
        )
    except Exception as e:
        logging.error(f"Error in auto-summary: {e}")

# ---------------------------
# MAIN
# ---------------------------

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("spend", spend))
    app.add_handler(CommandHandler("earn", earn))
    app.add_handler(CommandHandler("summary", summary))

    # Scheduler (runs every Monday 10AM IST)
    scheduler = AsyncIOScheduler(timezone=pytz.timezone("Asia/Kolkata"))
    scheduler.add_job(send_weekly_summary, CronTrigger(day_of_week="mon", hour=10, minute=0), args=[app])
    scheduler.start()

    app.run_polling()

if __name__ == "__main__":
    main()