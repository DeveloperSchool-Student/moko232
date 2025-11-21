import random
import asyncio
import io
import pandas as pd
import mplfinance as mpf
import matplotlib
from datetime import datetime

from sqlalchemy import select, delete, func
from aiogram import Bot

from database import async_session
from config import Config
from models import User, Meme, PriceHistory, News, Bet, LotteryTicket

matplotlib.use('Agg')

# --- ШАБЛОНИ НОВИН ---
NEWS_UP = [
    "🚀 {ticker} летить на Місяць! Інвестори в шоці!",
    "📈 Кити закуповують {ticker}. Ціна стрімко росте!",
    "🤑 Ходять чутки, що Ілон Маск купив {ticker}...",
    "🔥 {ticker} пробиває стелю! Тримайте свої капелюхи!",
    "🐂 Бичачий тренд по {ticker}. Всі купують!"
]

NEWS_DOWN = [
    "📉 {ticker} стрімко падає! Паніка на біржі!",
    "😱 Хтось злив величезну кількість {ticker}...",
    "🔻 Бульбашка {ticker} луснула? Інвестори плачуть.",
    "🐻 Ведмеді атакують {ticker}. Рятуйся хто може!",
    "🩸 Кровава лазня по {ticker}. Ціна летить у прірву."
]

async def update_prices():
    """Ця функція автоматично змінює ціни, враховуючи маніпуляції ТА дії гравців"""
    async with async_session() as session:
        result = await session.execute(select(Meme))
        memes = result.scalars().all()

        for meme in memes:
            # 1. ВПЛИВ ГРАВЦІВ
            player_impact = meme.trade_volume * Config.MARKET_IMPACT_FACTOR
            meme.trade_volume = 0 # Скидаємо об'єм
            
            # 2. АДМІНСЬКА МАНІПУЛЯЦІЯ
            change_percent = 0.0
            if meme.manipulation_remaining > 0:
                manipulation_effect = meme.volatility / 2 
                if meme.manipulation_mode == 'UP':
                    change_percent = random.uniform(manipulation_effect * 0.5, manipulation_effect)
                elif meme.manipulation_mode == 'DOWN':
                    change_percent = random.uniform(-manipulation_effect, -manipulation_effect * 0.5)
                meme.manipulation_remaining -= 1
                if meme.manipulation_remaining == 0:
                    meme.manipulation_mode = "NONE"
            else:
                # 3. ПРИРОДНІ КОЛИВАННЯ
                change_percent = random.uniform(-meme.volatility, meme.volatility)
            
            # --- ВИПРАВЛЕННЯ ТУТ ---
            # 4. ПІДСУМКОВИЙ РОЗРАХУНОК
            total_change = change_percent + player_impact
            
            # Жорстке обмеження: ціна не може змінитися більше ніж на 30% (0.3) за хвилину
            # Це рятує від краху до нуля
            total_change = max(-0.3, min(0.3, total_change))
            
            new_price = meme.current_price * (1 + total_change)
            
            # Захист від занадто низької ціни (мінімум 1 цент або 0.01)
            if new_price < 0.01: new_price = 0.01
            
            meme.current_price = new_price
            
            # Запис історії цін
            history = PriceHistory(meme_id=meme.id, price=new_price)
            session.add(history)
            
            # ... (далі код новин залишається без змін) ...

            # --- 5. ГЕНЕРАЦІЯ НОВИН ---
            # Генеруємо новину, якщо ціна змінилась більше ніж на поріг
            if abs(total_change) >= Config.NEWS_THRESHOLD:
                
                if total_change > 0:
                    template = random.choice(NEWS_UP)
                    emoji = "🟢"
                else:
                    template = random.choice(NEWS_DOWN)
                    emoji = "🔴"
                
                news_text = template.format(ticker=meme.ticker)
                full_text = f"{emoji} {news_text} ({total_change*100:+.1f}%)"
                
                news_item = News(
                    meme_id=meme.id,
                    ticker=meme.ticker,
                    content=full_text,
                    change_percent=total_change
                )
                session.add(news_item)

        # --- ОЧИЩЕННЯ СТАРИХ НОВИН ---
        # Виконуємо це поза циклом, щоб не робити зайвих запитів
        try:
            # Отримуємо ID всіх новин, відсортованих від нових до старих
            all_news_result = await session.execute(select(News.id).order_by(News.timestamp.desc()))
            all_news_ids = all_news_result.scalars().all()
            
            # Якщо новин більше 20, видаляємо зайві
            if len(all_news_ids) > 20:
                ids_to_delete = all_news_ids[20:]
                await session.execute(delete(News).where(News.id.in_(ids_to_delete)))
        except Exception as e:
            print(f"Помилка при очищенні новин: {e}")

        await session.commit()

