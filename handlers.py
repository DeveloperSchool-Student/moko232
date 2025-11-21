from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
from sqlalchemy import select, desc
from database import async_session
from mechanics import get_meme_chart
from config import IsAdmin, ADMIN_IDS, Config
import re
import asyncio
import random
from datetime import datetime, timedelta
from models import User, Meme, Portfolio, PromoCode, UsedPromo, News, Item, UserItem, Bet, Clan, LotteryTicket
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import func

router = Router()

ITEMS_PER_PAGE = 5 # Показуємо по 5 акцій, бо їх всього 10

# --- 10 РАНГІВ ПРОГРЕСУ ---
def calculate_rank(net_worth):
    if net_worth < 500: return "🦠 Планктон"            # 1
    if net_worth < 1500: return "Барон "             # 2
    if net_worth < 3000: return "Віконт"           # 3
    if net_worth < 5000: return "Граф"         # 4
    if net_worth < 10000: return "Маркіз"           # 5
    if net_worth < 25000: return "Герцог"     # 6
    if net_worth < 50000: return "Король"               # 7
    if net_worth < 100000: return "🐙 Кракен"           # 8
    if net_worth < 500000: return "👑 Вовк з Уолл-стріт" # 9
    return "🚀 Імператор"                         # 10

# --- ДОПОМІЖНІ ФУНКЦІЇ ---
async def get_user(session, telegram_id):
    result = await session.execute(select(User).where(User.telegram_id == telegram_id))
    return result.scalar_one_or_none()

async def get_net_worth(session, user):
    pf_items = await session.execute(select(Portfolio).where(Portfolio.user_id == user.id))
    items = pf_items.scalars().all()
    stock_value = 0
    for item in items:
        meme = await session.get(Meme, item.meme_id)
        stock_value += item.quantity * meme.current_price
    return user.balance + stock_value

# --- ОБРОБНИКИ ---

@router.message(Command("start"))
async def cmd_start(message: types.Message):
    # Перевіряємо аргументи команди (чи є реферальний код)
    # Повідомлення виглядає як "/start 12345", де 12345 - ID того, хто запросив
    args = message.text.split()
    referrer_candidate = None
    
    if len(args) > 1 and args[1].isdigit():
        referrer_candidate = int(args[1])

    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        
        if not user:
            # --- РЕЄСТРАЦІЯ НОВОГО ГРАВЦЯ ---
            user = User(
                telegram_id=message.from_user.id,
                username=message.from_user.username,
                full_name=message.from_user.full_name,
                referrer_id=referrer_candidate if referrer_candidate != message.from_user.id else None
            )
            session.add(user)
            
            start_text = (
                "🚀 <b>Ласкаво просимо на Meme Stock Exchange!</b>\n\n"
                "Твій старт: <b>$500</b>.\n"
            )

            # --- ЛОГІКА НАГОРОДИ ЗА ЗАПРОШЕННЯ ---
            if referrer_candidate and referrer_candidate != message.from_user.id:
                # Шукаємо того, хто запросив, в базі
                referrer_user = (await session.execute(select(User).where(User.telegram_id == referrer_candidate))).scalar_one_or_none()
                
                if referrer_user:
                    reward = 500.0
                    # Нараховуємо бонуси обом
                    user.balance += reward
                    referrer_user.balance += reward
                    
                    start_text += f"🎁 Ти перейшов за посиланням друга! Отримано бонус: <b>+${reward}</b>\n"
                    
                    # Сповіщаємо того, хто запросив
                    try:
                        await message.bot.send_message(
                            referrer_user.telegram_id,
                            f"🤝 <b>Новий реферал!</b>\n"
                            f"Гравець {message.from_user.full_name} зареєструвався за твоїм посиланням.\n"
                            f"Твій бонус: <b>+${reward}</b>"
                        , parse_mode="HTML")
                    except:
                        pass # Якщо заблокував бота

            await session.commit()
            
            await message.answer(
                start_text + "\nТисни /help щоб дізнатись правила або /market щоб торгувати.", 
                parse_mode="HTML"
            )
            
        else:
            # Якщо юзер вже є
            if user.username != message.from_user.username or user.full_name != message.from_user.full_name:
                user.username = message.from_user.username
                user.full_name = message.from_user.full_name
                await session.commit()
                
            await message.answer(f"👋 З поверненням, {user.full_name}! Твій кеш: ${user.balance:.2f}")

@router.message(Command("help"))
async def cmd_help(message: types.Message):
    text = (
        "📖 <b>Як грати?</b>\n\n"
        "1. <b>Ринок живий:</b> Ціни змінюються кожні 60 секунд автоматично!(+на ринок впливають гравці)\n"
        "2. <b>Ціль:</b> Купуй дешево, продавай дорого.\n"
        "3. <b>Ранги:</b> Збільшуй капітал, щоб пройти шлях від Планктона до Імператора.\n\n"
        "<b>Команди:</b>\n"
        "/market - Купити/Продати акції\n"
        "/portfolio - Твої активи\n"
        "/send - Відправити гроші іншому гравцю\n"
        "/bet - Ставки на рух цін\n"
        "/profile - Твій ранг і статистика\n"
        "/leaderboard - Рейтинг гравців\n"
        "/daily - Щоденний бонус\n"
        "/news - Останні новини біржі\n"
        "/help - Це довідка\n\n"
        "Успіхів на біржі! 💰📈"
        "Звязатися з підтримкою: @hedgehogMSM"
    )
    await message.answer(text, parse_mode="HTML")


# --- РИНОК ---

