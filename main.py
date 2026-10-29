import asyncio
import sqlite3
import re
from datetime import datetime
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# ================= SOZLAMALAR =================
BOT_TOKEN = "9004272366:AAFd6SNezsAIC1Th_7Flx1EGgx37mAek4Xo"

ADMINS = {
    "director": [8074642736],  # Direktor / Super-Admin ID raqami
    "inspector": [987654321],  # Inspektor ID raqami
}

INITIAL_LEADERS = {
    9064698794: "11-A"
}


# ================= MA'LUMOTLAR BAZASI =================
def init_db():
    conn = sqlite3.connect("maktab_pro_davomat.db")
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS leaders
                 (
                     user_id
                     INTEGER
                     PRIMARY
                     KEY,
                     sinf
                     TEXT,
                     ism
                     TEXT
                 )""")
    c.execute("""CREATE TABLE IF NOT EXISTS daily_reports
                 (
                     id
                     INTEGER
                     PRIMARY
                     KEY
                     AUTOINCREMENT,
                     sana
                     TEXT,
                     sinf
                     TEXT,
                     kelmadi_soni
                     INTEGER,
                     vaqt
                     TEXT
                 )""")
    c.execute("""CREATE TABLE IF NOT EXISTS absent_records
                 (
                     id
                     INTEGER
                     PRIMARY
                     KEY
                     AUTOINCREMENT,
                     sana
                     TEXT,
                     sinf
                     TEXT,
                     ism
                     TEXT,
                     sabab_turi
                     TEXT,
                     photo_id
                     TEXT,
                     vaqt
                     TEXT
                 )""")
    c.execute("""CREATE TABLE IF NOT EXISTS settings
                 (
                     key
                     TEXT
                     PRIMARY
                     KEY,
                     value
                     TEXT
                 )""")
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('holiday_mode', '0')")

    for uid, sinf in INITIAL_LEADERS.items():
        c.execute("INSERT OR IGNORE INTO leaders (user_id, sinf, ism) VALUES (?, ?, ?)", (uid, sinf, "Sardor"))

    conn.commit()
    conn.close()


# ================= HOLATLAR (FSM) =================
class BotStates(StatesGroup):
    reg_waiting_class = State()
    att_waiting_bulk_names = State()
    att_review_reasons = State()
    runaway_waiting_name = State()
    admin_search_student = State()
    admin_broadcast = State()


# ================= YORDAMCHI FUNKSIYALAR =================
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


def is_valid_fullname(text: str) -> bool:
    """Faqat Familiya va Ism kiritilganini tekshiruvchi qat'iy filtr"""
    if not text:
        return False
    words = text.strip().split()
    if len(words) < 2 or len(words) > 4:
        return False
    pattern = r"^[a-zA-Zа-яА-ЯёЁўЎқҚғҒҳҲʼ'`‘’-]+$"
    for w in words:
        if len(w) < 3 or not re.match(pattern, w):
            return False
    return True