def _generate_chart_sync(data, ticker):
    if not data: return None
    df = pd.DataFrame(data, columns=['Date', 'Price'])
    df['Date'] = pd.to_datetime(df['Date'])
    df.set_index('Date', inplace=True)
    
    # Fake OHLC (для лінійного графіку mpf це підходить)
    df['Open'] = df['Price']
    df['High'] = df['Price']
    df['Low'] = df['Price']
    df['Close'] = df['Price']
    
    buf = io.BytesIO()
    # style='yahoo' або 'binance' виглядають непогано
    mpf.plot(df, type='line', style='yahoo', title=f'{ticker}', savefig=dict(fname=buf, format='png'))
    buf.seek(0)
    return buf

async def get_meme_chart(meme_id: int, ticker: str):
    async with async_session() as session:
        query = select(PriceHistory).where(PriceHistory.meme_id == meme_id).order_by(PriceHistory.timestamp.desc()).limit(50)
        result = await session.execute(query)
        history = result.scalars().all()
        # Реверсуємо, щоб графік йшов зліва направо (від старого до нового)
        data = [{"Date": h.timestamp, "Price": h.price} for h in reversed(history)]
        if not data: return None
        
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _generate_chart_sync, data, ticker)
    
# mechanics.py

async def check_bets(bot: Bot):
    """Перевіряє ставки, час яких вийшов"""
    async with async_session() as session:
        now = datetime.utcnow()
        
        # Шукаємо необроблені ставки, час яких вже настав
        query = select(Bet).where(Bet.processed == False, Bet.end_time <= now)
        result = await session.execute(query)
        bets = result.scalars().all()
        
        for bet in bets:
            user = await session.get(User, bet.user_id)
            meme = await session.get(Meme, bet.meme_id)
            
            if not user or not meme:
                bet.processed = True
                continue

            # ЛОГІКА ПЕРЕМОГИ
            won = False
            if bet.direction == "UP" and meme.current_price > bet.start_price:
                won = True
            elif bet.direction == "DOWN" and meme.current_price < bet.start_price:
                won = True
            
            # Формування тексту
            text = ""
            if won:
                payout = bet.amount * Config.BET_PROFIT_FACTOR
                user.balance += payout
                text = (
                    f"✅ <b>ПЕРЕМОГА!</b>\n"
                    f"Ставка на {meme.ticker} ({bet.direction}) зіграла!\n"
                    f"Початкова ціна: ${bet.start_price:.4f}\n"
                    f"Поточна ціна: ${meme.current_price:.4f}\n"
                    f"💰 Виграш: <b>+${payout:.2f}</b>"
                )
            else:
                text = (
                    f"❌ <b>ПРОГРАШ...</b>\n"
                    f"Ставка на {meme.ticker} ({bet.direction}) не зайшла.\n"
                    f"Початкова ціна: ${bet.start_price:.4f}\n"
                    f"Поточна ціна: ${meme.current_price:.4f}\n"
                    f"💸 Втрачено: ${bet.amount:.2f}"
                )
            
            bet.processed = True
            
            # Відправляємо повідомлення гравцю
            try:
                await bot.send_message(chat_id=user.telegram_id, text=text, parse_mode="HTML")
            except Exception:
                pass # Якщо бот заблокований
        
        await session.commit()
        
async def run_lottery(bot: Bot):
    """Запускається раз на добу: обирає переможця і видаляє квитки"""
    async with async_session() as session:
        # Рахуємо квитки
        tickets_result = await session.execute(select(LotteryTicket))
        tickets = tickets_result.scalars().all()
        
        if not tickets:
            return # Ніхто не купив квитки
        
        # Розрахунок банку
        total_pot = len(tickets) * Config.LOTTERY_TICKET
        prize = total_pot * 0.8 # 80% переможцю
        
        # Обираємо переможця випадково
        winner_ticket = random.choice(tickets)
        winner_user = await session.get(User, winner_ticket.user_id)
        
        if winner_user:
            winner_user.balance += prize
            
            # Сповіщення переможця
            try:
                await bot.send_message(
                    winner_user.telegram_id,
                    f"🎉 <b>ДЖЕКПОТ!</b>\n\n"
                    f"Ти виграв у лотерею!\n"
                    f"Всього учасників: {len(tickets)}\n"
                    f"Твій виграш: <b>${prize:.2f}</b>"
                , parse_mode="HTML")
            except:
                pass
        
        # Очищаємо таблицю квитків
        await session.execute(delete(LotteryTicket))
        await session.commit()