async def generate_market_keyboard(page: int, user_id: int):
    async with async_session() as session:
        total_memes = (await session.execute(select(Meme))).scalars().all()
        total_pages = (len(total_memes) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
        
        offset = page * ITEMS_PER_PAGE
        memes_query = select(Meme).limit(ITEMS_PER_PAGE).offset(offset)
        memes = (await session.execute(memes_query)).scalars().all()

        kb = []
        row = []
        for meme in memes:
            # Додаємо стрілочку, щоб показати рух (можна потім ускладнити)
            btn_text = f"{meme.ticker} ${meme.current_price:.2f}"
            row.append(InlineKeyboardButton(text=btn_text, callback_data=f"view_{meme.id}"))
            if len(row) == 2:
                kb.append(row)
                row = []
        if row: kb.append(row)

        nav_row = []
        if page > 0:
            nav_row.append(InlineKeyboardButton(text="⬅️", callback_data=f"market_page_{page-1}_{user_id}")) # Додаємо ID
        # Додаємо ID користувача для перевірки власності на кнопці сторінки
        nav_row.append(InlineKeyboardButton(text=f"📄 {page+1}/{total_pages}", callback_data=f"market_ignore_{user_id}"))
        if page < total_pages - 1:
            nav_row.append(InlineKeyboardButton(text="➡️", callback_data=f"market_page_{page+1}_{user_id}")) # Додаємо ID
            
        kb.append(nav_row)
        return InlineKeyboardMarkup(inline_keyboard=kb)
    


@router.message(Command("news"))
async def cmd_news(message: types.Message):
    async with async_session() as session:
        # Беремо 5 останніх новин
        query = select(News).order_by(News.timestamp.desc()).limit(5)
        result = await session.execute(query)
        news_list = result.scalars().all()
        
        if not news_list:
            return await message.answer("📭 На ринку поки що тихо... Новин немає.")
        
        text = "📰 <b>Свіжі Новини Біржі</b>\n────────────────\n\n"
        
        for news in news_list:
            # Форматуємо час (години:хвилини)
            time_str = news.timestamp.strftime("%H:%M")
            text += f"🕒 <b>{time_str}</b> | {news.content}\n\n"
            
        await message.answer(text, parse_mode="HTML")

@router.message(Command("market"))
async def cmd_market(message: types.Message):
    # Передаємо ID користувача в клавіатуру, щоб запобігти чужим гортати сторінки
    kb = await generate_market_keyboard(0, message.from_user.id)
    await message.answer("📈 <b>Ринок Акцій</b>\nОбирай актив:", reply_markup=kb, parse_mode="HTML")

@router.callback_query(F.data.startswith("market_page_"))
async def cb_market_page(callback: types.CallbackQuery):
    _, _, page_str, original_user_id_str = callback.data.split("_")
    page = int(page_str)
    original_user_id = int(original_user_id_str)

    if callback.from_user.id != original_user_id:
        return await callback.answer("🚫 Це не твій ринок. Тисни /market", show_alert=True)

    kb = await generate_market_keyboard(page, original_user_id)
    
    # --- ЗМІНА ТУТ: Перевіряємо, чи це фото ---
    if callback.message.content_type == types.ContentType.PHOTO:
        await callback.message.delete()
        await callback.message.answer("📈 <b>Ринок Акцій</b>\nОбирай актив:", reply_markup=kb, parse_mode="HTML")
    else:
        # Якщо це був просто текст (гортання сторінок), то редагуємо
        try:
            await callback.message.edit_reply_markup(reply_markup=kb)
        except Exception:
            await callback.answer()

@router.callback_query(F.data.startswith("market_ignore_"))
async def cb_market_ignore(callback: types.CallbackQuery):
    # market_ignore_<user_id>
    original_user_id = int(callback.data.split("_")[2])
    # ПЕРЕВІРКА ВЛАСНОСТІ
    if callback.from_user.id != original_user_id:
        return await callback.answer("🚫 Це не твій ринок. Тисни /market", show_alert=True)
    await callback.answer("Це номер сторінки")

# --- ДЕТАЛІ ТА ТОРГІВЛЯ ---

@router.callback_query(F.data.startswith("view_"))
async def cb_view_meme(callback: types.CallbackQuery):
    meme_id = int(callback.data.split("_")[1])
    telegram_id = callback.from_user.id # Це ID з телеграму
    
    async with async_session() as session:
        meme = await session.get(Meme, meme_id)
        if not meme: return await callback.answer("Акція зникла", show_alert=True)
        
        # --- ВИПРАВЛЕННЯ ПОЧАТОК ---
        # 1. Спочатку отримуємо самого юзера з БД
        user = await get_user(session, telegram_id)
        
        # Якщо юзера немає (наприклад, після /reset_world), просимо старт
        if not user:
            return await callback.answer("⚠️ Спочатку натисни /start", show_alert=True)

        # 2. Тепер використовуємо user.id (внутрішній ID, наприклад 1), а не telegram_id (6500735335)
        pf_item = (await session.execute(
            select(Portfolio).where(Portfolio.user_id==user.id, Portfolio.meme_id==meme.id)
        )).scalar_one_or_none()
        # --- ВИПРАВЛЕННЯ КІНЕЦЬ ---

        user_quantity = pf_item.quantity if pf_item else 0

        text = (
            f"📊 <b>{meme.ticker}</b>\n"
            f"Ціна: <b>${meme.current_price:.4f}</b>\n"
            f"Волатильність: {meme.volatility*100:.0f}% (Ризик)\n"
            f"Твої акції: <b>{user_quantity} шт</b>"
        )
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🟢 Купити", callback_data=f"prompt_buy_{meme.id}_{telegram_id}"),
                InlineKeyboardButton(text="🔴 Продати", callback_data=f"prompt_sell_{meme.id}_{telegram_id}")
            ],
            [InlineKeyboardButton(text="📉 Графік", callback_data=f"chart_{meme.id}_{meme.ticker}")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data=f"market_page_0_{telegram_id}")]
        ])
        
        try:
            await callback.message.delete()
        except:
            pass

        if meme.image_url:
            await callback.message.answer_photo(photo=meme.image_url, caption=text, reply_markup=kb, parse_mode="HTML")
        else:
            await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")

# --- НОВІ ОБРОБНИКИ ДЛЯ ВИБОРУ КІЛЬКОСТІ (ЗАПИТ КІЛЬКОСТІ) ---

@router.callback_query(F.data.startswith("prompt_buy_"))
async def cb_prompt_buy(callback: types.CallbackQuery):
    # prompt_buy_<meme_id>_<user_id>
    _, _, meme_id_str, original_user_id_str = callback.data.split("_")
    meme_id = int(meme_id_str)
    original_user_id = int(original_user_id_str)
    
    # ПЕРЕВІРКА ВЛАСНОСТІ (УКРІПЛЕННЯ ВІД КОНФЛІКТУ В ГРУПІ)
    if callback.from_user.id != original_user_id:
        return await callback.answer("🚫 Ця дія не для тебе. Тисни /market", show_alert=True)
    
    async with async_session() as session:
        user = await get_user(session, original_user_id)
        meme = await session.get(Meme, meme_id)

        if not user or not meme: 
            return await callback.answer("Сталася помилка.", show_alert=True)

        # Визначаємо MAX, який може купити користувач
        max_buy = int(user.balance // meme.current_price)
        
        if max_buy < 1:
            return await callback.answer(f"❌ Недостатньо коштів для купівлі 1 {meme.ticker}. (Потрібно ${meme.current_price:.2f})", show_alert=True)

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="1 шт", callback_data=f"buy_EXECUTE_{meme.id}_1_{original_user_id}"),
                InlineKeyboardButton(text="5 шт", callback_data=f"buy_EXECUTE_{meme.id}_5_{original_user_id}"),
                InlineKeyboardButton(text="10 шт", callback_data=f"buy_EXECUTE_{meme.id}_10_{original_user_id}"),
            ],
            [
                # Кнопка MAX
                InlineKeyboardButton(text=f"MAX ({max_buy} шт)", callback_data=f"buy_EXECUTE_{meme.id}_{max_buy}_{original_user_id}"),
            ],
            [
                InlineKeyboardButton(text="🔙 Скасувати", callback_data=f"view_{meme.id}") # Повернутися до деталей
            ]
        ])
        
        text = (
            f"🛒 <b>Купити {meme.ticker}</b> (Ціна: ${meme.current_price:.4f})\n"
            f"Баланс: ${user.balance:.2f}\n\n"
            f"Скільки ти хочеш купити? (Максимум {max_buy} шт)"
        )

        # --- ЗМІНА ТУТ: Видаляємо фото, шлемо текст ---
        await callback.message.delete()
        await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")

