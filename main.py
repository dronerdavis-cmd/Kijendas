import os
import sqlite3
import random
import string
import logging
from datetime import datetime

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    InputMediaPhoto
)

from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS","").split(",") if x]

logging.basicConfig(level=logging.INFO)


# ================= DATABASE =================

def db():

    return sqlite3.connect("bot.db")


def init_db():

    conn=db()
    c=conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS reports(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_code TEXT,
    user_id INTEGER,
    name TEXT,
    card TEXT,
    username TEXT,
    phone TEXT,
    amount TEXT,
    description TEXT,
    created_at TEXT
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS photos(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_code TEXT,
    file_id TEXT
    )
    """)

    conn.commit()
    conn.close()


# ================= HELPERS =================

def case_code():

    return "CASE-"+''.join(random.choices(string.digits,k=6))


def show(v):

    return v if v else "اطلاعات وارد نشده"


def review_text(d):

    return f"""
📄 پیش‌نویس گزارش

👤 نام: {show(d['name'])}

💳 شماره کارت: {show(d['card'])}

🆔 یوزرنیم: {show(d['username'])}

📞 تلفن: {show(d['phone'])}

💰 مبلغ کلاهبرداری: {show(d['amount'])}

📝 شرح گزارش:
{show(d['desc'])}

📎 مدارک: {len(d['photos'])}
"""


# ================= KEYBOARDS =================

def main_menu():

    return ReplyKeyboardMarkup(
        [
            ["📝 ثبت گزارش"],
            ["🔎 استعلام","👤 پنل کاربر"],
            ["ℹ️ راهنما"]
        ],
        resize_keyboard=True
    )


def report_keyboard(data):

    def m(x):

        return "✅ " if x else ""

    return ReplyKeyboardMarkup(
        [
            [f"{m(data['name'])}👤 نام",f"{m(data['card'])}💳 شماره کارت"],
            [f"{m(data['username'])}🆔 یوزرنیم",f"{m(data['phone'])}📞 تلفن"],
            [f"{m(data['amount'])}💰 مبلغ کلاهبرداری"],
            [f"{m(data['desc'])}📝 شرح گزارش"],
            [f"{'✅ ' if data['photos'] else ''}📎 ارسال مدارک"],
            ["✅ ثبت نهایی","❌ لغو"]
        ],
        resize_keyboard=True
    )


def search_keyboard():

    return ReplyKeyboardMarkup(
        [
            ["💳 شماره کارت","📞 تلفن"],
            ["👤 نام","🆔 یوزرنیم"],
            ["🔙 بازگشت"]
        ],
        resize_keyboard=True
    )


def help_keyboard():

    return ReplyKeyboardMarkup(
        [
            ["📘 آموزش استفاده"],
            ["📩 ارتباط با ادمین"],
            ["🔙 بازگشت"]
        ],
        resize_keyboard=True
    )


# ================= START =================

async def start(update:Update,context:ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "به سامانه گزارش کلاهبرداری خوش آمدید",
        reply_markup=main_menu()
    )


# ================= REPORT =================

async def start_report(update,context):

    context.user_data["report"]={
        "name":None,
        "card":None,
        "username":None,
        "phone":None,
        "amount":None,
        "desc":None,
        "photos":[]
    }

    review=await update.message.reply_text(
        review_text(context.user_data["report"])
    )

    context.user_data["review"]=review.message_id

    await update.message.reply_text(
        "بخش مورد نظر را انتخاب کنید",
        reply_markup=report_keyboard(context.user_data["report"])
    )


# انتخاب فیلد

async def choose_field(update,context):

    msg=update.message.text

    try:
        await update.message.delete()
    except:
        pass

    mapping={
        "👤 نام":("name","نام کامل را وارد کنید"),
        "💳 شماره کارت":("card","شماره کارت ۱۶ رقمی را وارد کنید"),
        "🆔 یوزرنیم":("username","یوزرنیم تلگرام را وارد کنید"),
        "📞 تلفن":("phone","شماره تلفن را وارد کنید"),
        "💰 مبلغ کلاهبرداری":("amount","مبلغ را وارد کنید"),
        "📝 شرح گزارش":("desc","شرح کامل را بنویسید")
    }

    for k in mapping:

        if k in msg:

            field,question=mapping[k]

            p=await context.bot.send_message(
                update.effective_chat.id,
                question
            )

            context.user_data["waiting"]=field
            context.user_data["prompt"]=p.message_id


# دریافت مقدار

async def receive_value(update,context):

    if "waiting" not in context.user_data:
        return

    field=context.user_data["waiting"]

    context.user_data["report"][field]=update.message.text

    await update.message.delete()

    try:
        await context.bot.delete_message(
            update.effective_chat.id,
            context.user_data["prompt"]
        )
    except:
        pass

    await context.bot.edit_message_text(
        review_text(context.user_data["report"]),
        update.effective_chat.id,
        context.user_data["review"]
    )

    await context.bot.send_message(
        update.effective_chat.id,
        "ادامه فرم:",
        reply_markup=report_keyboard(context.user_data["report"])
    )

    context.user_data["waiting"]=None


# دریافت عکس

async def receive_photo(update,context):

    if "report" not in context.user_data:
        return

    fid=update.message.photo[-1].file_id

    context.user_data["report"]["photos"].append(fid)

    await update.message.delete()

    await context.bot.edit_message_text(
        review_text(context.user_data["report"]),
        update.effective_chat.id,
        context.user_data["review"]
    )


# ثبت نهایی

async def finalize(update,context):

    data=context.user_data["report"]

    code=case_code()

    conn=db()
    c=conn.cursor()

    c.execute("""
    INSERT INTO reports
    (case_code,user_id,name,card,username,phone,amount,description,created_at)
    VALUES (?,?,?,?,?,?,?,?,?)
    """,
    (
        code,
        update.effective_user.id,
        data["name"],
        data["card"],
        data["username"],
        data["phone"],
        data["amount"],
        data["desc"],
        datetime.now().isoformat()
    ))

    for p in data["photos"]:

        c.execute(
            "INSERT INTO photos(case_code,file_id) VALUES (?,?)",
            (code,p)
        )

    conn.commit()
    conn.close()

    text=f"""
✅ گزارش ثبت شد

شماره پرونده:
`{code}`

👤 نام: {show(data['name'])}
💳 کارت: {show(data['card'])}
🆔 یوزرنیم: {show(data['username'])}
📞 تلفن: {show(data['phone'])}
💰 مبلغ: {show(data['amount'])}

📝 شرح:
{show(data['desc'])}
"""

    await context.bot.delete_message(
        update.effective_chat.id,
        context.user_data["review"]
    )

    if data["photos"]:

        media=[InputMediaPhoto(data["photos"][0],caption=text,parse_mode="Markdown")]

        for p in data["photos"][1:10]:

            media.append(InputMediaPhoto(p))

        await context.bot.send_media_group(update.effective_chat.id,media)

    else:

        await update.message.reply_text(text,parse_mode="Markdown")

    await update.message.reply_text(
        "گزارش با موفقیت ثبت شد",
        reply_markup=main_menu()
    )


# ================= SEARCH =================

async def start_search(update,context):

    await update.message.reply_text(
        "روش استعلام را انتخاب کنید",
        reply_markup=search_keyboard()
    )


async def do_search(update,context):

    field_map={
        "💳 شماره کارت":"card",
        "📞 تلفن":"phone",
        "👤 نام":"name",
        "🆔 یوزرنیم":"username"
    }

    msg=update.message.text

    if msg not in field_map:
        return

    context.user_data["search_field"]=field_map[msg]

    await update.message.reply_text("مقدار را وارد کنید")


async def search_value(update,context):

    if "search_field" not in context.user_data:
        return

    val=update.message.text

    conn=db()
    c=conn.cursor()

    c.execute(
        f"SELECT * FROM reports WHERE {context.user_data['search_field']}=?",
        (val,)
    )

    rows=c.fetchall()

    if not rows:

        await update.message.reply_text("گزارشی یافت نشد")
        return

    total=len(rows)

    sum_amount=0

    for r in rows:

        try:
            sum_amount+=int(r[7])
        except:
            pass

    if total==1:
        risk="کم"
    elif total<=3:
        risk="متوسط"
    else:
        risk="بالا"

    await update.message.reply_text(
        f"""
⚠️ نتیجه استعلام

تعداد گزارش‌ها: {total}

مجموع مبالغ گزارش شده:
{sum_amount}

سطح ریسک:
{risk}
"""
    )


# ================= USER PANEL =================

async def user_panel(update,context):

    uid=update.effective_user.id

    conn=db()
    c=conn.cursor()

    c.execute("SELECT case_code FROM reports WHERE user_id=?",(uid,))

    rows=c.fetchall()

    if not rows:

        await update.message.reply_text("گزارشی ندارید")
        return

    txt="گزارش‌های شما:\n\n"

    for r in rows:

        txt+=r[0]+"\n"

    await update.message.reply_text(txt)


# ================= HELP =================

async def help_menu(update,context):

    await update.message.reply_text(
        "بخش راهنما",
        reply_markup=help_keyboard()
    )


# ================= MAIN =================

def main():

    init_db()

    app=Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start",start))

    app.add_handler(MessageHandler(filters.Regex("^📝 ثبت گزارش$"),start_report))

    app.add_handler(MessageHandler(filters.Regex("^(👤 نام|💳 شماره کارت|🆔 یوزرنیم|📞 تلفن|💰 مبلغ کلاهبرداری|📝 شرح گزارش)"),choose_field))

    app.add_handler(MessageHandler(filters.Regex("^✅ ثبت نهایی$"),finalize))

    app.add_handler(MessageHandler(filters.Regex("^🔎 استعلام$"),start_search))

    app.add_handler(MessageHandler(filters.Regex("^(💳 شماره کارت|📞 تلفن|👤 نام|🆔 یوزرنیم)$"),do_search))

    app.add_handler(MessageHandler(filters.Regex("^👤 پنل کاربر$"),user_panel))

    app.add_handler(MessageHandler(filters.Regex("^ℹ️ راهنما$"),help_menu))

    app.add_handler(MessageHandler(filters.PHOTO,receive_photo))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,receive_value))

    app.run_polling()


if __name__=="__main__":
    main()