def get_role(user_id: int):
    if user_id in ADMINS["director"]:
        return "director", "Direktor / Koordinator"
    if user_id in ADMINS["inspector"]:
        return "inspector", "Inspektor"
    conn = sqlite3.connect("maktab_pro_davomat.db")
    c = conn.cursor()
    c.execute("SELECT sinf FROM leaders WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return "leader", row[0]
    return None, None


def is_holiday() -> bool:
    conn = sqlite3.connect("maktab_pro_davomat.db")
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key = 'holiday_mode'")
    val = c.fetchone()[0]
    conn.close()
    return val == "1"


async def notify_admins(text: str):
    admin_ids = set(ADMINS["director"] + ADMINS["inspector"])
    for aid in admin_ids:
        try:
            await bot.send_message(aid, text, parse_mode="Markdown")
        except Exception:
            pass


# ================= MENYU TUGMALARI =================
def get_admin_kb():
    holiday_status = "🟢 Yoqilgan" if is_holiday() else "⚪️ O'chirilgan"
    b = InlineKeyboardBuilder()
    b.button(text="📊 Bugungi svodka", callback_data="adm_today")
    b.button(text="⏳ Topshirmaganlar", callback_data="adm_missing")
    b.button(text="🚨 Qizil ro'yxat (Sababsizlar)", callback_data="adm_redlist")
    b.button(text="🔍 O'quvchini qidirish (Dosye)", callback_data="adm_search")
    b.button(text="📈 Haftalik Reyting", callback_data="adm_rating")
    b.button(text="📢 Sardorlarga e'lon yuborish", callback_data="adm_broadcast")
    b.button(text=f"🏖 Dam olish rejimi: {holiday_status}", callback_data="adm_toggle_holiday")
    b.button(text="🔄 Yangilash", callback_data="adm_today")
    b.adjust(2, 1, 1, 2, 1, 1)
    return b.as_markup()


def get_leader_kb(sinf: str):
    b = InlineKeyboardBuilder()
    b.button(text=f"✅ {sinf} — Hamma darsda (100%)", callback_data=f"ldr_all_{sinf}")
    b.button(text="🔢 Kelmaganlarni kiritish (Tugmali)", callback_data=f"ldr_count_{sinf}")
    b.button(text="🏃‍♂️ Darsdan qochib keti (Shoshilinch)", callback_data=f"ldr_runaway_{sinf}")
    b.button(text="📋 Bugungi hisobotim", callback_data=f"ldr_status_{sinf}")
    b.adjust(1)
    return b.as_markup()


def get_reasons_toggle_kb(sinf: str, records: list):
    b = InlineKeyboardBuilder()
    for idx, item in enumerate(records):
        icon = "❌" if item["sabab"] == "Sababsiz" else "🏥"
        b.button(
            text=f"{idx + 1}. {item['ism']} — {icon} {item['sabab']}",
            callback_data=f"tglrsn_{idx}"
        )
    b.button(text="📤 Tasdiqlash va yuborish", callback_data=f"submit_bulk_{sinf}")
    b.button(text="🔙 Bekor qilish", callback_data=f"back_ldr_{sinf}")
    b.adjust(1)
    return b.as_markup()


# ================= START VA RO'YXATDAN O'TISH =================
@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    uid = message.from_user.id
    role, info = get_role(uid)
    bugun = datetime.now().strftime("%d.%m.%Y")

    if role in ["director", "inspector"]:
        await message.answer(
            f"🏛 **15-maktab PRO Davomat va Nazorat Tizimi**\n\n"
            f"👤 Xush kelibsiz, **{info}**!\n"
            f"📅 Sana: `{bugun}`",
            reply_markup=get_admin_kb(),
            parse_mode="Markdown"
        )
    elif role == "leader":
        if is_holiday():
            await message.answer(
                "🏖 **Bugun maktabda dam olish kuni deb e'lon qilingan!**\nDavomat topshirish talab etilmaydi.",
                parse_mode="Markdown")
            return
        await message.answer(
            f"👋 Salom, **{info}** sinf sardori!\n"
            f"📅 Sana: `{bugun}`\n\n"
            f"Quyidagi menyu orqali davomatni yuboring:",
            reply_markup=get_leader_kb(info),
            parse_mode="Markdown"
        )
    else:
        b = InlineKeyboardBuilder()
        b.button(text="🙋‍♂️ Men sinf sardoriman (Ulanish)", callback_data="reg_leader")
        await message.answer(
            f"⛔ **Siz tizimda ro'yxatdan o'tmagansiz!**\n\n"
            f"Agar sinf sardori bo'lsangiz, quyidagi tugmani bosib ro'yxatdan o'tish so'rovini yuboring:",
            reply_markup=b.as_markup(),
            parse_mode="Markdown"
        )


@dp.callback_query(F.data == "reg_leader")
async def reg_leader_step1(call: CallbackQuery, state: FSMContext):
    await state.set_state(BotStates.reg_waiting_class)
    await call.message.edit_text(
        "✍️ **Qaysi sinf sardorisiz?**\n\n"
        "Sinfingiz nomini va o'zingizning Familiya-Ismingizni yozib yuboring.\n"
        "*Masalan:* `9-B Aliyev Vali`",
        parse_mode="Markdown"
    )


@dp.message(BotStates.reg_waiting_class)
async def reg_leader_step2(message: Message, state: FSMContext):
    parts = message.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("⚠️ Xato! Oldin sinfni, keyin Familiya-Ismingizni yozing.\n*Masalan:* `9-B Aliyev Vali`",
                             parse_mode="Markdown")
        return
    sinf, ism = parts[0].upper(), parts[1].title()
    uid = message.from_user.id
    await state.clear()

    b = InlineKeyboardBuilder()
    b.button(text="✅ Tasdiqlash", callback_data=f"appr_yes_{uid}_{sinf}")
    b.button(text="❌ Rad etish", callback_data=f"appr_no_{uid}")
    b.adjust(2)

    for aid in ADMINS["director"]:
        try:
            await bot.send_message(
                aid,
                f"🔑 **Yangi sardor ulanish so'rovi!**\n\n"
                f"🏫 Sinf: **{sinf}**\n"
                f"👤 O'quvchi: `{ism}`\n"
                f"🆔 ID: `{uid}`\n\nTasdiqlaysizmi?",
                reply_markup=b.as_markup(),
                parse_mode="Markdown"
            )
        except Exception:
            pass

    await message.answer(
        "⏳ **So'rovingiz IT koordinator va Direktorga yuborildi!**\nTasdiqlangach, sizga xabar keladi.",
        parse_mode="Markdown")


@dp.callback_query(F.data.startswith("appr_"))
async def approve_leader_handler(call: CallbackQuery):
    data = call.data.split("_")
    action = data[1]
    uid = int(data[2])

    if action == "yes":
        sinf = data[3]
        conn = sqlite3.connect("maktab_pro_davomat.db")
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO leaders (user_id, sinf, ism) VALUES (?, ?, ?)", (uid, sinf, "Sardor"))
        conn.commit()
        conn.close()
        await call.message.edit_text(f"✅ **{sinf}** sinf sardori (ID: `{uid}`) muvaffaqiyatli tasdiqlandi!",
                                     parse_mode="Markdown")
        try:
            await bot.send_message(uid,
                                   f"🎉 **Tabriklaymiz! Siz {sinf} sinf sardori sifatida tasdiqlandingiz!**\nIshni boshlash uchun /start bosing.",
                                   parse_mode="Markdown")
        except Exception:
            pass
    else:
        await call.message.edit_text("❌ So'rov rad etildi.")
        try:
            await bot.send_message(uid, "⛔ Sizning sardorlik so'rovingiz rad etildi.")
        except Exception:
            pass


# ================= SARDOR: 100% DAVOMAT =================
@dp.callback_query(F.data.startswith("ldr_all_"))
async def ldr_all_present(call: CallbackQuery):
    if is_holiday():
        await call.answer("Bugun dam olish kuni!", show_alert=True)
        return
    sinf = call.data.split("_")[2]
    bugun = datetime.now().strftime("%d.%m.%Y")
    vaqt = datetime.now().strftime("%H:%M")

    conn = sqlite3.connect("maktab_pro_davomat.db")
    c = conn.cursor()
    c.execute("DELETE FROM daily_reports WHERE sana = ? AND sinf = ?", (bugun, sinf))
    c.execute("DELETE FROM absent_records WHERE sana = ? AND sinf = ?", (bugun, sinf))
    c.execute("INSERT INTO daily_reports (sana, sinf, kelmadi_soni, vaqt) VALUES (?, ?, 0, ?)", (bugun, sinf, vaqt))
    conn.commit()
    conn.close()

    await call.message.edit_text(
        f"✅ **{sinf}** sinfi davomati qabul qilindi!\n"
        f"⏰ Vaqt: `{vaqt}` | 📊 Holat: **100% Hamma darsda**",
        reply_markup=get_leader_kb(sinf),
        parse_mode="Markdown"
    )
    await notify_admins(f"🟢 **{sinf}** sinfi: **Hamma darsda (100%)** | ⏰ `{vaqt}`")
    await call.answer("Saqlandi!")


# ================= SARDOR: TUGMALI SON VA BITTA XABARDA KIRITISH =================
@dp.callback_query(F.data.startswith("ldr_count_"))
async def ldr_select_count(call: CallbackQuery):
    sinf = call.data.split("_")[2]
    b = InlineKeyboardBuilder()
    for i in range(1, 11):
        b.button(text=f"{i} ta", callback_data=f"setcnt_{sinf}_{i}")
    b.button(text="🔙 Orqaga", callback_data=f"back_ldr_{sinf}")
    b.adjust(5, 5, 1)

    await call.message.edit_text(
        f"🔢 **{sinf}** sinfida bugun nechta o'quvchi darsga kelmadi?\n"
        f"👇 *Quyidagi tugmalardan sonini tanlang:*",
        reply_markup=b.as_markup(),
        parse_mode="Markdown"
    )


@dp.callback_query(F.data.startswith("back_ldr_"))
async def back_to_ldr(call: CallbackQuery, state: FSMContext):
    await state.clear()
    sinf = call.data.split("_")[2]
    await call.message.edit_text(f"👋 **{sinf}** sinf sardori menyusi:", reply_markup=get_leader_kb(sinf),
                                 parse_mode="Markdown")


@dp.callback_query(F.data.startswith("setcnt_"))
async def ask_bulk_names(call: CallbackQuery, state: FSMContext):
    _, sinf, cnt = call.data.split("_")
    total = int(cnt)
    await state.update_data(sinf=sinf, total=total)
    await state.set_state(BotStates.att_waiting_bulk_names)

    b = InlineKeyboardBuilder()
    b.button(text="🔙 Orqaga qaytish", callback_data=f"ldr_count_{sinf}")

    namuna = "\n".join([f"`{i}. Familiya Ism`" for i in range(1, min(total + 1, 4))])
    if total > 3:
        namuna += f"\n`... ({total} ta qator)`"

    await call.message.edit_text(
        f"✍️ **{sinf}** sinfida kelmagan **{total} nafar** o'quvchining Familiyasi va Ismini **bitta xabarda** (har bir qatorda bittadan) yozib yuboring:\n\n"
        f"📌 *Namuna:*\n{namuna}\n\n"
        f"⚠️ **Diqqat:** Qatorlar soni aniq **{total} ta** bo'lishi va faqat haqiqiy Familiya-Ism yozilishi shart!",
        reply_markup=b.as_markup(),
        parse_mode="Markdown"
    )


@dp.message(BotStates.att_waiting_bulk_names)
async def process_bulk_names(message: Message, state: FSMContext):
    data = await state.get_data()
    sinf = data["sinf"]
    total = data["total"]

    # Qatorlarga bo'lish va tartib raqamlarini (1., 2) va h.k.) tozalash
    raw_lines = [line.strip() for line in message.text.split("\n") if line.strip()]
    cleaned_names = []
    for line in raw_lines:
        clean = re.sub(r"^\d+[\.\)\-\s]+", "", line).strip()
        cleaned_names.append(clean)

    # 1-TEKSHIRUV: Soni to'g'rimi?
    if len(cleaned_names) != total:
        await message.answer(
            f"⛔ **Xatolik! Soni to'g'ri kelmadi.**\n\n"
            f"Siz tugmada **{total} ta** o'quvchi tanlagansiz, lekin xabarda **{len(cleaned_names)} ta** qator yozdingiz!\n"
            f"🔄 *Iltimos, barcha {total} nafar o'quvchini bitta xabarda to'liq yozib yuboring:*",
            parse_mode="Markdown"
        )
        return

    # 2-TEKSHIRUV: Har bir qatorda haqiqiy Familiya va Ism bormi?
    invalid_lines = []
    for idx, name in enumerate(cleaned_names, start=1):
        if not is_valid_fullname(name):
            invalid_lines.append(f"{idx}-qator: «{name}»")

    if invalid_lines:
        err_list = "\n".join(invalid_lines)
        await message.answer(
            f"⛔ **Xatolik! Quyidagi qatorlarda Familiya va Ism noto'g'ri yozilgan:**\n"
            f"`{err_list}`\n\n"
            f"• Har bir qatorda kamida 2 ta so'z (Familiya va Ism) bo'lishi shart;\n"
            f"• Raqamlar va belgilar qatnashmasligi kerak.\n\n"
            f"🔄 *Iltimos, to'g'rilab qaytadan yuboring:*",
            parse_mode="Markdown"
        )
        return

    # Hammasi to'g'ri bo'lsa -> Sababini tugmada belgilash oynasiga o'tkazamiz
    records = [{"ism": name.title(), "sabab": "Sababsiz"} for name in cleaned_names]
    await state.update_data(records=records)
    await state.set_state(BotStates.att_review_reasons)

    await message.answer(
        f"✅ **{total} nafar o'quvchi qabul qilindi!**\n\n"
        f"👇 Agar ularning orasida **Sababli (Kasal/Tadbirda)** bo'lganlari bo'lsa, ismining ustiga bosib o'zgartiring. Tayyor bo'lgach, **«📤 Tasdiqlash va yuborish»** tugmasini bosing:",
        reply_markup=get_reasons_toggle_kb(sinf, records),
        parse_mode="Markdown"
    )


@dp.callback_query(BotStates.att_review_reasons, F.data.startswith("tglrsn_"))
async def toggle_reason_handler(call: CallbackQuery, state: FSMContext):
    idx = int(call.data.split("_")[1])
    data = await state.get_data()
    sinf = data["sinf"]
    records = data["records"]

    # Sababsiz <-> Sababli (Kasal) aylantirish
    current_reason = records[idx]["sabab"]
    records[idx]["sabab"] = "Sababli" if current_reason == "Sababsiz" else "Sababsiz"
    await state.update_data(records=records)

    await call.message.edit_reply_markup(reply_markup=get_reasons_toggle_kb(sinf, records))
    await call.answer(f"{records[idx]['ism']} -> {records[idx]['sabab']}")


@dp.callback_query(BotStates.att_review_reasons, F.data.startswith("submit_bulk_"))
async def submit_bulk_attendance(call: CallbackQuery, state: FSMContext):
    sinf = call.data.split("_")[2]
    data = await state.get_data()
    records = data["records"]
    total = len(records)

    bugun = datetime.now().strftime("%d.%m.%Y")
    vaqt = datetime.now().strftime("%H:%M")

    conn = sqlite3.connect("maktab_pro_davomat.db")
    c = conn.cursor()
    c.execute("DELETE FROM daily_reports WHERE sana = ? AND sinf = ?", (bugun, sinf))
    c.execute("DELETE FROM absent_records WHERE sana = ? AND sinf = ?", (bugun, sinf))
    c.execute("INSERT INTO daily_reports (sana, sinf, kelmadi_soni, vaqt) VALUES (?, ?, ?, ?)",
              (bugun, sinf, total, vaqt))

    summary_lines = []
    for r in records:
        c.execute(
            "INSERT INTO absent_records (sana, sinf, ism, sabab_turi, photo_id, vaqt) VALUES (?, ?, ?, ?, NULL, ?)",
            (bugun, sinf, r["ism"], r["sabab"], vaqt))
        icon = "❌" if r["sabab"] == "Sababsiz" else "🏥"
        summary_lines.append(f"{icon} `{r['ism']}` ({r['sabab']})")

        if r["sabab"] == "Sababsiz":
            c.execute("SELECT COUNT(*) FROM absent_records WHERE sinf = ? AND ism = ? AND sabab_turi = 'Sababsiz'",
                      (sinf, r["ism"]))
            unexcused_cnt = c.fetchone()[0]
            if unexcused_cnt >= 2:
                await notify_admins(
                    f"🚨 **DIQQAT! QIZIL RO'YXAT:**\n**{sinf}** sinf o'quvchisi `{r['ism']}` jami **{unexcused_cnt}-marta SABABSIZ** dars qoldirdi!")

    conn.commit()
    conn.close()
    await state.clear()

    ro_yxat_str = "\n".join(summary_lines)
    await call.message.edit_text(
        f"✅ **{sinf}** sinfi davomati muvaffaqiyatli saqlandi!\n\n"
        f"🚫 Yo'qlar: **{total} nafar** | ⏰ `{vaqt}`\n"
        f"{ro_yxat_str}",
        reply_markup=get_leader_kb(sinf),
        parse_mode="Markdown"
    )
    await notify_admins(
        f"🔴 **{sinf}** sinfi davomat topshirdi (⏰ `{vaqt}`)\n🚫 Yo'qlar: **{total} nafar**\n{ro_yxat_str}")
    await call.answer("Davomat yuborildi!")


# ================= SARDOR: DARSDAN KETIB QOLGANLAR =================
@dp.callback_query(F.data.startswith("ldr_runaway_"))
async def runaway_prompt(call: CallbackQuery, state: FSMContext):
    sinf = call.data.split("_")[2]
    await state.update_data(sinf=sinf)
    await state.set_state(BotStates.runaway_waiting_name)

    b = InlineKeyboardBuilder()
    b.button(text="🔙 Orqaga", callback_data=f"back_ldr_{sinf}")
    await call.message.edit_text(
        f"🏃‍♂️ **{sinf}** sinfidan kim so'roqsiz darsdan ketib qoldi?\n\n"
        f"✍️ *O'quvchining Familiyasi va Ismini yozing:*",
        reply_markup=b.as_markup(),
        parse_mode="Markdown"
    )


@dp.message(BotStates.runaway_waiting_name)
async def runaway_save(message: Message, state: FSMContext):
    if not is_valid_fullname(message.text):
        await message.answer("⚠️ Iltimos, o'quvchining Familiyasi va Ismini to'g'ri yozing!")
        return
    data = await state.get_data()
    sinf = data["sinf"]
    ism = message.text.strip().title()
    vaqt = datetime.now().strftime("%H:%M")
    bugun = datetime.now().strftime("%d.%m.%Y")

    conn = sqlite3.connect("maktab_pro_davomat.db")
    c = conn.cursor()
    c.execute(
        "INSERT INTO absent_records (sana, sinf, ism, sabab_turi, photo_id, vaqt) VALUES (?, ?, ?, 'Darsdan qochdi', NULL, ?)",
        (bugun, sinf, ism, vaqt))
    conn.commit()
    conn.close()

    await state.clear()
    await message.answer(f"🚨 **{ism}** bo'yicha shoshilinch xabar Inspektorga va Direktorga yuborildi!",
                         reply_markup=get_leader_kb(sinf), parse_mode="Markdown")
    await notify_admins(
        f"🏃‍♂️🚨 **SHOSHILINCH XABAR!**\n**{sinf}** sinf o'quvchisi `{ism}` soat `{vaqt}` da darsdan ketib qoldi!")


@dp.callback_query(F.data.startswith("ldr_status_"))
async def ldr_my_status(call: CallbackQuery):
    sinf = call.data.split("_")[2]
    bugun = datetime.now().strftime("%d.%m.%Y")
    conn = sqlite3.connect("maktab_pro_davomat.db")
    c = conn.cursor()
    c.execute("SELECT kelmadi_soni, vaqt FROM daily_reports WHERE sana = ? AND sinf = ?", (bugun, sinf))
    row = c.fetchone()
    conn.close()
    if row:
        await call.answer(f"✅ Bugun soat {row[1]} da topshirgansiz (Yo'qlar: {row[0]} ta)", show_alert=True)
    else:
        await call.answer("⚠️ Bugun hali davomat topshirmagansiz!", show_alert=True)


# ================= DIREKTOR VA INSPEKTOR FUNKSIYALARI =================
@dp.callback_query(F.data == "adm_today")
async def adm_today_handler(call: CallbackQuery):
    bugun = datetime.now().strftime("%d.%m.%Y")
    conn = sqlite3.connect("maktab_pro_davomat.db")
    c = conn.cursor()
    c.execute("SELECT COUNT(DISTINCT sinf) FROM leaders")
    jami_sinflar = c.fetchone()[0]

    c.execute("SELECT sinf, kelmadi_soni, vaqt FROM daily_reports WHERE sana = ? ORDER BY sinf ASC", (bugun,))
    reports = c.fetchall()

    jami_yoqlar = sum(r[1] for r in reports)
    text = (
        f"📊 **15-MAKTAB KUNLIK SVODKASI ({bugun})**\n"
        f"────────────────────\n"
        f"✅ Topshirgan sinflar: **{len(reports)} / {jami_sinflar}**\n"
        f"🚫 Jami darsda yo'qlar: **{jami_yoqlar} nafar**\n"
        f"────────────────────\n\n"
    )

    if reports:
        for sinf, soni, vaqt in reports:
            icon = "🟢" if soni == 0 else "🔴"
            text += f"{icon} **{sinf}** (⏰ {vaqt}) — Yo'qlar: **{soni} ta**\n"
            if soni > 0:
                c.execute("SELECT ism, sabab_turi FROM absent_records WHERE sana = ? AND sinf = ?", (bugun, sinf))
                students = c.fetchall()
                for ism, sabab in students:
                    s_icon = "❌" if sabab == "Sababsiz" else "🏥"
                    text += f"  └ {s_icon} `{ism}` ({sabab})\n"
            text += "\n"
    else:
        text += "⏳ *Hozircha hech qaysi sinf davomat topshirmadi.*"

    conn.close()
    try:
        await call.message.edit_text(text, reply_markup=get_admin_kb(), parse_mode="Markdown")
    except Exception:
        pass
    await call.answer("Yangilandi!")


@dp.callback_query(F.data == "adm_missing")
async def adm_missing_handler(call: CallbackQuery):
    bugun = datetime.now().strftime("%d.%m.%Y")
    conn = sqlite3.connect("maktab_pro_davomat.db")
    c = conn.cursor()
    c.execute("SELECT DISTINCT sinf FROM leaders")
    all_classes = {r[0] for r in c.fetchall()}
    c.execute("SELECT sinf FROM daily_reports WHERE sana = ?", (bugun,))
    submitted = {r[0] for r in c.fetchall()}
    conn.close()

    missing = sorted(list(all_classes - submitted))
    if missing:
        text = f"⏳ **Bugun davomat topshirmagan sinflar ({len(missing)} ta):**\n\n" + "\n".join(
            [f"🔸 **{s}** sinfi" for s in missing])
    else:
        text = "🎉 **Barcha sinflar davomatni to'liq topshirib bo'ldi!**"

    await call.message.edit_text(text, reply_markup=get_admin_kb(), parse_mode="Markdown")


@dp.callback_query(F.data == "adm_redlist")
async def adm_redlist_handler(call: CallbackQuery):
    conn = sqlite3.connect("maktab_pro_davomat.db")
    c = conn.cursor()
    c.execute("""SELECT sinf, ism, COUNT(*) as cnt
                 FROM absent_records
                 WHERE sabab_turi IN ('Sababsiz', 'Darsdan qochdi')
                 GROUP BY sinf, ism
                 HAVING cnt >= 2
                 ORDER BY cnt DESC""")
    rows = c.fetchall()
    conn.close()

    if rows:
        text = "🚨 **QIZIL RO'YXAT (Surunkali sababsiz dars qoldiruvchilar):**\n\n"
        for sinf, ism, cnt in rows:
            text += f"🔴 **{sinf}** | `{ism}` — **{cnt} marta** sababsiz\n"
    else:
        text = "✅ **Hozircha 2 va undan ko'p sababsiz dars qoldirgan o'quvchilar yo'q!**"

    await call.message.edit_text(text, reply_markup=get_admin_kb(), parse_mode="Markdown")


@dp.callback_query(F.data == "adm_search")
async def adm_search_prompt(call: CallbackQuery, state: FSMContext):
    await state.set_state(BotStates.admin_search_student)
    b = InlineKeyboardBuilder()
    b.button(text="🔙 Orqaga", callback_data="adm_today")
    await call.message.edit_text("🔍 **Qidirmoqchi bo'lgan o'quvchingizning Ism yoki Familiyasini yozing:**",
                                 reply_markup=b.as_markup(), parse_mode="Markdown")


@dp.message(BotStates.admin_search_student)
async def adm_search_result(message: Message, state: FSMContext):
    query = message.text.strip().title()
    await state.clear()
    conn = sqlite3.connect("maktab_pro_davomat.db")
    c = conn.cursor()
    c.execute("SELECT sana, sinf, ism, sabab_turi, vaqt FROM absent_records WHERE ism LIKE ? ORDER BY id DESC",
              (f"%{query}%",))
    rows = c.fetchall()
    conn.close()

    if rows:
        text = f"📂 **«{query}» bo'yicha topilgan ma'lumotlar ({len(rows)} ta holat):**\n\n"
        for sana, sinf, ism, sabab, vaqt in rows:
            text += f"• `{sana}` ({vaqt}) | **{sinf}** — `{ism}` ({sabab})\n"
    else:
        text = f"✅ **«{query}»** ismli o'quvchi dars qoldirganlar bazasidan topilmadi (100% darsga qatnashgan)."

    await message.answer(text, reply_markup=get_admin_kb(), parse_mode="Markdown")


@dp.callback_query(F.data == "adm_rating")
async def adm_rating_handler(call: CallbackQuery):
    conn = sqlite3.connect("maktab_pro_davomat.db")
    c = conn.cursor()
    c.execute("""SELECT sinf, SUM(kelmadi_soni) as total_abs, COUNT(*) as days
                 FROM daily_reports
                 GROUP BY sinf
                 ORDER BY total_abs ASC""")
    rows = c.fetchall()
    conn.close()

    if rows:
        text = "🏆 **SINFLAR DAVOMAT REYTINGI (Eng namunali sinflar):**\n\n"
        medals = ["🥇", "🥈", "🥉"]
        for idx, (sinf, total_abs, days) in enumerate(rows):
            m = medals[idx] if idx < 3 else f"{idx + 1}."
            text += f"{m} **{sinf}** sinfi — Jami yo'qlar: **{total_abs} ta** ({days} kun ichida)\n"
    else:
        text = "📊 Reyting shakllanishi uchun hali ma'lumotlar yetarli emas."

    await call.message.edit_text(text, reply_markup=get_admin_kb(), parse_mode="Markdown")


@dp.callback_query(F.data == "adm_broadcast")
async def adm_broadcast_prompt(call: CallbackQuery, state: FSMContext):
    await state.set_state(BotStates.admin_broadcast)
    b = InlineKeyboardBuilder()
    b.button(text="🔙 Bekor qilish", callback_data="adm_today")
    await call.message.edit_text("📢 **Barcha sinf sardorlariga yuboriladigan e'lon matnini yozing:**",
                                 reply_markup=b.as_markup(), parse_mode="Markdown")


@dp.message(BotStates.admin_broadcast)
async def adm_broadcast_send(message: Message, state: FSMContext):
    await state.clear()
    conn = sqlite3.connect("maktab_pro_davomat.db")
    c = conn.cursor()
    c.execute("SELECT user_id FROM leaders")
    leaders = c.fetchall()
    conn.close()

    sent = 0
    for (uid,) in leaders:
        try:
            await bot.send_message(uid, f"📢 **MAKTAB MA'MURIYATIDAN E'LON:**\n\n{message.text}", parse_mode="Markdown")
            sent += 1
        except Exception:
            pass

    await message.answer(f"✅ E'lon **{sent} nafar** sinf sardoriga muvaffaqiyatli yuborildi!",
                         reply_markup=get_admin_kb(), parse_mode="Markdown")


@dp.callback_query(F.data == "adm_toggle_holiday")
async def adm_toggle_holiday(call: CallbackQuery):
    new_val = "0" if is_holiday() else "1"
    conn = sqlite3.connect("maktab_pro_davomat.db")
    c = conn.cursor()
    c.execute("UPDATE settings SET value = ? WHERE key = 'holiday_mode'", (new_val,))
    conn.commit()
    conn.close()
    status_msg = "🏖 Dam olish kuni rejimi YOQILDI!" if new_val == "1" else "🔔 O'quv kuni rejimi YOQILDI!"
    await call.answer(status_msg, show_alert=True)
    await adm_today_handler(call)


async def main():
    init_db()
    print("🚀 15-maktab PRO Smart Davomat Boti (1-variant) ishga tushdi...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())