@router.callback_query(F.data.startswith("prompt_sell_"))
async def cb_prompt_sell(callback: types.CallbackQuery):
    _, _, meme_id_str, original_user_id_str = callback.data.split("_")
    meme_id = int(meme_id_str)
    original_user_id = int(original_user_id_str)
    
    if callback.from_user.id != original_user_id:
        return await callback.answer("🚫 Ця дія не для тебе. Тисни /market", show_alert=True)
    
    async with async_session() as session:
        user = await get_user(session, original_user_id)
        meme = await session.get(Meme, meme_id)

        pf_item = (await session.execute(
            select(Portfolio).where(Portfolio.user_id==user.id, Portfolio.meme_id==meme.id)
        )).scalar_one_or_none()
        
        user_quantity = pf_item.quantity if pf_item else 0
        
        if user_quantity < 1:
            return await callback.answer(f"❌ У тебе немає акцій {meme.ticker} для продажу.", show_alert=True)

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="1 шт", callback_data=f"sell_EXECUTE_{meme.id}_1_{original_user_id}"),
                InlineKeyboardButton(text="5 шт", callback_data=f"sell_EXECUTE_{meme.id}_5_{original_user_id}"),
                InlineKeyboardButton(text="10 шт", callback_data=f"sell_EXECUTE_{meme.id}_10_{original_user_id}"),
            ],
            [
                InlineKeyboardButton(text=f"ВСЕ ({user_quantity} шт)", callback_data=f"sell_EXECUTE_{meme.id}_{user_quantity}_{original_user_id}"),
            ],
            [
                InlineKeyboardButton(text="🔙 Скасувати", callback_data=f"view_{meme.id}")
            ]
        ])
        
        # --- ВИПРАВЛЕННЯ ---
        # Перевіряємо, яка комісія у гравця (чи є ліцензія)
        current_com = Config.SELL_COMMISSION_BROKER if user.has_license else Config.SELL_COMMISSION_DEFAULT
        com_percent = current_com * 100

        text = (
            f"💸 <b>Продати {meme.ticker}</b>\n"
            f"Ціна ринку: ${meme.current_price:.4f}\n"
            f"📉 <b>Комісія біржі: {com_percent:.0f}%</b>\n\n"
            f"Твої акції: <b>{user_quantity} шт</b>\n"
            f"Скільки продаємо?"
        )

        await callback.message.delete()
        await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")

@router.callback_query(F.data.startswith("buy_EXECUTE_"))
async def cb_execute_buy(callback: types.CallbackQuery):
    # buy_EXECUTE_<meme_id>_<quantity>_<user_id>
    _, _, meme_id_str, quantity_str, original_user_id_str = callback.data.split("_")
    meme_id = int(meme_id_str)
    quantity = int(quantity_str)
    original_user_id = int(original_user_id_str)
    
    # ПЕРЕВІРКА ВЛАСНОСТІ
    if callback.from_user.id != original_user_id:
        return await callback.answer("🚫 Ця дія не для тебе. Тисни /market", show_alert=True)
    
    async with async_session() as session:
        user = await get_user(session, original_user_id)
        meme = await session.get(Meme, meme_id)
        
        total_cost = meme.current_price * quantity

        # ФІНАЛЬНА ПЕРЕВІРКА БАЛАНСУ
        if user.balance < total_cost:
            return await callback.answer(
                f"❌ Не вистачає коштів!\nПотрібно: ${total_cost:.2f}\nТвій баланс: ${user.balance:.2f}", 
                show_alert=True
            )
        
        # Перевірка на "зникнення" Meme.current_price (хоча малоймовірно)
        if total_cost <= 0:
            return await callback.answer("❌ Неккоректна ціна.", show_alert=True)


        # Виконання транзакції
        user.balance -= total_cost
        
        pf_item = (await session.execute(select(Portfolio).where(Portfolio.user_id==user.id, Portfolio.meme_id==meme.id))).scalar_one_or_none()
        if pf_item: pf_item.quantity += quantity
        else: session.add(Portfolio(user_id=user.id, meme_id=meme.id, quantity=quantity))
        
        # --- ДОДАЄМО ВПЛИВ НА РИНОК ---
        meme.trade_volume += quantity  # Купівля штовхає ціну вгору (+)
        
        await session.commit()
        await callback.answer(f"✅ +{quantity} {meme.ticker} (${total_cost:.2f})")
        # Повертаємо користувача до деталей акції
        # Для коректного повернення до view, використовуємо callback.message
        # імітуючи натискання кнопки view
        new_callback = callback.model_copy(update={"data": f"view_{meme.id}"})
        await cb_view_meme(new_callback)



@router.callback_query(F.data.startswith("chart_"))
async def cb_chart(callback: types.CallbackQuery):
    _, meme_id, ticker = callback.data.split("_")
    meme_id = int(meme_id)
    await callback.answer("⏳ Генерую...")
    
    chart_buf = await get_meme_chart(meme_id, ticker)
    if chart_buf:
        photo = BufferedInputFile(chart_buf.read(), filename=f"{ticker}.png")
        await callback.message.answer_photo(photo, caption=f"Графік {ticker}")
    else:
        await callback.answer("Дані збираються...", show_alert=True)

@router.message(Command("portfolio"))
async def cmd_portfolio(message: types.Message):
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user: return await message.answer("⚠️ Натисни /start")
        
        pf_items = (await session.execute(select(Portfolio).where(Portfolio.user_id == user.id))).scalars().all()
        
        text = f"💼 <b>Портфель</b> | Кеш: ${user.balance:.2f}\n\n"
        total = user.balance
        for item in pf_items:
            meme = await session.get(Meme, item.meme_id)
            val = item.quantity * meme.current_price
            total += val
            text += f"🔹 <b>{meme.ticker}</b>: {item.quantity} шт (${val:.2f})\n"
        
        text += f"\n💰 Разом: <b>${total:.2f}</b>"
        await message.answer(text, parse_mode="HTML")

@router.message(Command("leaderboard"))
async def cmd_leaderboard(message: types.Message):
    async with async_session() as session:
        # Беремо топ-10 найбагатших
        users = (await session.execute(select(User).order_by(desc(User.balance)).limit(10))).scalars().all()
        
        text = "🏆 <b>ТОП Гравців</b>\n"
        
        for i, u in enumerate(users, 1):
            # Логіка вибору імені:
            if u.username:
                name = f"@{u.username}"
            elif u.full_name:
                name = u.full_name
            else:
                name = f"ID {u.telegram_id}" # На випадок якщо чомусь немає імені
            
            # Додаємо емодзі для топ-3
            medal = ""
            if i == 1: medal = "🥇"
            elif i == 2: medal = "🥈"
            elif i == 3: medal = "🥉"
            
            text += f"{i}. {medal} <b>{name}</b>: ${u.balance:.2f}\n"
            
        await message.answer(text, parse_mode="HTML")
        
# --- ОБРОБНИК АДМІН-ПАНЕЛІ ---

