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
TRASH_FILE = DATA_DIR / "trash.json"

# ── GitHub-backed Storage ────────────────────────────────────────────────────
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO = os.getenv("GITHUB_REPO")  # e.g. "eyadsbest-pixel/iubac-librarian-bot"

def _github_headers():
    return {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }

def _github_download(file_path: str):
    """Download a file from the GitHub repo."""
    import urllib.request, base64
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{file_path}"
    req = urllib.request.Request(url, headers=_github_headers())
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            content = base64.b64decode(data["content"]).decode("utf-8")
            return json.loads(content), data["sha"]
    except Exception as e:
        logger.warning(f"GitHub download failed for {file_path}: {e}")
        return None, None

def _github_upload(file_path: str, data_dict: dict, message: str):
    """Upload/update a file in the GitHub repo."""
    import urllib.request, base64
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{file_path}"
    
    # Get current SHA first
    _, sha = _github_download(file_path)
    
    content_bytes = json.dumps(data_dict, ensure_ascii=False, indent=2).encode("utf-8")
    body = {
        "message": message,
        "content": base64.b64encode(content_bytes).decode("ascii"),
    }
    if sha:
        body["sha"] = sha
    
    body_bytes = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=body_bytes, headers=_github_headers(), method="PUT")
    try:
        urllib.request.urlopen(req, timeout=15)
        logger.info(f"Saved {file_path} to GitHub.")
    except Exception as e:
        logger.error(f"GitHub upload failed for {file_path}: {e}")

def _init_data_files():
    """On startup, download data from GitHub if available, otherwise use local/defaults."""
    default_lectures = {"channel": "@iubac4medicin", "modules": []}
    default_admins = {"admin_usernames": []}
    
    if GITHUB_TOKEN and GITHUB_REPO:
        logger.info("GitHub storage enabled. Downloading data...")
        
        lec_data, _ = _github_download("data/lectures.json")
        if lec_data:
            with open(LECTURES_FILE, "w", encoding="utf-8") as f:
                json.dump(lec_data, f, ensure_ascii=False, indent=2)
            logger.info("Downloaded lectures.json from GitHub.")
        elif not LECTURES_FILE.exists():
            with open(LECTURES_FILE, "w", encoding="utf-8") as f:
                json.dump(default_lectures, f, ensure_ascii=False, indent=2)
        
        adm_data, _ = _github_download("data/admins.json")
        if adm_data:
            with open(ADMINS_FILE, "w", encoding="utf-8") as f:
                json.dump(adm_data, f, ensure_ascii=False, indent=2)
            logger.info("Downloaded admins.json from GitHub.")
        elif not ADMINS_FILE.exists():
            with open(ADMINS_FILE, "w", encoding="utf-8") as f:
                json.dump(default_admins, f, ensure_ascii=False, indent=2)
                
        trash_data, _ = _github_download("data/trash.json")
        if trash_data:
            with open(TRASH_FILE, "w", encoding="utf-8") as f:
                json.dump(trash_data, f, ensure_ascii=False, indent=2)
            logger.info("Downloaded trash.json from GitHub.")
        elif not TRASH_FILE.exists():
            with open(TRASH_FILE, "w", encoding="utf-8") as f:
                json.dump([], f, ensure_ascii=False, indent=2)
    else:
        logger.info("GitHub storage not configured. Using local files only.")
        if not LECTURES_FILE.exists():
            with open(LECTURES_FILE, "w", encoding="utf-8") as f:
                json.dump(default_lectures, f, ensure_ascii=False, indent=2)
        if not ADMINS_FILE.exists():
            with open(ADMINS_FILE, "w", encoding="utf-8") as f:
                json.dump(default_admins, f, ensure_ascii=False, indent=2)
        if not TRASH_FILE.exists():
            with open(TRASH_FILE, "w", encoding="utf-8") as f:
                json.dump([], f, ensure_ascii=False, indent=2)

_init_data_files()

