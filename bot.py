import os, time, threading, requests
from pymongo import MongoClient
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler

BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID"))
MONGO_URI = os.getenv("MONGO_URI")
SELF_PING_URL = os.getenv("SELF_PING_URL")

PING_INTERVAL = 120
RETRY_COUNT = 3
RETRY_DELAY = 10  # seconds

mongo = MongoClient(MONGO_URI)
db = mongo.uptimer
services = db.services
banned = db.banned

paused = False

# ---------- HELPERS ----------
def is_owner(uid): return uid == OWNER_ID
def is_banned(uid): return banned.find_one({"user_id": uid})

# ---------- COMMANDS ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_banned(update.effective_user.id): return
    await update.message.reply_text("🤖 Uptime Bot Active\n/add name url")

async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if is_banned(uid): return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /add name url")
        return

    services.insert_one({
        "user_id": uid,
        "name": context.args[0],
        "url": context.args[1],
        "status": "unknown",
        "down": False,
        "pings": 0,
        "fails": 0
    })
    await update.message.reply_text("✅ Service added")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    query = {} if is_owner(uid) else {"user_id": uid}
    data = list(services.find(query))

    if not data:
        await update.message.reply_text("No services")
        return

    msg = ""
    for i, s in enumerate(data, 1):
        icon = "🟢" if s["status"] == "up" else "🔴"
        msg += f"{i}. {icon} {s['name']}\n{s['url']}\n\n"

    await update.message.reply_text(msg)

async def list_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id): return
    rows = services.find()
    msg = ""
    for s in rows:
        msg += f"👤 {s['user_id']}\n{s['name']}\n{s['url']}\n\n"
    await update.message.reply_text(msg or "Empty")

async def remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not context.args: return
    name = context.args[0]

    if is_owner(uid):
        services.delete_many({"name": name})
    else:
        services.delete_one({"name": name, "user_id": uid})

    await update.message.reply_text("🗑 Removed")

async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id): return
    banned.insert_one({"user_id": int(context.args[0])})
    await update.message.reply_text("🚫 User banned")

async def unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id): return
    banned.delete_one({"user_id": int(context.args[0])})
    await update.message.reply_text("✅ User unbanned")

# ---------- PING LOGIC ----------
def ping_service(s):
    try:
        requests.get(s["url"], timeout=10)
        return True
    except:
        return False

def monitor():
    while True:
        if not paused:
            for s in services.find():
                if ping_service(s):
                    if s["down"]:
                        requests.post(
                            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                            json={"chat_id": OWNER_ID,
                                  "text": f"✅ RECOVERED\n{s['name']}\n{s['url']}"}
                        )
                    services.update_one({"_id": s["_id"]},
                        {"$set": {"status": "up", "down": False},
                         "$inc": {"pings": 1}})
                else:
                    recovered = False
                    for _ in range(RETRY_COUNT):
                        time.sleep(RETRY_DELAY)
                        if ping_service(s):
                            recovered = True
                            break

                    if not recovered:
                        if not s["down"]:
                            requests.post(
                                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                                json={"chat_id": OWNER_ID,
                                      "text": f"🚨 DOWN ALERT\n{s['name']}\n{s['url']}"}
                            )
                        services.update_one({"_id": s["_id"]},
                            {"$set": {"status": "down", "down": True},
                             "$inc": {"fails": 1}})

            try:
                requests.get(SELF_PING_URL, timeout=10)
            except:
                pass

        time.sleep(PING_INTERVAL)

# ---------- MAIN ----------
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add", add))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("list", list_all))
    app.add_handler(CommandHandler("remove", remove))
    app.add_handler(CommandHandler("ban", ban))
    app.add_handler(CommandHandler("unban", unban))

    threading.Thread(target=monitor, daemon=True).start()
    app.run_polling()

if __name__ == "__main__":
    main()