@router.message(Command(re.compile(r"adm_(\w+)_(\d+)_(\w+)")), IsAdmin())
async def cmd_admin_manipulate(message: types.Message):
    # Команда має вигляд /adm_TICKER_COUNT_DIRECTION
    # Приклад: /adm_DOGE_5_UP
    
    import re
    
    # Використовуємо регулярний вираз для вилучення даних
    match = re.match(r"/adm_(\w+)_(\d+)_(\w+)", message.text)
    if not match:
        return await message.answer("❌ Помилка формату. Спробуй: /adm_TICKER_COUNT_DIRECTION. (Напр: /adm_DOGE_5_UP)")

    ticker, count_str, direction = match.groups()
    
    # Перевірка напрямку
    direction = direction.upper()
    if direction not in ['UP', 'DOWN', 'NONE']:
        return await message.answer("❌ Напрямок має бути UP, DOWN або NONE.")
    
    # Перевірка кількості
    try:
        count = int(count_str)
        if count <= 0 or count > 60: # Обмежимо, наприклад, 1 годиною
            return await message.answer("❌ Кількість хвилин має бути від 1 до 60.")
    except ValueError:
        return await message.answer("❌ Кількість має бути числом.")
        
    async with async_session() as session:
        # Шукаємо акцію за тікером
        meme_query = select(Meme).where(Meme.ticker == ticker.upper())
        meme = (await session.execute(meme_query)).scalar_one_or_none()
        
        if not meme:
            return await message.answer(f"❌ Акцію з тікером <b>{ticker.upper()}</b> не знайдено.")
            
        # Зберігаємо зміни
        meme.manipulation_mode = direction
        meme.manipulation_remaining = count
        await session.commit()
        
        if direction == 'NONE':
             await message.answer(f"✅ Маніпуляція ціною <b>{meme.ticker}</b> скасована.")
        else:
             await message.answer(
                f"🔥 <b>Успіх!</b> Встановлено маніпуляцію для <b>{meme.ticker}</b>:\n"
                f"Напрямок: <b>{direction}</b>\n"
                f"Тривалість: <b>{count} хв</b>"
            , parse_mode="HTML")
             
@router.message(Command("broadcast"), IsAdmin())
async def cmd_broadcast(message: types.Message):
    # Перевіряємо, чи є текст після команди
    # message.text має вигляд "/broadcast Привіт всім"
    content = message.text.replace("/broadcast", "", 1).strip()
    
    if not content:
        return await message.answer("❌ <b>Помилка!</b> Введи текст повідомлення.\nПриклад: <code>/broadcast Знижки на DOGE!</code>", parse_mode="HTML")

    start_msg = await message.answer(f"⏳ Починаю розсилку для гравців...")
    
    async with async_session() as session:
        # Отримуємо список усіх ID користувачів
        result = await session.execute(select(User.telegram_id))
        users_ids = result.scalars().all()

    count_success = 0
    count_error = 0
    
    for user_id in users_ids:
        try:
            # Формуємо повідомлення
            text = f"📢 <b>ОГОЛОШЕННЯ ВІД БІРЖІ</b>\n\n{content}"
            
            # Відправляємо (використовуємо message.bot для відправки іншим)
            await message.bot.send_message(chat_id=user_id, text=text, parse_mode="HTML")
            count_success += 1
            
            # Дуже важливо! Робимо маленьку паузу, щоб не отримати бан від Telegram
            await asyncio.sleep(0.05) 
            
        except Exception:
            # Якщо користувач заблокував бота, просто рахуємо як помилку
            count_error += 1

    await start_msg.edit_text(
        f"✅ <b>Розсилка завершена!</b>\n\n"
        f"📨 Відправлено: <b>{count_success}</b>\n"
        f"🚫 Не доставлено (блокували): <b>{count_error}</b>",
        parse_mode="HTML"
    )
    
@router.message(Command("daily"))
async def cmd_daily(message: types.Message):
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user: return await message.answer("⚠️ Натисни /start")

        now = datetime.utcnow()
        
        # Перевірка часу (якщо бонус вже брали)
        if user.last_bonus_date:
            delta = now - user.last_bonus_date
            if delta < timedelta(days=1):
                # Рахуємо, скільки часу залишилось
                wait_time = timedelta(days=1) - delta
                hours, remainder = divmod(int(wait_time.total_seconds()), 3600)
                minutes, _ = divmod(remainder, 60)
                return await message.answer(
                    f"⏳ <b>Рано!</b> Бонус доступний раз на 24 години.\n"
                    f"Чекай ще: <b>{hours} год {minutes} хв</b>",
                    parse_mode="HTML"
                )

        # Видача бонусу
        bonus_amount = random.randint(100, 500) # Випадкова сума від 100 до 500
        user.balance += bonus_amount
        user.last_bonus_date = now
        
        await session.commit()
        
        await message.answer(
            f"🎁 <b>Щоденний бонус!</b>\n"
            f"Ти отримав: <b>${bonus_amount}</b>\n"
            f"Поточний баланс: <b>${user.balance:.2f}</b>\n\n"
            f"Приходь завтра за новим!",
            parse_mode="HTML"
        )
        
# --- СИСТЕМА ПРОМОКОДІВ ---

@router.message(Command("newcode"), IsAdmin())
async def cmd_create_promo(message: types.Message):
    # Формат: /newcode НАЗВА СУМА ХВИЛИНИ
    # Приклад: /newcode GAME 1000 120
    try:
        parts = message.text.split()
        if len(parts) != 4:
            raise ValueError
        
        code_name = parts[1].upper() # Робимо великими літерами
        amount = float(parts[2])
        minutes = int(parts[3])
        
        valid_until = datetime.utcnow() + timedelta(minutes=minutes)
        
    except ValueError:
        return await message.answer("❌ Формат: <code>/newcode НАЗВА СУМА ХВИЛИНИ</code>\nПриклад: /newcode GAME 500 60", parse_mode="HTML")

    async with async_session() as session:
        # Перевіряємо, чи код вже існує
        existing = await session.execute(select(PromoCode).where(PromoCode.code == code_name))
        if existing.scalar_one_or_none():
            return await message.answer("❌ Такий код вже існує!")

        new_promo = PromoCode(code=code_name, amount=amount, valid_until=valid_until)
        session.add(new_promo)
        await session.commit()
        
        await message.answer(
            f"✅ <b>Промокод створено!</b>\n\n"
            f"🔑 Код: <code>{code_name}</code>\n"
            f"💰 Сума: ${amount}\n"
            f"⏳ Діє: {minutes} хв (до {valid_until.strftime('%H:%M UTC')})",
            parse_mode="HTML"
        )

@router.message(Command("use"))
async def cmd_use_promo(message: types.Message):
    # Формат: /use CODE
    parts = message.text.split()
    if len(parts) != 2:
        return await message.answer("✍️ Введи код. Приклад: <code>/use GAME</code>", parse_mode="HTML")
    
    code_input = parts[1].upper().strip()
    
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user: return await message.answer("⚠️ Спочатку тисни /start")
        
        # Шукаємо код
        promo = (await session.execute(select(PromoCode).where(PromoCode.code == code_input))).scalar_one_or_none()
        
        if not promo:
            return await message.answer("❌ Такого коду не існує.")
            
        # 1. Перевірка часу
        if datetime.utcnow() > promo.valid_until:
            return await message.answer("⌛️ <b>Термін дії коду вийшов!</b> Ти не встиг.", parse_mode="HTML")
        
        # 2. Перевірка, чи вже використовував
        used_check = await session.execute(
            select(UsedPromo).where(UsedPromo.user_id == user.id, UsedPromo.promo_id == promo.id)
        )
        if used_check.scalar_one_or_none():
            return await message.answer("❌ Ти вже активував цей код.")
            
        # НАРАХУВАННЯ
        user.balance += promo.amount
        
        # Записуємо, що використав
        usage_record = UsedPromo(user_id=user.id, promo_id=promo.id)
        session.add(usage_record)
        
        await session.commit()
        
        await message.answer(f"🎉 <b>Успіх!</b>\nТи отримав <b>${promo.amount}</b>!\nБаланс: ${user.balance:.2f}", parse_mode="HTML")