def load_data():
    with open(LECTURES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_data(data):
    with open(LECTURES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    # Also push to GitHub in background
    if GITHUB_TOKEN and GITHUB_REPO:
        t = threading.Thread(target=_github_upload, args=("data/lectures.json", data, "Update lectures data"), daemon=True)
        t.start()

def load_admins():
    with open(ADMINS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)["admin_usernames"]

def save_admins(admins_list):
    data = {"admin_usernames": admins_list}
    with open(ADMINS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    if GITHUB_TOKEN and GITHUB_REPO:
        t = threading.Thread(target=_github_upload, args=("data/admins.json", data, "Update admins data"), daemon=True)
        t.start()

def load_trash():
    if not TRASH_FILE.exists():
        return []
    with open(TRASH_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_trash(data):
    with open(TRASH_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    if GITHUB_TOKEN and GITHUB_REPO:
        t = threading.Thread(target=_github_upload, args=("data/trash.json", data, "Update trash data"), daemon=True)
        t.start()

def trash_item(item_type, data, parent_id=None):
    trash = load_trash()
    trash.insert(0, {
        "trash_id": str(uuid.uuid4())[:8],
        "type": item_type,
        "parent_id": parent_id,
        "data": data,
        "deleted_at": int(time.time())
    })
    save_trash(trash)

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
A_MANAGE_TRASH = 21

STUDENT_LECTURE = 3

BTN_BACK = "🔙 رجوع"
BTN_DONE = "✅ انتهيت"

# ── Admin Dashboard ──────────────────────────────────────────────────────────

async def admin_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    if not is_admin(user.username):
        if update.callback_query:
            await update.callback_query.answer("⛔️ عذراً، هذا الأمر مخصص للمشرفين فقط.", show_alert=True)
        else:
            await update.message.reply_text("⛔️ عذراً، هذا الأمر مخصص للمشرفين فقط.")
        return ConversationHandler.END

    keyboard = [
        [InlineKeyboardButton("📁 إدارة الموديولات (Modules)", callback_data="admin_modules")],
        [InlineKeyboardButton("📚 إدارة المواد (Subjects)", callback_data="admin_subjects")],
        [InlineKeyboardButton("📝 إدارة المحاضرات (Lectures)", callback_data="admin_lectures")],
        [InlineKeyboardButton("👥 إدارة المشرفين", callback_data="admin_admins")],
        [InlineKeyboardButton("🗑 سلة المحذوفات", callback_data="admin_trash")],
        [InlineKeyboardButton("❌ إغلاق لوحة التحكم", callback_data="admin_close")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = "🛠 <b>لوحة تحكم المشرف</b>\n\nاختر ما تريد القيام به:"
    
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
        
    elif data == "admin_trash":
        return await show_trash_menu(query, context)

    return A_MAIN

# -- Manage Trash --
async def show_trash_menu(query, context):
    trash = load_trash()
    keyboard = []
    
    # Show last 10 items to avoid payload too large
    for t in trash[:10]:
        t_type = t["type"]
        t_id = t["trash_id"]
        if t_type == "module":
            name = f"موديول: {t['data']['name']}"
        elif t_type == "subject":
            name = f"مادة: {t['data']['name']}"
        elif t_type == "lecture":
            name = f"محاضرة: {t['data']['name']}"
        else:
            name = f"ملف: {t_type}"
            
        keyboard.append([
            InlineKeyboardButton(f"♻️ استعادة {name}", callback_data=f"restore_{t_id}")
        ])
        keyboard.append([
            InlineKeyboardButton(f"❌ حذف نهائي {name}", callback_data=f"perma_{t_id}")
        ])
        
    keyboard.append([InlineKeyboardButton(BTN_BACK, callback_data="back_main")])
    
    text = "🗑 <b>سلة المحذوفات</b>\n\nأحدث العناصر المحذوفة:" if trash else "🗑 <b>سلة المحذوفات</b>\n\nالسلة فارغة."
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
    return A_MANAGE_TRASH

async def admin_trash_actions_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data == "back_main":
        return await admin_start(update, context)
        
    trash = load_trash()
    
    if data.startswith("perma_"):
        t_id = data.split("_", 1)[1]
        trash = [t for t in trash if t["trash_id"] != t_id]
        save_trash(trash)
        return await show_trash_menu(query, context)
        
    elif data.startswith("restore_"):
        t_id = data.split("_", 1)[1]
        t_item = next((t for t in trash if t["trash_id"] == t_id), None)
        if not t_item:
            await query.answer("لم يتم العثور على العنصر.", show_alert=True)
            return await show_trash_menu(query, context)
            
        db = load_data()
        success = False
        if t_item["type"] == "module":
            db["modules"].append(t_item["data"])
            success = True
        elif t_item["type"] == "subject":
            mod_id = t_item["parent_id"]
            module = next((m for m in db["modules"] if m["id"] == mod_id), None)
            if module:
                module["subjects"].append(t_item["data"])
                success = True
            else:
                await query.answer("خطأ: الموديول الأصلي غير موجود! استعد الموديول أولاً.", show_alert=True)
        elif t_item["type"] == "lecture":
            subj_id = t_item["parent_id"]
            subject = None
            for m in db["modules"]:
                subject = next((s for s in m["subjects"] if s["id"] == subj_id), None)
                if subject: break
            if subject:
                if "lectures" not in subject: subject["lectures"] = []
                subject["lectures"].append(t_item["data"])
                success = True
            else:
                await query.answer("خطأ: المادة الأصلية غير موجودة! استعد المادة أولاً.", show_alert=True)
        elif t_item["type"].startswith("file_"):
            lec_id = t_item["parent_id"]
            lecture = None
            for m in db["modules"]:
                for s in m["subjects"]:
                    lecture = next((l for l in s.get("lectures", []) if l["id"] == lec_id), None)
                    if lecture: break
                if lecture: break
            if lecture:
                target_field = "audio_file_id" if t_item["type"] == "file_audio" else "pdf_file_id"
                lecture[target_field] = t_item["data"]
                success = True
            else:
                await query.answer("خطأ: المحاضرة الأصلية غير موجودة! استعد المحاضرة أولاً.", show_alert=True)
                
        if success:
            trash = [t for t in trash if t["trash_id"] != t_id]
            save_trash(trash)
            save_data(db)
            await query.answer("تمت الاستعادة بنجاح!", show_alert=True)
        return await show_trash_menu(query, context)

    return A_MANAGE_TRASH

# -- Manage Modules --
async def show_modules_menu(query, context):
    db = load_data()
    keyboard = []
    for m in db["modules"]:
        keyboard.append([InlineKeyboardButton(f"🗑 حذف {m['name']}", callback_data=f"delmod_{m['id']}")])
        
    keyboard.append([InlineKeyboardButton("➕ إضافة موديول جديد", callback_data="add_module")])
    keyboard.append([InlineKeyboardButton(BTN_BACK, callback_data="back_main")])
    
    await query.edit_message_text("📁 <b>إدارة الموديولات</b>\n\nيمكنك إضافة موديول جديد أو حذف موديول حالي:", 
                                  reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
    return A_ADD_MODULE_NAME

async def admin_modules_actions_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "back_main":
        return await admin_start(update, context)
        
    elif data == "admin_modules":
        return await show_modules_menu(query, context)
        
    elif data == "add_module":
        await query.edit_message_text("✏️ أرسل اسم الموديول الجديد الآن:\n(مثال: PNS - الجهاز العصبي الطّرفيّ)")
        return A_ADD_MODULE_NAME
        
    elif data.startswith("delmod_"):
        mod_id = data.split("_", 1)[1]
        db = load_data()
        mod_to_delete = next((m for m in db["modules"] if m["id"] == mod_id), None)
        if mod_to_delete:
            trash_item("module", mod_to_delete)
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
    
    await query.edit_message_text(f"📚 <b>إدارة مواد: {module['name']}</b>\n\nيمكنك إضافة أو حذف المواد:", 
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
                subj_to_delete = next((s for s in m["subjects"] if s["id"] == subj_id), None)
                if subj_to_delete:
                    trash_item("subject", subj_to_delete, parent_id=mod_id)
                m["subjects"] = [s for s in m["subjects"] if s["id"] != subj_id]
                break
        save_data(db)
        
        # Refresh the view
        query.data = f"modsubj_{mod_id}"
        return await pick_module_for_subject_cb(update, context)

    elif data.startswith("modsubj_"):
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
        keyboard.append([InlineKeyboardButton(f"📖 {l['name']}", callback_data=f"viewlec_{l['id']}")])
        
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
        
    elif data.startswith("viewlec_"):
        lec_id = data.split("_", 1)[1]
        context.user_data["current_lec_id"] = lec_id
        db = load_data()
        mod_id = context.user_data["upload_mod_id"]
        subj_id = context.user_data["upload_subj_id"]
        module = next((m for m in db["modules"] if m["id"] == mod_id), None)
        subject = next((s for s in module["subjects"] if s["id"] == subj_id), None)
        lecture = next((l for l in subject["lectures"] if l["id"] == lec_id), None)
        
        keyboard = [
            [
                InlineKeyboardButton("➕ تسجيل", callback_data=f"addrec_{lecture['id']}"),
                InlineKeyboardButton("🗑 تسجيل", callback_data=f"delrec_{lecture['id']}")
            ],
            [
                InlineKeyboardButton("➕ ملف", callback_data=f"addpdf_{lecture['id']}"),
                InlineKeyboardButton("🗑 ملف", callback_data=f"delpdf_{lecture['id']}")
            ],
            [
                InlineKeyboardButton("➕ ملخص", callback_data=f"addsum_{lecture['id']}"),
                InlineKeyboardButton("🗑 ملخص", callback_data=f"delsum_{lecture['id']}")
            ],
            [
                InlineKeyboardButton("➕ تبييض", callback_data=f"addnot_{lecture['id']}"),
                InlineKeyboardButton("🗑 تبييض", callback_data=f"delnot_{lecture['id']}")
            ],
            [InlineKeyboardButton("🗑 حذف المحاضرة كاملة", callback_data=f"dellec_{lecture['id']}")],
            [InlineKeyboardButton("🔙 رجوع للقائمة", callback_data=f"upsubj_{subj_id}")]
        ]
        await query.edit_message_text(f"📝 إدارة المحاضرة: {lecture['name']}\nاختر خياراً:", reply_markup=InlineKeyboardMarkup(keyboard))
        return A_MANAGE_LECTURES
        
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
        if subject:
            lec_to_delete = next((l for l in subject.get("lectures", []) if l["id"] == lec_id), None)
            if lec_to_delete:
                trash_item("lecture", lec_to_delete, parent_id=subj_id)
                subject["lectures"] = [l for l in subject.get("lectures", []) if l["id"] != lec_id]
                save_data(db)
        return await pick_subject_for_lecture_cb(update, context)
        
    elif data.startswith("addrec_") or data.startswith("addpdf_") or data.startswith("addsum_") or data.startswith("addnot_"):
        action, lec_id = data.split("_", 1)
        context.user_data["current_lec_id"] = lec_id
        
        target_map = {
            "addrec": "audio_file_id",
            "addpdf": "pdf_file_id",
            "addsum": "summary_file_id",
            "addnot": "notes_file_id"
        }
        context.user_data["upload_target"] = target_map[action]
        
        msg_map = {
            "addrec": "أرسل التسجيل الآن (أي نوع ملف):",
            "addpdf": "أرسل ملف الـ PDF الآن:",
            "addsum": "أرسل ملف الملخص الآن:",
            "addnot": "أرسل ملف التبييض الآن:"
        }
        msg = msg_map[action]
        markup = ReplyKeyboardMarkup([[BTN_DONE]], resize_keyboard=True)
        await query.message.reply_text(f"👉 {msg}\nعند الانتهاء، اضغط على '{BTN_DONE}'.", reply_markup=markup)
        return A_WAIT_FOR_LECTURE_FILE
        
    elif data.startswith("delrec_") or data.startswith("delpdf_") or data.startswith("delsum_") or data.startswith("delnot_"):
        action, lec_id = data.split("_", 1)
        db = load_data()
        mod_id = context.user_data["upload_mod_id"]
        subj_id = context.user_data["upload_subj_id"]
        module = next((m for m in db["modules"] if m["id"] == mod_id), None)
        subject = next((s for s in module["subjects"] if s["id"] == subj_id), None)
        lecture = next((l for l in subject["lectures"] if l["id"] == lec_id), None)
        
        target_map = {
            "delrec": "audio_file_id",
            "delpdf": "pdf_file_id",
            "delsum": "summary_file_id",
            "delnot": "notes_file_id"
        }
        target_field = target_map[action]
        if lecture and target_field in lecture:
            # We save the file reference in the trash
            file_type = action[3:]
            trash_item(f"file_{file_type}", lecture[target_field], parent_id=lec_id)
            del lecture[target_field]
            save_data(db)
        return await pick_subject_for_lecture_cb(update, context)
        
    return A_MANAGE_LECTURES

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
        db = load_data()
        mod_id = context.user_data.get("upload_mod_id")
        subj_id = context.user_data.get("upload_subj_id")
        if not mod_id or not subj_id:
            await update.message.reply_text("✅ تم الانتهاء من رفع الملفات.", reply_markup=ReplyKeyboardRemove())
            return await admin_start(update, context)
            
        module = next((m for m in db["modules"] if m["id"] == mod_id), None)
        subject = next((s for s in module["subjects"] if s["id"] == subj_id), None) if module else None
        
        if not subject:
            await update.message.reply_text("✅ تم الانتهاء من رفع الملفات.", reply_markup=ReplyKeyboardRemove())
            return await admin_start(update, context)
            
        await update.message.reply_text("✅ تم الانتهاء.", reply_markup=ReplyKeyboardRemove())
        
        keyboard = []
        for l in subject.get("lectures", []):
            keyboard.append([InlineKeyboardButton(f"📖 {l['name']}", callback_data=f"viewlec_{l['id']}")])
            
        keyboard.append([InlineKeyboardButton("➕ إضافة محاضرة جديدة", callback_data="add_lecture")])
        keyboard.append([InlineKeyboardButton(BTN_BACK, callback_data=f"upmod_{mod_id}")])
        
        await update.message.reply_text(f"📝 إدارة المحاضرات في: {subject['name']}\nاختر خياراً:", reply_markup=InlineKeyboardMarkup(keyboard))
        return A_MANAGE_LECTURES
        
    # If it's a text message that isn't BTN_DONE, it's a stray button press (e.g. from student menu)
    if update.message.text and update.message.text != BTN_DONE:
        markup = ReplyKeyboardMarkup([[BTN_DONE]], resize_keyboard=True)
        await update.message.reply_text(
            f"👉 أرسل ملفاً (PDF أو تسجيل) أو اضغط '{BTN_DONE}' للانتهاء.",
            reply_markup=markup
        )
        return A_WAIT_FOR_LECTURE_FILE
        
    lec_id = context.user_data.get("current_lec_id")
    if not lec_id:
        await update.message.reply_text("⚠️ حدث خطأ. يرجى البدء من جديد.", reply_markup=ReplyKeyboardRemove())
        return await admin_start(update, context)
    db = load_data()
    mod_id = context.user_data["upload_mod_id"]
    subj_id = context.user_data["upload_subj_id"]
    module = next((m for m in db["modules"] if m["id"] == mod_id), None)
    subject = next((s for s in module["subjects"] if s["id"] == subj_id), None)
    lecture = next((l for l in subject["lectures"] if l["id"] == lec_id), None)
    
    target = context.user_data.get("upload_target")
    file_id = None
    
    if update.message.document:
        file_id = update.message.document.file_id
    elif update.message.audio:
        file_id = update.message.audio.file_id
    elif update.message.voice:
        file_id = update.message.voice.file_id
    elif update.message.video:
        file_id = update.message.video.file_id
    elif update.message.photo:
        file_id = update.message.photo[-1].file_id

    if not file_id:
        await update.message.reply_text("⚠️ الرجاء إرسال ملف صالح (PDF، صوت، فيديو، أو صورة).")
        return A_WAIT_FOR_LECTURE_FILE

    if target:
        lecture[target] = file_id
        save_data(db)
        target_msg_map = {
            "audio_file_id": "التسجيل",
            "pdf_file_id": "ملف الـ PDF",
            "summary_file_id": "الملخص",
            "notes_file_id": "التبييض"
        }
        msg_type = target_msg_map.get(target, "الملف")
        await update.message.reply_text(f"✅ تم حفظ {msg_type} للمحاضرة بنجاح.")
    else:
        if update.message.document:
            lecture["pdf_file_id"] = file_id
            save_data(db)
            await update.message.reply_text("✅ تم حفظ ملف الـ PDF للمحاضرة.")
        else:
            lecture["audio_file_id"] = file_id
            save_data(db)
            await update.message.reply_text("✅ تم حفظ التسجيل للمحاضرة.")
            
    return A_WAIT_FOR_LECTURE_FILE

# -- Manage Admins --
async def show_admins_menu(query, context):
    admins = load_admins()
    keyboard = []
    for a in admins:
        keyboard.append([InlineKeyboardButton(f"🗑 حذف @{a}", callback_data=f"deladm_{a}")])
        
    keyboard.append([InlineKeyboardButton("➕ إضافة مشرف جديد", callback_data="add_admin")])
    keyboard.append([InlineKeyboardButton(BTN_BACK, callback_data="back_main")])
    
    await query.edit_message_text(f"👥 <b>إدارة المشرفين</b>\n\nالمشرف الأساسي: @{SUPER_ADMIN}\nالمشرفون الآخرون:", 
                                  reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
    return A_WAIT_FOR_ADMIN_USERNAME

async def admin_manage_admins_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data == "back_main":
        return await admin_start(update, context)
        
    elif data == "admin_admins":
        return await show_admins_menu(query, context)
        
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
    
    keyboard.append(["🔙 القائمة الرئيسية"])
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("🔽 <b>اختر الموديول:</b>", reply_markup=reply_markup, parse_mode="HTML")
    return STUDENT_MODULE

async def student_module_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text
    
    if text in ["🔙 Go Back", "🔙 القائمة الرئيسية"]:
        await update.message.reply_text(
            "📚 <b>أهلاً بك في بوت أمين مكتبة أيوباك!</b>\n"
            "استخدم الأمر /menu لعرض القائمة.",
            parse_mode="HTML", reply_markup=ReplyKeyboardRemove()
        )
        return ConversationHandler.END
    
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
        # Check if we are in the file-choice sub-menu or the lecture list
        if context.user_data.get("in_lecture_choice"):
            # Go back to the lecture list for this subject
            context.user_data["in_lecture_choice"] = False
            subj_id = context.user_data.get("selected_student_subject")
            mod_id = context.user_data.get("selected_student_module")
            db = load_data()
            module = next((m for m in db["modules"] if m["id"] == mod_id), None)
            subject = next((s for s in module["subjects"] if s["id"] == subj_id), None)
            keyboard = []
            row = []
            for l in subject.get("lectures", []):
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
        else:
            # Go back to the subject list
            context.user_data["in_lecture_choice"] = False
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
        
    if text in ["📄 ملف المحاضرة", "🎙 تسجيل المحاضرة", "📝 ملخصات", "✍️ تبييضات"]:
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
                await update.message.reply_text("📤 جارِ إرسال التسجيل...")
                file_id = lecture["audio_file_id"]
                try:
                    await context.bot.send_audio(chat_id=update.effective_chat.id, audio=file_id)
                except:
                    try:
                        await context.bot.send_voice(chat_id=update.effective_chat.id, voice=file_id)
                    except:
                        try:
                            await context.bot.send_document(chat_id=update.effective_chat.id, document=file_id)
                        except:
                            try:
                                await context.bot.send_video(chat_id=update.effective_chat.id, video=file_id)
                            except:
                                await update.message.reply_text("⚠️ حدث خطأ أثناء إرسال التسجيل.")
            else:
                await update.message.reply_text("⚠️ لم يتم رفع تسجيل صوتي لهذه المحاضرة.")
        elif text == "📝 ملخصات":
            if lecture.get("summary_file_id"):
                await update.message.reply_text("📤 جارِ إرسال الملخص...")
                await context.bot.send_document(chat_id=update.effective_chat.id, document=lecture["summary_file_id"])
            else:
                await update.message.reply_text("⚠️ لم يتم رفع ملخص لهذه المحاضرة.")
        elif text == "✍️ تبييضات":
            if lecture.get("notes_file_id"):
                await update.message.reply_text("📤 جارِ إرسال التبييض...")
                await context.bot.send_document(chat_id=update.effective_chat.id, document=lecture["notes_file_id"])
            else:
                await update.message.reply_text("⚠️ لم يتم رفع تبييض لهذه المحاضرة.")
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
    context.user_data["in_lecture_choice"] = True
    
    keyboard = [
        ["📄 ملف المحاضرة", "🎙 تسجيل المحاضرة"],
        ["📝 ملخصات", "✍️ تبييضات"],
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
            ],
            A_MANAGE_TRASH: [CallbackQueryHandler(admin_trash_actions_cb)]
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
