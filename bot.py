import os
import asyncio
import random
import sqlite3
import requests
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, CommandObject, StateFilter
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_IDS")

# --- ⚙️ ТВОИ НАСТРОЙКИ ---
MARGIN_BUY = 4.3
MARGIN_SELL = 2.0
ADMIN_WALLET = "UQBaUmVa78KiBSuyeH8nNFq9-8jTl2YM05k22q54SJtgGaOH"
REFERRAL_BONUS = 0.01

bot = Bot(token=TOKEN)
dp = Dispatcher()

# ==========================================
# 💾 БАЗА ДАННЫХ
# ==========================================
DB_FILE = "exchange.db"

def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                referrer_id INTEGER,
                balance REAL DEFAULT 0,
                join_date TEXT
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS deals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                type TEXT,
                amount_usdt REAL,
                amount_rub REAL,
                status TEXT,
                date TEXT
            )
        ''')
        conn.commit()

def db_add_user(user_id, username, referrer_id=None):
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
            if cursor.fetchone() is None:
                cursor.execute("INSERT INTO users (user_id, username, referrer_id, join_date) VALUES (?, ?, ?, ?)", 
                               (user_id, username, referrer_id, datetime.now().strftime("%Y-%m-%d %H:%M")))
                conn.commit()
                print(f"✅ БД: Пользователь {user_id} добавлен. Реферер: {referrer_id}")
                return True
            else:
                print(f"ℹ️ БД: Пользователь {user_id} уже есть в базе.")
                return False
    except Exception as e:
        print(f"❌ Ошибка записи в БД: {e}")
        return False

def db_get_user(user_id):
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        return cursor.fetchone()

def db_add_bonus(user_id, amount):
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
        conn.commit()

def db_get_all_users():
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM users")
        return [row[0] for row in cursor.fetchall()]

def db_add_deal(user_id, deal_type, usdt, rub):
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO deals (user_id, type, amount_usdt, amount_rub, status, date) VALUES (?, ?, ?, ?, 'pending', ?)",
                       (user_id, deal_type, usdt, rub, datetime.now().strftime("%Y-%m-%d %H:%M")))
        return cursor.lastrowid

def db_update_deal_status(deal_id, status):
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("UPDATE deals SET status = ? WHERE id = ?", (status, deal_id))
        conn.commit()

def db_get_stats(user_id):
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*), SUM(amount_usdt) FROM deals WHERE user_id = ? AND status = 'success'", (user_id,))
        count, volume = cursor.fetchone()
        cursor.execute("SELECT COUNT(*) FROM users WHERE referrer_id = ?", (user_id,))
        refs = cursor.fetchone()[0]
        return count or 0, round(volume or 0, 2), refs

# ==========================================
# 🧠 ЛОГИКА БОТА
# ==========================================

class BuyState(StatesGroup):
    amount = State()
    wallet = State()
    proof = State()

class SellState(StatesGroup):
    amount_usdt = State()
    card = State()
    proof = State()

def get_courses():
    try:
        url = "https://api.binance.com/api/v3/ticker/price?symbol=USDTRUB"
        session = requests.Session()
        session.trust_env = False
        response = session.get(url, timeout=5)
        price = float(response.json()['price'])
        return round(price + MARGIN_BUY, 2), round(price - MARGIN_SELL, 2)
    except:
        return 100.00, 90.00

# --- 🎹 МЕНЮ ---
main_menu = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="💸 Купить USDT", callback_data="buy_start"),
     InlineKeyboardButton(text="💰 Продать USDT", callback_data="sell_start")],
    [InlineKeyboardButton(text="👤 Личный кабинет", callback_data="profile")],
    [InlineKeyboardButton(text="📊 Курс обмена", callback_data="rates")]
])
cancel_menu = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]])
back_menu = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 В меню", callback_data="menu")]])

# --- 🚀 СТАРТ (ИСПРАВЛЕННЫЙ И НАДЕЖНЫЙ) ---
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    print(f"\n🚀 НАЖАТ СТАРТ: {message.from_user.id} ({message.from_user.username})")
    
    referrer_id = None
    
    # Надежный способ достать рефералку вручную
    try:
        args = message.text.split()
        if len(args) > 1:
            potential_id = args[1]
            if potential_id.isdigit():
                referrer_id = int(potential_id)
                if referrer_id == message.from_user.id:
                    print("⚠️ Попытка пригласить самого себя")
                    referrer_id = None
                else:
                    print(f"🔗 ОБНАРУЖЕН РЕФЕРЕР: {referrer_id}")
    except Exception as e:
        print(f"⚠️ Ошибка разбора ссылки: {e}")

    # Добавляем в БД
    is_new = db_add_user(message.from_user.id, message.from_user.username, referrer_id)
    
    if is_new and referrer_id:
        try:
            await bot.send_message(referrer_id, f"🎉 **У вас новый реферал:** @{message.from_user.username}")
            print("📩 Уведомление рефереру отправлено")
        except Exception as e:
            print(f"❌ Не удалось отправить уведомление рефереру: {e}")

    await message.answer(f"👋 Привет, {message.from_user.first_name}! Это лучший P2P обменник.", reply_markup=main_menu)

# --- 🛠 ДИАГНОСТИКА (DEBUG) ---
@dp.message(F.text == "/debug")
async def cmd_debug(message: types.Message):
    if str(message.from_user.id) != str(ADMIN_ID):
        return
        
    users_list = "📋 **Список пользователей:**\n\n"
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, username, referrer_id, balance FROM users")
        rows = cursor.fetchall()
        for row in rows:
            uid, uname, ref_id, bal = row
            ref_str = f"Пригласил: `{ref_id}`" if ref_id else "Пригласил: ⛔ Нет"
            users_list += f"👤 {uname} (ID `{uid}`)\n   └ {ref_str} | Баланс: {bal}\n\n"
    await message.answer(users_list)

# --- 📢 РАССЫЛКА ---
@dp.message(F.text.startswith("/send"))
async def cmd_broadcast(message: types.Message):
    if str(message.from_user.id) != str(ADMIN_ID):
        return
    text = message.text[6:]
    if not text:
        return await message.answer("⚠️ Пиши так: `/send Текст`")
    users = db_get_all_users()
    count = 0
    await message.answer(f"⏳ Рассылка на {len(users)} чел...")
    for user_id in users:
        try:
            await bot.send_message(user_id, f"📢 **ВАЖНОЕ СООБЩЕНИЕ:**\n\n{text}")
            count += 1
            await asyncio.sleep(0.1)
        except:
            pass
    await message.answer(f"✅ Успешно: {count}")

@dp.callback_query(F.data.in_({"menu", "cancel"}))
async def back_handler(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("👋 Главное меню:", reply_markup=main_menu)

# --- 🔄 СДЕЛКИ ---
@dp.callback_query(F.data == "buy_start")
async def buy_start(callback: CallbackQuery, state: FSMContext):
    b, _ = get_courses()
    await state.update_data(course=b)
    await state.set_state(BuyState.amount)
    await callback.message.edit_text(f"💸 **Покупка**\n📈 Курс: {b} RUB\n👇 Сумма в РУБЛЯХ:", reply_markup=cancel_menu)

@dp.message(StateFilter(BuyState.amount))
async def buy_amount(message: types.Message, state: FSMContext):
    if not message.text.isdigit(): return await message.answer("⚠️ Число!")
    amount = int(message.text)
    if amount < 500: return await message.answer("⛔ Минимум 500 RUB")
    await state.update_data(rub_amount=amount)
    await state.set_state(BuyState.wallet)
    await message.answer("✅ Введите кошелек для получения USDT:", reply_markup=cancel_menu)

@dp.message(StateFilter(BuyState.wallet))
async def buy_wallet(message: types.Message, state: FSMContext):
    data = await state.get_data()
    usdt = round(data['rub_amount'] / data['course'], 2)
    deal_id = db_add_deal(message.from_user.id, 'BUY', usdt, data['rub_amount'])
    await state.update_data(deal_id=deal_id, wallet=message.text, usdt_amount=usdt)
    await state.set_state(BuyState.proof)
    await message.answer(f"📝 **Заявка #{deal_id}**\nК оплате: **{data['rub_amount']} RUB**\n💳 Озон: `2200 7000 1234 5678`\n⏳ Жду скриншот.", reply_markup=cancel_menu)

@dp.callback_query(F.data == "sell_start")
async def sell_start(callback: CallbackQuery, state: FSMContext):
    _, s = get_courses()
    await state.update_data(course=s)
    await state.set_state(SellState.amount_usdt)
    await callback.message.edit_text(f"💰 **Продажа**\n📉 Курс: {s} RUB\n👇 Сумма в USDT:", reply_markup=cancel_menu)

@dp.message(StateFilter(SellState.amount_usdt))
async def sell_amount(message: types.Message, state: FSMContext):
    try: val = float(message.text.replace(',', '.'))
    except: return await message.answer("⚠️ Число!")
    if val < 5: return await message.answer("⛔ Минимум 5 USDT")
    await state.update_data(usdt_amount=val)
    await state.set_state(SellState.card)
    await message.answer("✅ Номер карты для получения рублей:", reply_markup=cancel_menu)

@dp.message(StateFilter(SellState.card))
async def sell_card(message: types.Message, state: FSMContext):
    data = await state.get_data()
    rub = round(data['usdt_amount'] * data['course'], 2)
    deal_id = db_add_deal(message.from_user.id, 'SELL', data['usdt_amount'], rub)
    await state.update_data(deal_id=deal_id, card=message.text, rub_amount=rub)
    await state.set_state(SellState.proof)
    await message.answer(f"📝 **Заявка #{deal_id}**\nВы получите: **{rub} RUB**\n📥 Переведите USDT на: `{ADMIN_WALLET}`\n⏳ Жду скриншот.", reply_markup=cancel_menu)

@dp.message(F.photo)
async def handle_proof(message: types.Message, state: FSMContext):
    st = await state.get_state()
    if st not in [BuyState.proof, SellState.proof]: return
    data = await state.get_data()
    deal_id = data['deal_id']
    await message.answer("✅ **Принято!** Ждите подтверждения.", reply_markup=main_menu)
    if ADMIN_ID:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ ОК", callback_data=f"ok_{deal_id}_{message.from_user.id}"),
             InlineKeyboardButton(text="❌ НЕТ", callback_data=f"no_{deal_id}_{message.from_user.id}")]
        ])
        await bot.send_message(ADMIN_ID, f"🚨 **ЗАЯВКА #{deal_id}**\nТип: {st}\nСумма: {data.get('rub_amount')} RUB\n👤: @{message.from_user.username}", reply_markup=kb)
        await message.forward(ADMIN_ID)
    await state.clear()

# --- АДМИНКА ---
@dp.callback_query(F.data.startswith("ok_"))
async def admin_ok(callback: CallbackQuery):
    try:
        _, deal_id, user_id_str = callback.data.split("_")
        user_id = int(user_id_str)
        print(f"🔧 Админ подтверждает сделку #{deal_id} для юзера {user_id}...")
        
        db_update_deal_status(deal_id, 'success')
        
        user_info = db_get_user(user_id)
        if user_info:
            referrer_id = user_info[2]
            if referrer_id:
                print(f"🎁 Найден реферер {referrer_id}! Начисляем бонус.")
                db_add_bonus(referrer_id, REFERRAL_BONUS)
                try: await bot.send_message(referrer_id, f"💰 **Вам начислен бонус {REFERRAL_BONUS} USDT** за сделку вашего реферала!")
                except: pass
            else:
                print("👀 У этого юзера нет реферера.")
        else:
            print("⚠️ Ошибка: Юзер не найден в базе данных.")

        try: await bot.send_message(user_id, "✅ Заявка выполнена!")
        except: pass
        await callback.message.edit_text(f"✅ #{deal_id} Выполнена.")
        
    except Exception as e:
        print(f"❌ ОШИБКА АДМИНКИ: {e}")
        await callback.message.answer("Ошибка при подтверждении. Смотри консоль.")

@dp.callback_query(F.data.startswith("no_"))
async def admin_no(callback: CallbackQuery):
    _, deal_id, user_id = callback.data.split("_")
    db_update_deal_status(deal_id, 'cancel')
    try: await bot.send_message(user_id, "❌ Отклонено.")
    except: pass
    await callback.message.edit_text(f"❌ #{deal_id} Отменена.")

# --- ПРОФИЛЬ (ВЕРСИЯ БЕЗ КАВЫЧЕК) ---
@dp.callback_query(F.data == "profile")
async def profile(callback: CallbackQuery):
    user_id = callback.from_user.id
    count, volume, refs = db_get_stats(user_id)
    user_data = db_get_user(user_id)
    balance = user_data[3] if user_data else 0.0
    
    bot_info = await bot.get_me()
    # Формируем ссылку
    ref_link = f"https://t.me/{bot_info.username}?start={user_id}"
    
    await callback.message.edit_text(
        f"👤 **Личный кабинет** 🆕\n"  # <--- Я добавил значок NEW, чтобы ты видел изменения
        f"🆔 ID: `{user_id}`\n"
        f"📊 Сделок: **{count}** (Объем: {volume} USDT)\n\n"
        f"👥 **Реферальная программа**\n"
        f"Приглашено: **{refs} чел.**\n"
        f"💰 Ваш бонусный баланс: **{balance:.2f} USDT**\n\n"
        f"🔗 **Ваша ссылка:**\n{ref_link}", # <--- Тут теперь чисто, БЕЗ кавычек
        reply_markup=back_menu,
        disable_web_page_preview=True
    )

@dp.callback_query(F.data == "rates")
async def rates(callback: CallbackQuery):
    b, s = get_courses()
    await callback.message.edit_text(f"""📊 **Курсы**\n🟢 Покупка: {b} RUB\n🔴 Продажа: {s} RUB""", reply_markup=back_menu)

async def start_bot():
    init_db()
    print("Бот запущен! 🚀")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(start_bot())