# handlers.py

@router.message(Command("send"))
async def cmd_send(message: types.Message):
    # Очікуємо формат: /send СУМА КОМУ
    args = message.text.split()
    
    if len(args) != 3:
        return await message.answer(
            "💸 <b>Переказ коштів</b>\n"
            "Використання: <code>/send СУМА @USERNAME</code>\n"
            "Приклад: <code>/send 500 @friend_login</code>",
            parse_mode="HTML"
        )

    try:
        amount = float(args[1])
        target_input = args[2]
    except ValueError:
        return await message.answer("❌ Сума має бути числом.")

    if amount <= 0:
        return await message.answer("❌ Сума має бути більше нуля.")

    async with async_session() as session:
        # 1. Отримуємо відправника
        sender = await get_user(session, message.from_user.id)
        if not sender: return await message.answer("⚠️ Спочатку натисни /start")

        if sender.balance < amount:
            return await message.answer(f"❌ Недостатньо коштів. Твій баланс: ${sender.balance:.2f}")

        # 2. Шукаємо отримувача
        recipient = None
        
        # Якщо ввели юзернейм (починається з @)
        if target_input.startswith("@"):
            clean_username = target_input[1:] # Прибираємо @
            # Шукаємо в базі (username)
            result = await session.execute(select(User).where(User.username == clean_username))
            recipient = result.scalar_one_or_none()
        
        # Якщо ввели ID (число)
        elif target_input.isdigit():
            target_id = int(target_input)
            result = await session.execute(select(User).where(User.telegram_id == target_id))
            recipient = result.scalar_one_or_none()

        # Перевірки отримувача
        if not recipient:
            return await message.answer(
                f"❌ Користувача <b>{target_input}</b> не знайдено в базі гри.\n"
                f"Він має натиснути /start у боті хоча б раз, або перевірте правильність нікнейму.",
                parse_mode="HTML"
            )
            
        if recipient.id == sender.id:
            return await message.answer("❌ Не можна надсилати гроші самому собі.")

        # 3. Виконуємо транзакцію
        sender.balance -= amount
        recipient.balance += amount
        
        await session.commit()
        
        # 4. Сповіщення
        await message.answer(
            f"✅ <b>Успішно!</b>\n"
            f"Відправлено: <b>${amount:.2f}</b>\n"
            f"Отримувач: {recipient.full_name}", 
            parse_mode="HTML"
        )
        
        # Пробуємо написати отримувачу в особисті (якщо він не заблокував бота)
        try:
            await message.bot.send_message(
                chat_id=recipient.telegram_id,
                text=f"💸 <b>Вам надійшов переказ!</b>\n\n"
                     f"Сума: <b>${amount:.2f}</b>\n"
                     f"Від: {sender.full_name} (@{sender.username})",
                parse_mode="HTML"
            )
        except Exception:
            pass # Якщо у отримувача заблокований бот, помилку ігноруємо
        
# handlers.py

@router.message(Command("privacy"))
async def cmd_privacy(message: types.Message):
    text = (
        "🔒 <b>Політика конфіденційності та Умови використання</b>\n\n"
        
        "<b>1. Збір даних</b>\n"
        "Ми зберігаємо лише необхідний мінімум даних для функціонування гри:\n"
        "• Ваш Telegram ID (для ідентифікації акаунту).\n"
        "• Ваше Ім'я та Username (для відображення в рейтингах).\n"
        "• Ігрову статистику (баланс, портфель акцій).\n\n"
        
        "<b>2. Використання даних</b>\n"
        "Ваші дані використовуються виключно для забезпечення ігрового процесу. "
        "Ми не передаємо їх третім особам і не використовуємо для реклами.\n\n"
        
        "<b>3. ВІДМОВА ВІД ВІДПОВІДАЛЬНОСТІ (ВАЖЛИВО)</b>\n"
        "⚠️ <b>Цей бот є ГРОЮ-СИМУЛЯТОРОМ.</b>\n"
        "• Всі гроші в боті ($) є <b>віртуальними</b> і не мають жодної реальної цінності.\n"
        "• Їх неможливо вивести, обміняти на реальні гроші або товари.\n"
        "• Гра не є фінансовою порадою, біржею або платформою для азартних ігор.\n"
        "• Адміністрація не несе відповідальності за ваші віртуальні збитки.\n\n"
        
        "<b>4. Видалення даних</b>\n"
        "Якщо ви хочете видалити свій акаунт і всі дані про себе, будь ласка, зв'яжіться з адміністратором.\n\n"
        
        "<i>Використовуючи цього бота, ви автоматично погоджуєтесь із цими правилами.</i>"
    )
    # Додаємо кнопку, щоб приховати повідомлення
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 Згорнути", callback_data="delete_msg")]
    ])
    await message.answer(text, parse_mode="HTML", reply_markup=kb)

# Додамо маленьку функцію для кнопки "Згорнути", щоб не засмічувати чат
@router.callback_query(F.data == "delete_msg")
async def cb_delete_msg(callback: types.CallbackQuery):
    await callback.message.delete()
    # await callback.answer() # Можна не відповідати, бо повідомлення видалиться
    
# handlers.py

@router.message(Command("bet"))
async def cmd_bet(message: types.Message):
    # Формат: /bet TIKER DIRECTION AMOUNT
    # Приклад: /bet BTC UP 100
    
    args = message.text.split()
    if len(args) != 4:
        return await message.answer(
            "🎰 <b>Бінарні Опціони</b>\n"
            "Вгадай, куди піде ціна за 1 хвилину!\n\n"
            "Формат: <code>/bet ТІКЕР КУДИ СУМА</code>\n"
            "Приклад: <code>/bet BTC UP 100</code>\n"
            "Приклад: <code>/bet DOGE DOWN 500</code>",
            parse_mode="HTML"
        )

    ticker_input = args[1].upper()
    direction_input = args[2].upper()
    try:
        amount = float(args[3])
    except ValueError:
        return await message.answer("❌ Сума має бути числом.")

    if direction_input not in ["UP", "DOWN"]:
        return await message.answer("❌ Напрямок має бути <b>UP</b> (вгору) або <b>DOWN</b> (вниз).", parse_mode="HTML")
        
    if amount <= 0: return await message.answer("❌ Ставка має бути більше 0.")

    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user: return await message.answer("⚠️ Тисни /start")
        
        if user.balance < amount:
            return await message.answer(f"❌ Недостатньо коштів. Твій баланс: ${user.balance:.2f}")

        # Шукаємо акцію
        meme = (await session.execute(select(Meme).where(Meme.ticker == ticker_input))).scalar_one_or_none()
        if not meme:
            return await message.answer(f"❌ Акцію {ticker_input} не знайдено.")

        # РОБИМО СТАВКУ
        user.balance -= amount
        
        end_time = datetime.utcnow() + timedelta(seconds=Config.BET_DURATION)
        
        new_bet = Bet(
            user_id=user.id,
            meme_id=meme.id,
            amount=amount,
            direction=direction_input,
            start_price=meme.current_price,
            end_time=end_time
        )
        session.add(new_bet)
        await session.commit()
        
        await message.answer(
            f"🎲 <b>Ставку прийнято!</b>\n"
            f"Акція: <b>{meme.ticker}</b>\n"
            f"Напрямок: <b>{direction_input}</b>\n"
            f"Сума: <b>${amount:.2f}</b>\n"
            f"Поточна ціна: ${meme.current_price:.4f}\n\n"
            f"⏳ Результат через 1 хвилину...",
            parse_mode="HTML"
        )
        
