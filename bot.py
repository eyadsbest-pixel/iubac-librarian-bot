"""
IUBAC Librarian Bot
A Telegram bot with a full dynamic admin dashboard and student file delivery.
"""
import json
import logging
import os
import uuid
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from dotenv import load_dotenv

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    BotCommand
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters
)

# ── Load environment ─────────────────────────────────────────────────────────
load_dotenv(override=True)
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is not set!")

SUPER_ADMIN = os.getenv("ADMIN_USERNAME")
if SUPER_ADMIN:
    SUPER_ADMIN = SUPER_ADMIN.replace("@", "").lower()

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ── Data Paths ───────────────────────────────────────────────────────────────
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
LECTURES_FILE = DATA_DIR / "lectures.json"
ADMINS_FILE = DATA_DIR / "admins.json"

# Ensure data files exist
if not LECTURES_FILE.exists():
    with open(LECTURES_FILE, "w", encoding="utf-8") as f:
        json.dump({"channel": "@iubac4medicin", "modules": []}, f, ensure_ascii=False, indent=2)

if not ADMINS_FILE.exists():
    with open(ADMINS_FILE, "w", encoding="utf-8") as f:
        json.dump({"admin_usernames": []}, f, ensure_ascii=False, indent=2)

def load_data():
    with open(LECTURES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_data(data):
    with open(LECTURES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_admins():
    with open(ADMINS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)["admin_usernames"]

def save_admins(admins_list):
    with open(ADMINS_FILE, "w", encoding="utf-8") as f:
        json.dump({"admin_usernames": admins_list}, f, ensure_ascii=False, indent=2)

def is_admin(username: str) -> bool:
    if not username:
        return False
    username = username.lower()
    if SUPER_ADMIN and username == SUPER_ADMIN:
        return True
    return username in [u.lower() for u in load_admins()]

# ── States ───────────────────────────────────────────────────────────────────
# Student States
STUDENT_MODULE = 1
STUDENT_SUBJECT = 2

# Admin States
A_MAIN = 10
A_ADD_MODULE_NAME = 11
A_PICK_MODULE_FOR_SUBJECT = 12
A_ADD_SUBJECT_NAME = 13
A_PICK_MODULE_FOR_LECTURE = 14
A_PICK_SUBJECT_FOR_LECTURE = 15
A_MANAGE_LECTURES = 16
A_WAIT_FOR_LECTURE_NAME = 17
A_WAIT_FOR_LECTURE_FILE = 18
A_MANAGE_ADMINS = 19
A_WAIT_FOR_ADMIN_USERNAME = 20

STUDENT_LECTURE = 3

BTN_BACK = "🔙 رجوع"
BTN_DONE = "✅ انتهيت"

# ── Admin Dashboard ──────────────────────────────────────────────────────────

async def admin_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    if not is_admin(user.username):
        await update.message.reply_text("⛔️ عذراً، هذا الأمر مخصص للمشرفين فقط.")
        return ConversationHandler.END

    keyboard = [
        [InlineKeyboardButton("📁 إدارة الموديولات (Modules)", callback_data="admin_modules")],
        [InlineKeyboardButton("📚 إدارة المواد (Subjects)", callback_data="admin_subjects")],
        [InlineKeyboardButton("📝 إدارة المحاضرات (Lectures)", callback_data="admin_lectures")],
        [InlineKeyboardButton("👥 إدارة المشرفين", callback_data="admin_admins")],
        [InlineKeyboardButton("❌ إغلاق لوحة التحكم", callback_data="admin_close")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = "🛠 *لوحة تحكم المشرف*\n\nاختر ما تريد القيام به:"
    
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")
    else:
        # Clear any reply keyboard just in case
        await update.message.reply_text("فتح لوحة التحكم...", reply_markup=ReplyKeyboardRemove())
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")
        
    return A_MAIN

async def admin_main_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "admin_close":
        await query.edit_message_text("تم إغلاق لوحة التحكم. ✅")
        return ConversationHandler.END
        
    elif data == "admin_modules":
        return await show_modules_menu(query, context)
        
    elif data == "admin_subjects":
        return await show_pick_module_for_subject(query, context)
        
    elif data == "admin_lectures":
        return await show_pick_module_for_lecture(query, context)
        
    elif data == "admin_admins":
        return await show_admins_menu(query, context)

    return A_MAIN

# -- Manage Modules --
async def show_modules_menu(query, context):
    db = load_data()
    keyboard = []
    for m in db["modules"]:
        keyboard.append([InlineKeyboardButton(f"🗑 حذف {m['name']}", callback_data=f"delmod_{m['id']}")])
        
    keyboard.append([InlineKeyboardButton("➕ إضافة موديول جديد", callback_data="add_module")])
    keyboard.append([InlineKeyboardButton(BTN_BACK, callback_data="back_main")])
    
    await query.edit_message_text("📁 *إدارة الموديولات*\n\nيمكنك إضافة موديول جديد أو حذف موديول حالي:", 
                                  reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
    return A_ADD_MODULE_NAME

async def admin_modules_actions_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "back_main":
        return await admin_start(update, context)
        
    elif data == "add_module":
        await query.edit_message_text("✏️ أرسل اسم الموديول الجديد الآن:\n(مثال: PNS - الجهاز العصبي الطّرفيّ)")
        return A_ADD_MODULE_NAME
        
    elif data.startswith("delmod_"):
        mod_id = data.split("_", 1)[1]
        db = load_data()
        db["modules"] = [m for m in db["modules"] if m["id"] != mod_id]
        save_data(db)
        return await show_modules_menu(query, context)
        
    return A_ADD_MODULE_NAME

async def receive_module_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    name = update.message.text
    db = load_data()
    mod_id = str(uuid.uuid4())[:8]
    db["modules"].append({
        "id": mod_id,
        "name": name,
        "name_short": name.split("-")[0].strip() if "-" in name else name,
        "subjects": []
    })
    save_data(db)
    
    keyboard = [[InlineKeyboardButton(BTN_BACK, callback_data="admin_modules")]]
    await update.message.reply_text(f"✅ تم إضافة الموديول: {name}", reply_markup=InlineKeyboardMarkup(keyboard))
    return A_ADD_MODULE_NAME

# -- Manage Subjects --
async def show_pick_module_for_subject(query, context):
    db = load_data()
    if not db["modules"]:
        keyboard = [[InlineKeyboardButton(BTN_BACK, callback_data="back_main")]]
        await query.edit_message_text("⚠️ لا يوجد موديولات بعد. أضف موديول أولاً.", reply_markup=InlineKeyboardMarkup(keyboard))
        return A_MAIN
        
    keyboard = []
    for m in db["modules"]:
        keyboard.append([InlineKeyboardButton(m['name'], callback_data=f"modsubj_{m['id']}")])
    keyboard.append([InlineKeyboardButton(BTN_BACK, callback_data="back_main")])
    
    await query.edit_message_text("📚 اختر الموديول الذي تريد إدارة مواده:", reply_markup=InlineKeyboardMarkup(keyboard))
    return A_PICK_MODULE_FOR_SUBJECT

async def pick_module_for_subject_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data == "back_main":
        return await admin_start(update, context)
        
    mod_id = data.split("_", 1)[1]
    context.user_data["selected_mod_id"] = mod_id
    
    db = load_data()
    module = next((m for m in db["modules"] if m["id"] == mod_id), None)
    
    if not module:
        return await show_pick_module_for_subject(query, context)

    keyboard = []
    for s in module["subjects"]:
        keyboard.append([InlineKeyboardButton(f"🗑 حذف {s['name']}", callback_data=f"delsubj_{s['id']}")])
        
    keyboard.append([InlineKeyboardButton("➕ إضافة مادة جديدة", callback_data="add_subject")])
    keyboard.append([InlineKeyboardButton(BTN_BACK, callback_data="admin_subjects")])
    
    await query.edit_message_text(f"📚 *إدارة مواد: {module['name']}*\n\nيمكنك إضافة أو حذف المواد:", 
                                  reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
    return A_ADD_SUBJECT_NAME

async def admin_subjects_actions_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data == "admin_subjects":
        return await show_pick_module_for_subject(query, context)
        
    elif data == "add_subject":
        await query.edit_message_text("✏️ أرسل اسم المادة الجديدة الآن:\n(مثال: Anatomy)")
        return A_ADD_SUBJECT_NAME
        
    elif data.startswith("delsubj_"):
        subj_id = data.split("_", 1)[1]
        mod_id = context.user_data["selected_mod_id"]
        db = load_data()
        for m in db["modules"]:
            if m["id"] == mod_id:
                m["subjects"] = [s for s in m["subjects"] if s["id"] != subj_id]
                break
        save_data(db)
        
        # Refresh the view
        query.data = f"modsubj_{mod_id}"
        return await pick_module_for_subject_cb(update, context)

    return A_ADD_SUBJECT_NAME

async def receive_subject_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    name = update.message.text
    mod_id = context.user_data["selected_mod_id"]
    
    db = load_data()
    subj_id = str(uuid.uuid4())[:8]
    for m in db["modules"]:
        if m["id"] == mod_id:
            m["subjects"].append({
                "id": subj_id,
                "name": name,
                "files": []
            })
            break
    save_data(db)
    
    keyboard = [[InlineKeyboardButton(BTN_BACK, callback_data=f"modsubj_{mod_id}")]]
    await update.message.reply_text(f"✅ تم إضافة المادة: {name}", reply_markup=InlineKeyboardMarkup(keyboard))
    return A_ADD_SUBJECT_NAME

# -- Manage Lectures --
async def show_pick_module_for_lecture(query, context):
    db = load_data()
    if not db["modules"]:
        keyboard = [[InlineKeyboardButton(BTN_BACK, callback_data="back_main")]]
        await query.edit_message_text("⚠️ لا يوجد موديولات بعد.", reply_markup=InlineKeyboardMarkup(keyboard))
        return A_MAIN
        
    keyboard = []
    for m in db["modules"]:
        keyboard.append([InlineKeyboardButton(m['name'], callback_data=f"upmod_{m['id']}")])
    keyboard.append([InlineKeyboardButton(BTN_BACK, callback_data="back_main")])
    
    await query.edit_message_text("📥 اختر الموديول:", reply_markup=InlineKeyboardMarkup(keyboard))
    return A_PICK_MODULE_FOR_LECTURE

async def pick_module_for_lecture_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data == "back_main":
        return await admin_start(update, context)
        
    mod_id = data.split("_", 1)[1]
    context.user_data["upload_mod_id"] = mod_id
    
    db = load_data()
    module = next((m for m in db["modules"] if m["id"] == mod_id), None)
    
    if not module["subjects"]:
        keyboard = [[InlineKeyboardButton(BTN_BACK, callback_data="admin_lectures")]]
        await query.edit_message_text("⚠️ لا يوجد مواد في هذا الموديول.", reply_markup=InlineKeyboardMarkup(keyboard))
        return A_PICK_MODULE_FOR_LECTURE
        
    keyboard = []
    for s in module["subjects"]:
        keyboard.append([InlineKeyboardButton(s['name'], callback_data=f"upsubj_{s['id']}")])
    keyboard.append([InlineKeyboardButton(BTN_BACK, callback_data="admin_lectures")])
    
    await query.edit_message_text("📥 اختر المادة لإدارة محاضراتها:", reply_markup=InlineKeyboardMarkup(keyboard))
    return A_PICK_SUBJECT_FOR_LECTURE

async def pick_subject_for_lecture_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data == "admin_lectures":
        return await show_pick_module_for_lecture(query, context)
        
    if data.startswith("upsubj_"):
        subj_id = data.split("_", 1)[1]
        context.user_data["upload_subj_id"] = subj_id
    else:
        subj_id = context.user_data["upload_subj_id"]
        
    db = load_data()
    mod_id = context.user_data["upload_mod_id"]
    module = next((m for m in db["modules"] if m["id"] == mod_id), None)
    subject = next((s for s in module["subjects"] if s["id"] == subj_id), None)
    
    keyboard = []
    if "lectures" not in subject:
        subject["lectures"] = []
        save_data(db)
        
    for l in subject.get("lectures", []):
        keyboard.append([InlineKeyboardButton(f"🗑 حذف: {l['name']}", callback_data=f"dellec_{l['id']}")])
        
    keyboard.append([InlineKeyboardButton("➕ إضافة محاضرة جديدة", callback_data="add_lecture")])
    keyboard.append([InlineKeyboardButton(BTN_BACK, callback_data=f"upmod_{mod_id}")])
    
    await query.edit_message_text(f"📝 إدارة المحاضرات في: {subject['name']}\nاختر خياراً:", reply_markup=InlineKeyboardMarkup(keyboard))
    return A_MANAGE_LECTURES

async def manage_lectures_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data.startswith("upmod_"):
        return await pick_module_for_lecture_cb(update, context)
        
    elif data == "add_lecture":
        await query.edit_message_text("✏️ أرسل اسم المحاضرة الجديدة الآن (مثال: Lec 1 - Intro):")
        return A_WAIT_FOR_LECTURE_NAME
        
    elif data.startswith("dellec_"):
        lec_id = data.split("_", 1)[1]
        db = load_data()
        mod_id = context.user_data["upload_mod_id"]
        subj_id = context.user_data["upload_subj_id"]
        module = next((m for m in db["modules"] if m["id"] == mod_id), None)
        subject = next((s for s in module["subjects"] if s["id"] == subj_id), None)
        
        subject["lectures"] = [l for l in subject["lectures"] if l["id"] != lec_id]
        save_data(db)
        return await pick_subject_for_lecture_cb(update, context)

async def receive_lecture_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lec_name = update.message.text
    lec_id = "l" + str(int(time.time()))
    
    db = load_data()
    mod_id = context.user_data["upload_mod_id"]
    subj_id = context.user_data["upload_subj_id"]
    module = next((m for m in db["modules"] if m["id"] == mod_id), None)
    subject = next((s for s in module["subjects"] if s["id"] == subj_id), None)
    
    new_lec = {
        "id": lec_id,
        "name": lec_name
    }
    subject["lectures"].append(new_lec)
    save_data(db)
    
    context.user_data["current_lec_id"] = lec_id
    
    markup = ReplyKeyboardMarkup([[BTN_DONE]], resize_keyboard=True)
    await update.message.reply_text(
        f"✅ تم إضافة محاضرة: {lec_name}\n\n"
        f"👉 قم الآن بإرسال (PDF) أو تسجيل صوتي (Record) أو كليهما.\n"
        f"عند الانتهاء، اضغط على '{BTN_DONE}'.",
        reply_markup=markup
    )
    return A_WAIT_FOR_LECTURE_FILE

async def receive_lecture_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.text == BTN_DONE:
        await update.message.reply_text("✅ تم الانتهاء من رفع الملفات.", reply_markup=ReplyKeyboardRemove())
        return await admin_start(update, context)
        
    lec_id = context.user_data["current_lec_id"]
    db = load_data()
    mod_id = context.user_data["upload_mod_id"]
    subj_id = context.user_data["upload_subj_id"]
    module = next((m for m in db["modules"] if m["id"] == mod_id), None)
    subject = next((s for s in module["subjects"] if s["id"] == subj_id), None)
    lecture = next((l for l in subject["lectures"] if l["id"] == lec_id), None)
    
    if update.message.document:
        lecture["pdf_file_id"] = update.message.document.file_id
        save_data(db)
        await update.message.reply_text("✅ تم حفظ ملف الـ PDF للمحاضرة.")
    elif update.message.audio:
        lecture["audio_file_id"] = update.message.audio.file_id
        save_data(db)
        await update.message.reply_text("✅ تم حفظ التسجيل الصوتي (Audio) للمحاضرة.")
    elif update.message.voice:
        lecture["audio_file_id"] = update.message.voice.file_id
        save_data(db)
        await update.message.reply_text("✅ تم حفظ التسجيل الصوتي (Voice) للمحاضرة.")
    else:
        await update.message.reply_text("⚠️ الرجاء إرسال ملف (PDF) أو تسجيل صوتي.")
        
    return A_WAIT_FOR_LECTURE_FILE

# -- Manage Admins --
async def show_admins_menu(query, context):
    admins = load_admins()
    keyboard = []
    for a in admins:
        keyboard.append([InlineKeyboardButton(f"🗑 حذف @{a}", callback_data=f"deladm_{a}")])
        
    keyboard.append([InlineKeyboardButton("➕ إضافة مشرف جديد", callback_data="add_admin")])
    keyboard.append([InlineKeyboardButton(BTN_BACK, callback_data="back_main")])
    
    await query.edit_message_text(f"👥 *إدارة المشرفين*\n\nالمشرف الأساسي: @{SUPER_ADMIN}\nالمشرفون الآخرون:", 
                                  reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
    return A_WAIT_FOR_ADMIN_USERNAME

async def admin_manage_admins_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data == "back_main":
        return await admin_start(update, context)
        
    elif data == "add_admin":
        await query.edit_message_text("✏️ أرسل معرّف المشرف الجديد الآن:\n(مثال: @username)")
        return A_WAIT_FOR_ADMIN_USERNAME
        
    elif data.startswith("deladm_"):
        adm = data.split("_", 1)[1]
        admins = load_admins()
        if adm in admins:
            admins.remove(adm)
            save_admins(admins)
        return await show_admins_menu(query, context)
        
    return A_WAIT_FOR_ADMIN_USERNAME

async def receive_admin_username(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text
    if not text:
        return A_WAIT_FOR_ADMIN_USERNAME
        
    username = text.replace("@", "").strip().lower()
    admins = load_admins()
    if username not in admins and username != SUPER_ADMIN:
        admins.append(username)
        save_admins(admins)
        
    keyboard = [[InlineKeyboardButton(BTN_BACK, callback_data="admin_admins")]]
    await update.message.reply_text(f"✅ تم إضافة المشرف: @{username}", reply_markup=InlineKeyboardMarkup(keyboard))
    return A_WAIT_FOR_ADMIN_USERNAME


async def cancel_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("تم الإلغاء.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


# ── Student Workflow ─────────────────────────────────────────────────────────

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point for students."""
    # Ensure they have a clean keyboard
    welcome = (
        "🔤 <b>بسم الله الرّحمن الرّحيم</b> 🔤\n\n"
        "📚 <b>أهلًا بك في بوت أمين مكتبة أيوباك!</b>\n"
        "أنا هنا لمساعدتك في الوصول إلى ملفات المحاضرات بسهولة.\n\n"
        "استخدم الأمر /menu لعرض القائمة."
    )
    await update.message.reply_text(welcome, parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    db = load_data()
    if not db["modules"]:
        await update.message.reply_text("⚠️ المكتبة فارغة حالياً.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END
        
    keyboard = []
    row = []
    for m in db["modules"]:
        row.append(m['name'])
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
        
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("🔽 <b>اختر الموديول:</b>", reply_markup=reply_markup, parse_mode="HTML")
    return STUDENT_MODULE

async def student_module_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text
    db = load_data()
    
    module = next((m for m in db["modules"] if m["name"] == text), None)
    
    if not module:
        await update.message.reply_text("⚠️ الرجاء اختيار موديول من القائمة المتاحة.")
        return STUDENT_MODULE
        
    context.user_data["selected_student_module"] = module["id"]
    
    if not module["subjects"]:
        keyboard = [["🔙 Go Back"]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text("⚠️ لا يوجد مواد في هذا الموديول.", reply_markup=reply_markup)
        return STUDENT_SUBJECT
        
    keyboard = []
    row = []
    for s in module["subjects"]:
        row.append(s['name'])
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
        
    keyboard.append(["🔙 Go Back"])
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(f"📋 <b>{module['name']}</b>\n\n🔽 اختر المادّة:", reply_markup=reply_markup, parse_mode="HTML")
    return STUDENT_SUBJECT

async def student_subject_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text
    
    if text == "🔙 Go Back":
        return await menu_command(update, context)
        
    mod_id = context.user_data.get("selected_student_module")
    db = load_data()
    module = next((m for m in db["modules"] if m["id"] == mod_id), None)
    
    if not module:
        return await menu_command(update, context)
        
    subject = next((s for s in module["subjects"] if s["name"] == text), None)
    
    if not subject:
        await update.message.reply_text("⚠️ الرجاء اختيار مادة من القائمة المتاحة.")
        return STUDENT_SUBJECT
    
    lectures = subject.get("lectures", [])
    
    if not lectures:
        await update.message.reply_text(f"⚠️ عذراً، لم يتم إضافة أي محاضرات لمادة {subject['name']} بعد.")
        return STUDENT_SUBJECT
        
    context.user_data["selected_student_subject"] = subject["id"]
        
    keyboard = []
    row = []
    for l in lectures:
        row.append(l['name'])
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
        
    keyboard.append(["🔙 Go Back"])
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(f"📚 <b>{subject['name']}</b>\n\n🔽 اختر المحاضرة:", reply_markup=reply_markup, parse_mode="HTML")
    return STUDENT_LECTURE

async def student_lecture_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text
    
    if text == "🔙 Go Back":
        # Simulate back to subjects
        mod_id = context.user_data.get("selected_student_module")
        db = load_data()
        module = next((m for m in db["modules"] if m["id"] == mod_id), None)
        keyboard = []
        row = []
        for s in module["subjects"]:
            row.append(s['name'])
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        keyboard.append(["🔙 Go Back"])
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text(f"📋 <b>{module['name']}</b>\n\n🔽 اختر المادّة:", reply_markup=reply_markup, parse_mode="HTML")
        return STUDENT_SUBJECT
        
    if text in ["📄 ملف المحاضرة", "🎙 تسجيل المحاضرة"]:
        # Delivery
        lec_id = context.user_data.get("selected_student_lecture")
        subj_id = context.user_data.get("selected_student_subject")
        mod_id = context.user_data.get("selected_student_module")
        db = load_data()
        module = next((m for m in db["modules"] if m["id"] == mod_id), None)
        subject = next((s for s in module["subjects"] if s["id"] == subj_id), None)
        lecture = next((l for l in subject["lectures"] if l["id"] == lec_id), None)
        
        if text == "📄 ملف المحاضرة":
            if lecture.get("pdf_file_id"):
                await update.message.reply_text("📤 جارِ إرسال الملف...")
                await context.bot.send_document(chat_id=update.effective_chat.id, document=lecture["pdf_file_id"])
            else:
                await update.message.reply_text("⚠️ لم يتم رفع ملف PDF لهذه المحاضرة.")
        elif text == "🎙 تسجيل المحاضرة":
            if lecture.get("audio_file_id"):
                await update.message.reply_text("📤 جارِ إرسال التسجيل الصوتي...")
                # It could be audio or voice, we just try audio, if it fails, voice
                try:
                    await context.bot.send_audio(chat_id=update.effective_chat.id, audio=lecture["audio_file_id"])
                except:
                    await context.bot.send_voice(chat_id=update.effective_chat.id, voice=lecture["audio_file_id"])
            else:
                await update.message.reply_text("⚠️ لم يتم رفع تسجيل صوتي لهذه المحاضرة.")
        return STUDENT_LECTURE
        
    # Otherwise it's a lecture name selection
    subj_id = context.user_data.get("selected_student_subject")
    mod_id = context.user_data.get("selected_student_module")
    db = load_data()
    module = next((m for m in db["modules"] if m["id"] == mod_id), None)
    subject = next((s for s in module["subjects"] if s["id"] == subj_id), None)
    
    lecture = next((l for l in subject["lectures"] if l["name"] == text), None)
    if not lecture:
        await update.message.reply_text("⚠️ الرجاء اختيار محاضرة من القائمة المتاحة.")
        return STUDENT_LECTURE
        
    context.user_data["selected_student_lecture"] = lecture["id"]
    
    keyboard = [
        ["📄 ملف المحاضرة", "🎙 تسجيل المحاضرة"],
        ["🔙 Go Back"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(f"📝 <b>{lecture['name']}</b>\n\n🔽 ماذا تريد؟", reply_markup=reply_markup, parse_mode="HTML")
    return STUDENT_LECTURE


# ── App Setup ────────────────────────────────────────────────────────────────
async def post_init(application: Application) -> None:
    commands = [
        BotCommand("start", "بدء البوت 🚀"),
        BotCommand("menu", "القائمة الرئيسيّة 📋"),
    ]
    if SUPER_ADMIN:
        commands.append(BotCommand("admin", "لوحة تحكم المشرفين 🛠"))
    await application.bot.set_my_commands(commands)
    logger.info("Bot commands set successfully.")

# ── Keep-Alive Web Server (for Render.com) ───────────────────────────────────
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"IUBAC Librarian Bot is alive!")
    def log_message(self, format, *args):
        pass  # Suppress noisy access logs

def start_keep_alive():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("", port), HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info(f"Keep-alive web server started on port {port}")

def self_ping():
    """Ping our own Render URL every 10 minutes to prevent spin-down."""
    import urllib.request
    render_url = os.environ.get("RENDER_EXTERNAL_URL")
    if not render_url:
        return  # Not on Render, skip
    while True:
        try:
            urllib.request.urlopen(render_url, timeout=10)
        except Exception:
            pass
        time.sleep(600)  # every 10 minutes

def main() -> None:
    logger.info("Starting IUBAC Librarian Bot (v2 Dynamic)...")

    # Start keep-alive server for Render
    start_keep_alive()
    # Start self-ping to prevent spin-down
    ping_thread = threading.Thread(target=self_ping, daemon=True)
    ping_thread.start()

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    admin_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("admin", admin_start)],
        states={
            A_MAIN: [CallbackQueryHandler(admin_main_cb)],
            A_ADD_MODULE_NAME: [
                CallbackQueryHandler(admin_modules_actions_cb),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_module_name)
            ],
            A_PICK_MODULE_FOR_SUBJECT: [CallbackQueryHandler(pick_module_for_subject_cb)],
            A_ADD_SUBJECT_NAME: [
                CallbackQueryHandler(admin_subjects_actions_cb),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_subject_name)
            ],
            A_PICK_MODULE_FOR_LECTURE: [CallbackQueryHandler(pick_module_for_lecture_cb)],
            A_PICK_SUBJECT_FOR_LECTURE: [CallbackQueryHandler(pick_subject_for_lecture_cb)],
            A_MANAGE_LECTURES: [CallbackQueryHandler(manage_lectures_cb)],
            A_WAIT_FOR_LECTURE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_lecture_name)],
            A_WAIT_FOR_LECTURE_FILE: [MessageHandler(filters.ALL & ~filters.COMMAND, receive_lecture_file)],
            A_MANAGE_ADMINS: [CallbackQueryHandler(admin_manage_admins_cb)],
            A_WAIT_FOR_ADMIN_USERNAME: [
                CallbackQueryHandler(admin_manage_admins_cb),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_admin_username)
            ]
        },
        fallbacks=[
            CommandHandler("cancel", cancel_admin), 
            CommandHandler("admin", admin_start),
            MessageHandler(filters.COMMAND, cancel_admin) # Any other command cancels admin mode
        ],
    )

    user_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("menu", menu_command)],
        states={
            STUDENT_MODULE: [MessageHandler(filters.TEXT & ~filters.COMMAND, student_module_handler)],
            STUDENT_SUBJECT: [MessageHandler(filters.TEXT & ~filters.COMMAND, student_subject_handler)],
            STUDENT_LECTURE: [MessageHandler(filters.TEXT & ~filters.COMMAND, student_lecture_handler)],
        },
        fallbacks=[CommandHandler("start", start_command), CommandHandler("menu", menu_command)],
    )

    app.add_handler(admin_conv_handler)
    app.add_handler(user_conv_handler)
    app.add_handler(CommandHandler("start", start_command))

    logger.info("Bot is running! Press Ctrl+C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == "__main__":
    main()