# handlers.py

# ... (імпорти ті самі) ...

# --- ЛОГІКА МАГАЗИНУ ---

@router.message(Command("shop"))
async def cmd_shop(message: types.Message):
    # Головне меню магазину з категоріями
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 Нерухомість", callback_data="shop_cat_real_estate_0")],
        [InlineKeyboardButton(text="🚗 Автомобілі", callback_data="shop_cat_auto_0")],
        [InlineKeyboardButton(text="📱 Техніка", callback_data="shop_cat_tech_0")],
    ])
    
    await message.answer(
        "🛒 <b>Магазин Розкоші</b>\n\n"
        "Обери категорію, щоб витратити свої мільйони:", 
        reply_markup=kb, 
        parse_mode="HTML"
    )

async def generate_shop_keyboard(category: str, page: int, user_id: int):
    async with async_session() as session:
        # Отримуємо товари конкретної категорії
        query = select(Item).where(Item.category == category).order_by(Item.price)
        all_items = (await session.execute(query)).scalars().all()
        
        # Пагінація (по 5 штук на сторінку)
        ITEMS_PER_PAGE = 5
        total_pages = (len(all_items) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
        
        offset = page * ITEMS_PER_PAGE
        items_on_page = all_items[offset : offset + ITEMS_PER_PAGE]
        
        kb = []
        for item in items_on_page:
            btn_text = f"{item.emoji} {item.name} — ${item.price:,.0f}"
            kb.append([InlineKeyboardButton(text=btn_text, callback_data=f"buy_item_{item.id}_{user_id}")])
            
        # Кнопки навігації
        nav_row = []
        if page > 0:
            nav_row.append(InlineKeyboardButton(text="⬅️", callback_data=f"shop_cat_{category}_{page-1}"))
        
        nav_row.append(InlineKeyboardButton(text=f"📄 {page+1}/{total_pages}", callback_data="ignore"))
        
        if page < total_pages - 1:
            nav_row.append(InlineKeyboardButton(text="➡️", callback_data=f"shop_cat_{category}_{page+1}"))
            
        kb.append(nav_row)
        # Кнопка "Назад в меню"
        kb.append([InlineKeyboardButton(text="🔙 В меню магазину", callback_data="shop_menu")])
        
        return InlineKeyboardMarkup(inline_keyboard=kb)

@router.callback_query(F.data == "shop_menu")
async def cb_shop_menu_back(callback: types.CallbackQuery):
    # Повертаємо головне меню категорій
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 Нерухомість", callback_data="shop_cat_real_estate_0")],
        [InlineKeyboardButton(text="🚗 Автомобілі", callback_data="shop_cat_auto_0")],
        [InlineKeyboardButton(text="📱 Техніка", callback_data="shop_cat_tech_0")],
    ])
    await callback.message.edit_text(
        "🛒 <b>Магазин Розкоші</b>\nОбери категорію:", 
        reply_markup=kb, 
        parse_mode="HTML"
    )

@router.callback_query(F.data.startswith("shop_cat_"))
async def cb_shop_category(callback: types.CallbackQuery):
    # --- ВИПРАВЛЕННЯ ПОЧАТОК ---
    # Ми прибираємо початок "shop_cat_" (перші 9 букв)
    # Залишається: "real_estate_0" або "auto_0"
    clean_data = callback.data[9:] 
    
    # Тепер ділимо текст тільки по ОСТАННЬОМУ підкресленню (цифра 1 в кінці)
    # Це дозволяє зберегти "real_estate" цілим шматком
    category, page_str = clean_data.rsplit("_", 1)
    # --- ВИПРАВЛЕННЯ КІНЕЦЬ ---

    page = int(page_str)
    
    kb = await generate_shop_keyboard(category, page, callback.from_user.id)
    
    # Визначаємо гарну назву для заголовку
    cat_names = {"real_estate": "🏠 Нерухомість", "auto": "🚗 Автопарк", "tech": "📱 Техніка"}
    cat_title = cat_names.get(category, category)
    
    try:
        await callback.message.edit_text(
            f"🛒 <b>{cat_title}</b> (Сторінка {page+1})\nТисни на товар, щоб купити:", 
            reply_markup=kb, 
            parse_mode="HTML"
        )
    except Exception:
        await callback.answer()

@router.callback_query(F.data.startswith("buy_item_"))
async def cb_buy_item(callback: types.CallbackQuery):
    # buy_item_<item_id>_<original_user_id>
    parts = callback.data.split("_")
    item_id = int(parts[2])
    original_user_id = int(parts[3])
    
    # Захист від кліків чужих кнопок
    if callback.from_user.id != original_user_id:
        return await callback.answer("🚫 Це не твій магазин.", show_alert=True)
    
    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        item = await session.get(Item, item_id)
        
        if not item: return await callback.answer("Товар зник.")
        
        # Перевірка: чи вже є цей предмет?
        has_item = (await session.execute(
            select(UserItem).where(UserItem.user_id == user.id, UserItem.item_id == item.id)
        )).scalar_one_or_none()
        
        if has_item:
            return await callback.answer(f"😎 У тебе вже є {item.name}!", show_alert=True)
            
        if user.balance < item.price:
            return await callback.answer(f"❌ Тобі не вистачає ${(item.price - user.balance):.2f}", show_alert=True)
            
        # Покупка
        user.balance -= item.price
        session.add(UserItem(user_id=user.id, item_id=item.id))
        await session.commit()
        
        await callback.answer(f"✅ Куплено: {item.name}!", show_alert=True)
        
@router.message(Command("invite"))
async def cmd_invite(message: types.Message):
    bot_username = (await message.bot.get_me()).username
    link = f"https://t.me/{bot_username}?start={message.from_user.id}"
    
    text = (
        "🤝 <b>Партнерська програма</b>\n\n"
        "Запрошуй друзів і заробляй легкі гроші!\n"
        "За кожного друга ви <b>ОБИДВА</b> отримаєте по <b>$500</b>.\n\n"
        "👇 <b>Твоє посилання:</b>\n"
        f"<code>{link}</code>\n\n"
        "(Натисни на посилання, щоб скопіювати)"
    )
    await message.answer(text, parse_mode="HTML")
    
# ------------------------------------------
# ЗМІНА 1: Оновлена логіка комісії при продажу
# ------------------------------------------
@router.callback_query(F.data.startswith("sell_EXECUTE_"))
async def cb_execute_sell(callback: types.CallbackQuery):
    # ... (код розбору callback.data залишається таким самим) ...
    _, _, meme_id_str, quantity_str, original_user_id_str = callback.data.split("_")
    meme_id = int(meme_id_str)
    quantity = int(quantity_str)
    original_user_id = int(original_user_id_str)

    if callback.from_user.id != original_user_id:
        return await callback.answer("🚫 Ця дія не для тебе.", show_alert=True)

    async with async_session() as session:
        user = await get_user(session, original_user_id)
        meme = await session.get(Meme, meme_id)
        pf_item = (await session.execute(select(Portfolio).where(Portfolio.user_id==user.id, Portfolio.meme_id==meme.id))).scalar_one_or_none()

       # --- СТАЛО (Кращий варіант) ---
    if not pf_item:
     return await callback.answer("❌ Акцій вже немає.", show_alert=True)

# Якщо хоче продати 10, а є 9 - продаємо 9
     amount_to_sell = min(quantity, pf_item.quantity)

        # --- ЛОГІКА КОМІСІЇ ---
        current_commission_rate = Config.SELL_COMMISSION_BROKER if user.has_license else Config.SELL_COMMISSION_DEFAULT
        
        gross_total = meme.current_price * quantity
        commission = gross_total * current_commission_rate
        net_income = gross_total - commission
        
        user.balance += net_income
        pf_item.quantity -= quantity
        if pf_item.quantity == 0: await session.delete(pf_item)
        
        meme.trade_volume -= quantity 
        await session.commit()
        
        status_icon = "📜" if user.has_license else ""
        
        await callback.answer(
            f"💵 Продано {quantity} {meme.ticker} {status_icon}\n"
            f"Отримано: ${net_income:.2f}\n"
            f"Комісія: ${commission:.2f} ({current_commission_rate*100:.0f}%)",
            show_alert=True
        )
        new_callback = callback.model_copy(update={"data": f"view_{meme.id}"})
        await cb_view_meme(new_callback)

# ------------------------------------------
# ЗМІНА 2: Нове меню послуг (/services)
# ------------------------------------------
@router.message(Command("services"))
async def cmd_services(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📜 Ліцензія Брокера ($50k)", callback_data="buy_service_license")],
        [InlineKeyboardButton(text="🕵️ VIP Інсайд ($5k/год)", callback_data="buy_service_vip")],
        [InlineKeyboardButton(text="🎫 Лотерея ($500)", callback_data="menu_lottery")],
        [InlineKeyboardButton(text="🏷 Змінити Титул ($10k)", callback_data="buy_service_title")],
        [InlineKeyboardButton(text="🏢 Хедж-Фонди (Клани)", callback_data="menu_clans")]
    ])
    await message.answer("🛠 <b>Додаткові Послуги</b>", reply_markup=kb, parse_mode="HTML")

@router.callback_query(F.data.startswith("buy_service_"))
async def cb_buy_service(callback: types.CallbackQuery):
    service = callback.data.split("_")[2]
    user_id = callback.from_user.id
    
    async with async_session() as session:
        user = await get_user(session, user_id)
        
        if service == "license":
            if user.has_license:
                return await callback.answer("✅ У тебе вже є ліцензія!", show_alert=True)
            if user.balance < Config.LICENSE_COST:
                return await callback.answer("❌ Не вистачає грошей.", show_alert=True)
            
            user.balance -= Config.LICENSE_COST
            user.has_license = True
            await session.commit()
            await callback.answer("✅ Ліцензію придбано! Комісія тепер 1%.", show_alert=True)

        elif service == "vip":
            now = datetime.utcnow()
            if user.vip_until and user.vip_until > now:
                return await callback.answer(f"✅ VIP активний до {user.vip_until.strftime('%H:%M')}", show_alert=True)
            
            if user.balance < Config.VIP_COST:
                return await callback.answer("❌ Не вистачає грошей.", show_alert=True)
            
            user.balance -= Config.VIP_COST
            user.vip_until = now + timedelta(hours=1)
            await session.commit()
            await callback.answer("✅ VIP активовано на 1 годину!", show_alert=True)

        elif service == "title":
            # Тут ми просто кажемо юзеру команду
            await callback.answer("Введи команду: /settitle ТвійТитул", show_alert=True)

@router.message(Command("settitle"))
async def cmd_set_title(message: types.Message):
    args = message.text.split(maxsplit=1)
    if len(args) != 2:
        return await message.answer(f"✍️ Використання: <code>/settitle Імператор</code>\nВартість: ${Config.TITLE_CHANGE_COST}", parse_mode="HTML")
    
    new_title = args[1]
    if len(new_title) > 20: return await message.answer("❌ Занадто довгий титул.")

    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if user.balance < Config.TITLE_CHANGE_COST:
            return await message.answer("❌ Недостатньо коштів.")
        
        user.balance -= Config.TITLE_CHANGE_COST
        user.custom_title = new_title
        await session.commit()
        await message.answer(f"✅ Титул змінено на: <b>{new_title}</b>", parse_mode="HTML")

# ------------------------------------------
# ЗМІНА 3: Лотерея
# ------------------------------------------
@router.callback_query(F.data == "menu_lottery")
async def cb_lottery_menu(callback: types.CallbackQuery):
    async with async_session() as session:
        tickets_count = (await session.execute(select(func.count(LotteryTicket.id)))).scalar()
        pot = tickets_count * Config.LOTTERY_TICKET
        win_amount = pot * 0.8
        
        text = (
            f"🎰 <b>Щоденна Лотерея</b>\n\n"
            f"🎟 Квиток коштує: <b>${Config.LOTTERY_TICKET}</b>\n"
            f"💰 В банку зараз: <b>${pot:.2f}</b>\n"
            f"🏆 Переможець отримає: <b>${win_amount:.2f}</b>\n\n"
            f"Розіграш раз на добу!"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎟 Купити квиток", callback_data="buy_ticket")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="delete_msg")] # Повернення в services (треба буде хендлер зробити або просто ігнорувати start)
        ])
        # Виправлення: оновимо на повідомлення
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")

@router.callback_query(F.data == "buy_ticket")
async def cb_buy_ticket(callback: types.CallbackQuery):
    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        
        if user.balance < Config.LOTTERY_TICKET:
            return await callback.answer("❌ Немає грошей.", show_alert=True)
            
        # Перевіряємо чи вже купив (опціонально, дозволимо купувати багато)
        user.balance -= Config.LOTTERY_TICKET
        session.add(LotteryTicket(user_id=user.id))
        await session.commit()
        
        await callback.answer("✅ Квиток куплено! Удачі!", show_alert=True)

# ------------------------------------------
# ЗМІНА 4: Клани (Хедж-Фонди)
# ------------------------------------------
@router.callback_query(F.data == "menu_clans")
async def cb_clans_menu(callback: types.CallbackQuery):
    text = (
        "🏢 <b>Хедж-Фонди (Клани)</b>\n\n"
        "Створи свій фонд або приєднайся до існуючого!\n"
        f"Вартість реєстрації фонду: <b>${Config.CLAN_CREATION_COST:,.0f}</b>\n\n"
        "Команди:\n"
        "/createclan [НАЗВА] - Створити\n"
        "/joinclan [ID] - Приєднатися\n"
        "/clan - Інформація про твій фонд\n"
        "/topclans - Рейтинг фондів"
    )
    await callback.message.edit_text(text, parse_mode="HTML")

@router.message(Command("createclan"))
async def cmd_create_clan(message: types.Message):
    args = message.text.split(maxsplit=1)
    if len(args) != 2: return await message.answer("✍️ Введи назву. Приклад: `/createclan Wolves`", parse_mode="HTML")
    
    name = args[1]
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        
        if user.clan_id:
            return await message.answer("❌ Ти вже у клані.")
        if user.balance < Config.CLAN_CREATION_COST:
            return await message.answer(f"❌ Потрібно ${Config.CLAN_CREATION_COST:,.0f}")
            
        # Перевірка назви
        exists = (await session.execute(select(Clan).where(Clan.name == name))).scalar_one_or_none()
        if exists: return await message.answer("❌ Така назва зайнята.")
        
        user.balance -= Config.CLAN_CREATION_COST
        new_clan = Clan(name=name, owner_id=user.id)
        session.add(new_clan)
        await session.flush() # Щоб отримати ID
        
        user.clan_id = new_clan.id
        await session.commit()
        
        await message.answer(f"✅ Фонд <b>{name}</b> створено! ID: <code>{new_clan.id}</code>", parse_mode="HTML")

@router.message(Command("joinclan"))
async def cmd_join_clan(message: types.Message):
    args = message.text.split()
    if len(args) != 2: return await message.answer("✍️ Введи ID. Приклад: `/joinclan 1`", parse_mode="HTML")
    
    try:
        clan_id = int(args[1])
    except:
        return await message.answer("❌ ID має бути числом.")
        
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        clan = await session.get(Clan, clan_id)
        
        if not clan: return await message.answer("❌ Клан не знайдено.")
        if user.clan_id: return await message.answer("❌ Ти вже у клані. Вийди спочатку (поки не реалізовано, пиши адміну :))")
        
        user.clan_id = clan.id
        await session.commit()
        await message.answer(f"✅ Ти приєднався до <b>{clan.name}</b>!", parse_mode="HTML")

@router.message(Command("clan"))
async def cmd_my_clan(message: types.Message):
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user.clan_id: return await message.answer("⚠️ Ти не в клані.")
        
        clan = await session.get(Clan, user.clan_id)
        
        # Рахуємо учасників і капітал
        members = (await session.execute(select(User).where(User.clan_id == clan.id))).scalars().all()
        total_wealth = 0
        for m in members:
            # Тут треба використати get_net_worth, але він асинхронний і вимагає сесії.
            # Спростимо: рахуємо тільки баланс + (приблизно активи)
            # Або просто викличемо get_net_worth для кожного (може бути повільно, якщо багато людей)
            total_wealth += await get_net_worth(session, m)
            
        text = (
            f"🏢 <b>{clan.name}</b> (ID: {clan.id})\n"
            f"👥 Учасників: {len(members)}\n"
            f"💰 Загальний капітал: <b>${total_wealth:,.2f}</b>\n"
        )
        await message.answer(text, parse_mode="HTML")

# ------------------------------------------
# ЗМІНА 5: VIP Broadcast
# ------------------------------------------
@router.message(Command("vipbroadcast"), IsAdmin())
async def cmd_vip_broadcast(message: types.Message):
    content = message.text.replace("/vipbroadcast", "", 1).strip()
    if not content: return await message.answer("Введи текст.")
    
    async with async_session() as session:
        now = datetime.utcnow()
        # Шукаємо активних VIP
        query = select(User).where(User.vip_until > now)
        vips = (await session.execute(query)).scalars().all()
        
        count = 0
        for vip in vips:
            try:
                await message.bot.send_message(
                    vip.telegram_id,
                    f"🕵️ <b>ІНСАЙДЕРСЬКА ІНФА</b>\n\n{content}",
                    parse_mode="HTML"
                )
                count += 1
                await asyncio.sleep(0.05)
            except: pass
            
        await message.answer(f"✅ Відправлено {count} VIP-ам.")

# ------------------------------------------
# ЗМІНА 6: Оновлений Профіль (з Титулом)
# ------------------------------------------
# Заміни існуючий cmd_profile на цей:
@router.message(Command("profile"))
async def cmd_profile(message: types.Message):
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user: return await message.answer("⚠️ Натисни /start")

        net_worth = await get_net_worth(session, user)
        
        # Логіка титулу:
        if user.custom_title:
            rank = f"✨ {user.custom_title}"
        else:
            rank = calculate_rank(net_worth) # Імпортуй цю функцію або переконайся, що вона доступна

        clan_info = ""
        if user.clan_id:
            clan = await session.get(Clan, user.clan_id)
            if clan: clan_info = f"🏢 Фонд: {clan.name}\n"

        vip_status = ""
        if user.vip_until and user.vip_until > datetime.utcnow():
            vip_status = f"🕵️ VIP до {user.vip_until.strftime('%H:%M')}\n"
        
        license_status = "✅ Брокер" if user.has_license else "❌ Немає"

        text = (
            f"👤 <b>Твій Профіль</b>\n"
            f"────────────────\n"
            f"🏆 Ранг: <b>{rank}</b>\n"
            f"{clan_info}"
            f"{vip_status}"
            f"📜 Ліцензія: {license_status}\n"
            f"💵 Готівка: ${user.balance:.2f}\n"
            f"📈 Всього активів: <b>${net_worth:.2f}</b>\n"
            f"────────────────"
        )
        
        # ... (логіка відправки фото залишається) ...
        try:
            user_photos = await message.bot.get_user_profile_photos(message.from_user.id)
            if user_photos.total_count > 0:
                photo_id = user_photos.photos[0][-1].file_id
                await message.answer_photo(photo=photo_id, caption=text, parse_mode="HTML")
            else:
                await message.answer(text, parse_mode="HTML")
        except Exception:

            await message.answer(text, parse_mode="HTML")

@router.message(Command("addstock"), IsAdmin())
async def cmd_add_stock(message: types.Message):
    # Формат: /addstock TICKER PRICE VOLATILITY IMAGE_URL
    # Приклад: /addstock PEP 15.5 0.05 https://link.to/image.jpg
    
    try:
        args = message.text.split()
        ticker = args[1].upper()
        price = float(args[2])
        volatility = float(args[3])
        image_url = args[4] if len(args) > 4 else None
        
        async with async_session() as session:
            # Перевірка чи існує
            exists = await session.execute(select(Meme).where(Meme.ticker == ticker))
            if exists.scalar_one_or_none():
                return await message.answer("❌ Така акція вже є.")
            
            new_meme = Meme(
                ticker=ticker,
                current_price=price,
                volatility=volatility,
                image_url=image_url
            )
            session.add(new_meme)
            await session.commit()
            
        await message.answer(f"✅ Акцію **{ticker}** додано в гру!", parse_mode="Markdown")
        
    except Exception as e:
        await message.answer(f"❌ Помилка. Приклад:\n`/addstock PEP 15.5 0.05 https://url...`\nДеталі: {e}")





