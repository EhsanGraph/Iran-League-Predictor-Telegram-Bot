import logging
from typing import Optional, Tuple, Dict, Any, List
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes,
    CallbackQueryHandler, ConversationHandler, MessageHandler, filters, CallbackContext
)
from config import BOT_TOKEN, ADMIN_IDS, DEFAULT_SCORES, MAX_SCORE_LENGTH
from config import POINTS_FOR_EXACT_SCORE, POINTS_FOR_CORRECT_WINNER, POINTS_FOR_PARTIAL_SCORE
from database import DatabaseManager
import sqlite3
import time
from datetime import datetime

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

SELECT_SCORE, SELECT_WINNER = range(2)
current_week_cache = {"value": None, "timestamp": 0}
SET_RESULT_MATCH, SET_RESULT_SCORE, SET_RESULT_WINNER, SET_RESULT_CONFIRM = range(3, 7)

class BotHandlers:
    @staticmethod
    def validate_score(score: str) -> bool:
        try:
            if not isinstance(score, str) or len(score) > MAX_SCORE_LENGTH:
                return False
            
            if "-" not in score:
                return False
            
            home, away = score.split("-")
            if not home.strip().isdigit() or not away.strip().isdigit():
                return False
                
            home_int, away_int = int(home), int(away)
            if home_int < 0 or away_int < 0:
                return False
                
            if home_int > 20 or away_int > 20:
                return False
                
            return True
        except Exception:
            return False

    @staticmethod
    def get_cached_current_week(ttl_seconds: int = 300) -> int:
        now = time.time()
        if current_week_cache["value"] is not None and now - current_week_cache["timestamp"] < ttl_seconds:
            return current_week_cache["value"]
        
        current_week = DatabaseManager.get_current_week()
        current_week_cache["value"] = current_week
        current_week_cache["timestamp"] = now
        return current_week

    @staticmethod
    def register_user(user) -> bool:
        try:
            DatabaseManager.execute_write(
                """
                INSERT OR IGNORE INTO users 
                (user_id, full_name, username, language_code)
                VALUES (?, ?, ?, ?)
                """,
                (user.id, user.full_name, user.username, user.language_code)
            )
            return True
        except Exception as e:
            logger.error(f"خطا در ثبت کاربر: {e}")
            return False

    @staticmethod
    def get_next_match(user_id: int, week: int) -> Optional[Tuple]:
        try:
            result = DatabaseManager.execute_query(
                """
                SELECT m.id, m.week, m.home_team, m.away_team 
                FROM matches m
                WHERE m.week = ?
                AND m.id NOT IN (
                    SELECT match_id FROM predictions WHERE user_id=?
                )
                ORDER BY m.id LIMIT 1
                """,
                (week, user_id),
                fetch_one=True
            )
            return tuple(result) if result else None
        except Exception as e:
            logger.error(f"خطا در دریافت بازی بعدی: {e}")
            return None
        
    @staticmethod
    async def current_week(update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            current = BotHandlers.get_cached_current_week()
            await update.message.reply_text(f"📅 هفته فعلی لیگ: {current}")
        except Exception as e:
            logger.error(f"خطا در دریافت هفته جاری: {e}")
            await update.message.reply_text("⚠️ خطا در دریافت هفته فعلی.")

    @staticmethod
    async def _send_match_prediction_request(message_obj, week: int, home: str, away: str):
        keyboard = []
        row = []
        for i, score in enumerate(DEFAULT_SCORES, 1):
            row.append(InlineKeyboardButton(text=score, callback_data=f"score|{score}"))
            if i % 3 == 0 or i == len(DEFAULT_SCORES):
                keyboard.append(row)
                row = []
        
        keyboard.append([InlineKeyboardButton(text="⚙️ دستی", callback_data="score|manual")])

        await message_obj.reply_text(
            f"📅 هفته {week}\n🟢 {home} 🆚 {away}\n\nتعداد گل‌های پیش‌بینی‌شده را انتخاب کنید:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    @staticmethod
    async def _handle_no_matches(update: Update, current_week: int, user_id: int):
        try:
            remaining = DatabaseManager.execute_query(
                """
                SELECT COUNT(*) FROM matches 
                WHERE week = ? 
                AND id NOT IN (
                    SELECT match_id FROM predictions WHERE user_id=?
                )
                """,
                (current_week, user_id),
                fetch_one=True
            )[0]
            
            message = update.message or update.callback_query.message
            
            if remaining == 0:
                await message.reply_text(
                    f"🎉 شما تمام بازی‌های هفته {current_week} را پیش‌بینی کرده‌اید!\n\n"
                    "برای مشاهده پیش‌بینی‌هایتان /mybets را وارد کنید."
                )
            else:
                await message.reply_text(
                    f"⚠️ خطا در یافتن بازی‌های هفته {current_week}. لطفاً با پشتیبانی تماس بگیرید."
                )
        except Exception as e:
            logger.error(f"خطا در _handle_no_matches: {e}")
            if update.callback_query:
                await update.callback_query.answer("⚠️ خطایی رخ داده است", show_alert=True)

    @staticmethod
    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            user = update.effective_user
            if not user:
                raise ValueError("کاربر یافت نشد")
                
            logger.info(f"دستور شروع از کاربر {user.id}")
            
            if not BotHandlers.register_user(user):
                msg = update.message or update.callback_query.message
                await msg.reply_text("⚠️ خطا در ثبت کاربر. لطفاً دوباره امتحان کنید.")
                return ConversationHandler.END

            current_week = BotHandlers.get_cached_current_week()
            if current_week is None:
                logger.error("خطا در دریافت هفته جاری")
                msg = update.message or update.callback_query.message
                await msg.reply_text("⚠️ خطا در دریافت هفته جاری. لطفاً با پشتیبانی تماس بگیرید.")
                return ConversationHandler.END

            match = BotHandlers.get_next_match(user.id, current_week)
            if not match:
                await BotHandlers._handle_no_matches(update, current_week, user.id)
                return ConversationHandler.END

            match_id, week, home, away = match
            context.user_data.clear()
            context.user_data.update({
                "match_id": match_id,
                "home": home,
                "away": away,
                "week": week
            })

            msg = update.message or update.callback_query.message
            await BotHandlers._send_match_prediction_request(msg, week, home, away)
            return SELECT_SCORE
            
        except Exception as e:
            logger.error(f"خطا در هندلر شروع: {e}", exc_info=True)
            if update.callback_query:
                await update.callback_query.answer("⚠️ خطایی رخ داده است", show_alert=True)
            else:
                await update.message.reply_text("⚠️ خطایی رخ داده است. لطفاً دوباره امتحان کنید.")
            return ConversationHandler.END

    @staticmethod
    async def handle_score(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        try:
            action, value = query.data.split("|")
            if value == "manual":
                await query.edit_message_text(
                    "✍️ لطفاً نتیجه را به صورت عدد وارد کنید.\nمثال: 2-1\n"
                    f"حداکثر طول مجاز: {MAX_SCORE_LENGTH} کاراکتر"
                )
                return SELECT_SCORE

            if not BotHandlers.validate_score(value):
                await query.edit_message_text("❌ نتیجه نامعتبر است. لطفاً دوباره انتخاب کنید.")
                return SELECT_SCORE

            context.user_data["score"] = value
            return await BotHandlers.prompt_for_winner(query, context)
        except Exception as e:
            logger.error(f"خطا در handle_score: {e}")
            await query.edit_message_text("⚠️ خطایی رخ داده است. لطفاً دوباره امتحان کنید.")
            return ConversationHandler.END

    @staticmethod
    async def handle_manual_score(update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = update.message.text.strip()
        
        try:
            if len(text) > MAX_SCORE_LENGTH:
                await update.message.reply_text(f"❌ نتیجه بسیار طولانی است. حداکثر {MAX_SCORE_LENGTH} کاراکتر مجاز است.")
                return SELECT_SCORE

            if not BotHandlers.validate_score(text):
                await update.message.reply_text("❌ فرمت اشتباه است. لطفاً به صورت x-y بنویسید (مثال: 2-1).")
                return SELECT_SCORE

            context.user_data["score"] = text
            return await BotHandlers.prompt_for_winner(update.message, context)
        except Exception as e:
            logger.error(f"خطا در handle_manual_score: {e}")
            await update.message.reply_text("⚠️ خطایی رخ داده است. لطفاً دوباره امتحان کنید.")
            return ConversationHandler.END
        
    @staticmethod
    async def matches_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            week = BotHandlers.get_cached_current_week()
            matches = DatabaseManager.execute_query(
                """
                SELECT id, home_team, away_team, result 
                FROM matches 
                WHERE week = ? 
                ORDER BY id
                """,
                (week,)
            )

            if not matches:
                await update.message.reply_text(f"⚠️ هیچ بازی‌ای برای هفته {week} ثبت نشده.")
                return

            response = [f"📅 بازی‌های هفته {week}:"]
            for match in matches:
                status = f" (نتیجه: {match['result']})" if match['result'] else " (در انتظار)"
                response.append(f"#{match['id']}: {match['home_team']} 🆚 {match['away_team']}{status}")

            await update.message.reply_text("\n".join(response))
        except Exception as e:
            logger.error(f"خطا در matches_handler: {e}")
            await update.message.reply_text("⚠️ خطا در دریافت لیست بازی‌ها.")

    @staticmethod
    async def start_week_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            if update.effective_user.id not in ADMIN_IDS:
                await update.message.reply_text("⛔ فقط برای مدیران")
                return

            week = BotHandlers.get_cached_current_week()
            matches = DatabaseManager.execute_query(
                """
                SELECT home_team, away_team FROM matches
                WHERE week = ? ORDER BY id
                """,
                (week,)
            )

            if not matches:
                await update.message.reply_text(f"❌ هیچ بازی‌ای برای هفته {week} تعریف نشده.")
                return

            lines = [f"📢 شروع هفته {week}!\n📅 بازی‌های این هفته:"]
            for i, match in enumerate(matches, 1):
                lines.append(f"{i}. {match['home_team']} 🆚 {match['away_team']}")

            await update.message.reply_text("\n".join(lines))
        except Exception as e:
            logger.error(f"خطا در start_week_command: {e}")
            await update.message.reply_text("⚠️ خطا در ارسال برنامه هفته.")

    @staticmethod
    async def prompt_for_winner(message_obj, context: ContextTypes.DEFAULT_TYPE):
        try:
            score = context.user_data["score"]
            home = context.user_data["home"]
            away = context.user_data["away"]
            
            home_goals, away_goals = map(int, score.split('-'))
            is_draw_prediction = (home_goals == away_goals)
            
            keyboard = [[
                InlineKeyboardButton(home, callback_data="winner|" + home),
                InlineKeyboardButton(away, callback_data="winner|" + away)
            ]]
            
            if is_draw_prediction:
                keyboard[0].insert(1, InlineKeyboardButton("مساوی", callback_data="winner|مساوی"))
            
            text = f"🔢 نتیجه انتخابی: {score}\nچه تیمی را برنده می‌دانید؟"
            
            if hasattr(message_obj, 'edit_message_text'):
                await message_obj.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
            else:
                await message_obj.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
                
            return SELECT_WINNER
        except Exception as e:
            logger.error(f"خطا در prompt_for_winner: {e}")
            await message_obj.reply_text("⚠️ خطایی رخ داده است. لطفاً دوباره امتحان کنید.")
            return ConversationHandler.END
        
    @staticmethod
    async def next_week(update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            if update.effective_user.id not in ADMIN_IDS:
                await update.message.reply_text("⛔ فقط برای مدیران")
                return

            current = BotHandlers.get_cached_current_week()
            new_week = current + 1

            DatabaseManager.set_current_week(new_week)
            
            current_week_cache["value"] = None

            await update.message.reply_text(f"📆 هفته جاری به {new_week} تغییر یافت.")
        except Exception as e:
            logger.error(f"خطا در next_week: {e}")
            await update.message.reply_text("⚠️ خطا در بروزرسانی هفته.")

    @staticmethod
    async def _send_prediction_success(query, week: int, score: str, winner: str):
        """ارسال پیام موفقیت ثبت پیش‌بینی"""
        await query.edit_message_text(
            f"✅ پیش‌بینی ذخیره شد:\n"
            f"📅 هفته {week}\n"
            f"🔢 نتیجه: {score}\n"
            f"🏆 برنده: {winner}\n\n"
            "برای پیش‌بینی بازی بعدی /start را وارد کنید."
        )

    @staticmethod
    async def handle_winner(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        try:
            _, winner = query.data.split("|")
            user = update.effective_user
            match_data = context.user_data
            
            success = DatabaseManager.execute_write(
                """
                INSERT OR REPLACE INTO predictions 
                (user_id, match_id, week, home_team, away_team, score, winner) 
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (user.id, match_data['match_id'], match_data['week'], 
                match_data['home'], match_data['away'], 
                match_data['score'], winner)
            )
            
            if not success:
                raise ValueError("Failed to save prediction")

            await BotHandlers._send_prediction_success(query, match_data['week'], match_data['score'], winner)
            return ConversationHandler.END
            
        except Exception as e:
            logger.error(f"Error in handle_winner: {e}")
            await query.edit_message_text(
                "⚠️ خطایی در ذخیره پیش‌بینی رخ داده است.\n"
                "لطفاً دوباره امتحان کنید یا با پشتیبانی تماس بگیرید."
            )
            return ConversationHandler.END

    @staticmethod
    async def my_predictions(update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            user_id = update.effective_user.id
            args = context.args
            
            week_filter = int(args[0]) if args and args[0].isdigit() else None
            
            predictions = DatabaseManager.get_user_predictions(user_id, week_filter)
            
            if not predictions:
                msg = "هنوز هیچ پیش‌بینی ثبت نکرده‌اید."
                if week_filter:
                    msg = f"پیش‌بینی‌ای برای هفته {week_filter} ثبت نکرده‌اید."
                await update.message.reply_text(msg)
                return
                
            response = ["📊 پیش‌بینی‌های شما:"]
            for pred in predictions:
                status = ""
                if pred['result']:
                    if pred['points'] is not None:
                        status = f" ✅ ({pred['points']} امتیاز)"
                    else:
                        status = " ⏳ (در انتظار امتیازدهی)"
                
                response.append(
                    f"\n📅 هفته {pred['week']}: "
                    f"{pred['home_team']} {pred['score']} {pred['away_team']}\n"
                    f"🏆 برنده: {pred['winner']}{status}"
                )
                
            await update.message.reply_text("\n".join(response))
            
        except Exception as e:
            logger.error(f"خطا در my_predictions: {e}")
            await update.message.reply_text(
                "⚠️ خطایی در دریافت پیش‌بینی‌ها رخ داده است.\n"
                "فرمت صحیح: /mybets [شماره_هفته]"
            )
            

    @staticmethod
    async def set_result_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id not in ADMIN_IDS:
            await update.message.reply_text("⛔ فقط برای مدیران")
            return ConversationHandler.END
        
        current_week = BotHandlers.get_cached_current_week()
        matches = DatabaseManager.execute_query(
            """
            SELECT id, home_team, away_team 
            FROM matches 
            WHERE week = ? AND result IS NULL
            ORDER BY id
            """,
            (current_week,)
        )
        
        if not matches:
            await update.message.reply_text("✅ همه بازی‌های این هفته نتیجه دارند!")
            return ConversationHandler.END
        
        keyboard = []
        for match in matches:
            keyboard.append([
                InlineKeyboardButton(
                    f"{match['home_team']} 🆚 {match['away_team']}",
                    callback_data=f"setresult_match|{match['id']}"
                )
            ])
        
        await update.message.reply_text(
            "⚽ بازی مورد نظر برای ثبت نتیجه را انتخاب کنید:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return SET_RESULT_MATCH
    
    @staticmethod
    async def set_result_select_match(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        _, match_id = query.data.split("|")
        match = DatabaseManager.execute_query(
            "SELECT id, week, home_team, away_team FROM matches WHERE id = ?",
            (match_id,), fetch_one=True
        )
        
        context.user_data["setresult"] = {
            "match_id": match["id"],
            "week": match["week"],
            "home": match["home_team"],
            "away": match["away_team"]
        }
        
        keyboard = []
        row = []
        for i, score in enumerate(DEFAULT_SCORES, 1):
            row.append(InlineKeyboardButton(score, callback_data=f"setresult_score|{score}"))
            if i % 3 == 0:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        keyboard.append([InlineKeyboardButton("✍️ وارد کردن دستی", callback_data="setresult_score|manual")])
        
        await query.edit_message_text(
            f"📌 بازی انتخاب شده:\n{match['home_team']} 🆚 {match['away_team']}\n\n"
            "لطفاً نتیجه نهایی را انتخاب کنید:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return SET_RESULT_SCORE

    @staticmethod
    async def set_result_select_score(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        _, score = query.data.split("|")
        match_data = context.user_data["setresult"]
        
        if score == "manual":
            await query.edit_message_text(
                "✍️ لطفاً نتیجه را به صورت عدد وارد کنید (مثال: 2-1):"
            )
            return SET_RESULT_SCORE
        
        if not BotHandlers.validate_score(score):
            await query.edit_message_text("❌ نتیجه نامعتبر! لطفاً دوباره انتخاب کنید.")
            return SET_RESULT_SCORE
        
        match_data["score"] = score
        context.user_data["setresult"] = match_data
        
        return await BotHandlers.set_result_prompt_winner(query, context)
    
    @staticmethod
    async def set_result_prompt_winner(message_obj, context: ContextTypes.DEFAULT_TYPE):
        try:
            match_data = context.user_data["setresult"]
            score = match_data["score"]
            home = match_data["home"]
            away = match_data["away"]
            
            home_goals, away_goals = map(int, score.split('-'))
            is_draw = (home_goals == away_goals)
            
            keyboard = [[
                InlineKeyboardButton(home, callback_data="setresult_winner|" + home),
                InlineKeyboardButton(away, callback_data="setresult_winner|" + away)
            ]]
            
            if is_draw:
                keyboard[0].insert(1, InlineKeyboardButton("مساوی", callback_data="setresult_winner|مساوی"))
            
            text = f"🔢 نتیجه انتخابی: {score}\nتیم برنده را انتخاب کنید:"
            
            if hasattr(message_obj, 'edit_message_text'):
                await message_obj.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
            else:
                await message_obj.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
                
            return SET_RESULT_WINNER
        except Exception as e:
            logger.error(f"خطا در set_result_prompt_winner: {e}")
            await message_obj.reply_text("⚠️ خطایی رخ داده است. لطفاً دوباره امتحان کنید.")
            return ConversationHandler.END
        
    @staticmethod
    async def set_result_select_winner(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        _, winner = query.data.split("|")
        match_data = context.user_data["setresult"]
        match_data["winner"] = winner
        
        keyboard = [
            [InlineKeyboardButton("✅ تأیید و ثبت نتیجه", callback_data="setresult_confirm|1")],
            [InlineKeyboardButton("❌ انصراف", callback_data="setresult_confirm|0")]
        ]
        
        await query.edit_message_text(
            f"🔍 تأیید نهایی:\n\n"
            f"📅 هفته {match_data['week']}\n"
            f"🏠 {match_data['home']} 🆚 {match_data['away']} 🏡\n"
            f"🔢 نتیجه: {match_data['score']}\n"
            f"🏆 برنده: {winner}\n\n"
            "آیا از ثبت این نتیجه اطمینان دارید؟",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return SET_RESULT_CONFIRM

    @staticmethod
    async def set_result_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        _, confirm = query.data.split("|")
        if confirm == "0":
            await query.edit_message_text("❌ ثبت نتیجه لغو شد.")
            return ConversationHandler.END
        
        match_data = context.user_data["setresult"]
        
        try:
            DatabaseManager.execute_write(
                """UPDATE matches 
                SET result = ?, winner = ?, updated_at = CURRENT_TIMESTAMP 
                WHERE id = ?""",
                (match_data["score"], match_data["winner"], match_data["match_id"])
            )
            
            updated_count = 0
            predictions = DatabaseManager.execute_query(
                """SELECT p.id, p.score, p.winner 
                FROM predictions p 
                WHERE p.match_id = ?""",
                (match_data["match_id"],)
            )
            
            home_score, away_score = map(int, match_data["score"].split('-'))
            
            for pred in predictions:
                points = PredictionSystem.calculate_points(
                    pred["score"], pred["winner"],
                    match_data["score"], match_data["home"], match_data["away"]
                )
                
                DatabaseManager.execute_write(
                    """UPDATE predictions 
                    SET points = ?, updated_at = CURRENT_TIMESTAMP 
                    WHERE id = ?""",
                    (points, pred["id"])
                )
                updated_count += 1

            await query.edit_message_text(
                f"✅ نتیجه با موفقیت ثبت شد!\n\n"
                f"📊 {updated_count} پیش‌بینی امتیازدهی شد\n\n"
                f"برای مشاهده جدول امتیازات: /champion"
            )
        except Exception as e:
            logger.error(f"خطا در ثبت نتیجه: {e}")
            await query.edit_message_text(
                f"⚠️ خطایی در ثبت نتیجه رخ داد:\n{str(e)}\n"
                "لطفاً دوباره امتحان کنید."
            )
        
        return ConversationHandler.END
    

    
    @staticmethod
    async def set_result_manual_score(update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = update.message.text.strip()
        match_data = context.user_data["setresult"]
        
        if not BotHandlers.validate_score(text):
            await update.message.reply_text("❌ فرمت نتیجه اشتباه است! لطفاً به صورت x-y وارد کنید (مثال: 2-1)")
            return SET_RESULT_SCORE
        
        match_data["score"] = text
        context.user_data["setresult"] = match_data
        
        return await BotHandlers.set_result_prompt_winner(update.message, context)
    


    @staticmethod
    async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
        help_text = [
            "📚 *راهنمای خفن ربات پیش‌بینی فوتبال* 📚",
            "",
            "",
            "🔹 *دستورات عمومی:*",
            "",
            "🔸 /start - شروع پیش‌بینی بازی‌های این هفته (بزن بریم!)",
            "🔸 /mybets - ببین این دفعه چه کردی ، هنوز شانسی هست؟",
            "🔸 /matches - لیست بازی‌های این هفته رو ببین و نظر بده",
            "🔸 /week - شماره هفته فعلی رو نشونت میده (چندمین هفته ایم؟)",
            "🔸 /champion - جدول قهرمان‌ها! خوبان عالم ؟ 😎",
            "🔸 /helpme - همین راهنمای جذاب رو دوباره نشون بده",
            "",
            "🔹 *دستورات مدیریتی (فقط مخصوص ادمین‌های قدر قدرت):*",
            "",
            "🔸 /setresult - وارد کردن نتیجه واقعی بازی‌ها (تعیین سرنوشت!)",
            "🔸 /nextweek - بزن بریم هفته بعد! ⏩",
            "🔸 /startweek - اعلام رسمی شروع هفته به همه بچه‌ها 📢",
            "",
            "📝 *چجوری بازی کنیم؟*",
            "",
            "1️⃣ دستور /start رو بزن",
            "2️⃣ نتایج رو انتخاب یا دستی وارد کن",
            "3️⃣ تیم برنده یا مساوی رو مشخص کن",
            "4️⃣ ادمین نتایج واقعی رو وارد می‌کنه",
            "5️⃣ ربات خودش برات امتیاز حساب می‌کنه و می‌ری بالا! 🚀",
            "",
            "⚽ *سیستم امتیازدهی (خیلی مهمه):*",
            "",
            "🏅 نتیجه دقیق: *5 امتیاز* (مثل جادوگر فوتبال!)",
            "🥈 فقط برنده رو درست گفتی؟ *3 امتیاز* هم غنیمته!",
            "🥉 یه عدد رو درست زدی؟ *1 امتیاز* هم نوش جونت!",
            "",
            "🏆 *لیگ برتر فوتبال ایران*",
            "🤖 نسخه ربات: 1.0.1 – بیا قهرمان شو!"
        ]

        
        keyboard = [
            [
                InlineKeyboardButton("پیش‌بینی‌های من 📊", callback_data="my_predictions"),
                InlineKeyboardButton("جدول امتیازات 🏆", callback_data="leaderboard")
            ],
            [InlineKeyboardButton("بازی‌های هفته 📅", callback_data="current_matches")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "\n".join(help_text),
            parse_mode="Markdown",
            reply_markup=reply_markup,
            disable_web_page_preview=True
        )

    @staticmethod
    async def handle_quick_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        new_update = Update(update.update_id, message=query.message)
        await BotHandlers.start(new_update, context)

    @staticmethod
    async def handle_my_predictions(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        new_update = Update(update.update_id, message=query.message)
        await BotHandlers.my_predictions(new_update, context)

    @staticmethod
    async def handle_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        new_update = Update(update.update_id, message=query.message)
        await BotHandlers.leaderboard(new_update, context)

    @staticmethod
    async def handle_current_matches(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        new_update = Update(update.update_id, message=query.message)
        await BotHandlers.matches_handler(new_update, context)

    @staticmethod
    async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            args = context.args
            week = int(args[0]) if args else None
            
            if week:
                results = DatabaseManager.execute_query(
                    """
                    SELECT u.full_name, SUM(p.points) as total_points
                    FROM predictions p
                    JOIN users u ON p.user_id = u.user_id
                    WHERE p.week = ? AND p.points IS NOT NULL
                    GROUP BY p.user_id
                    ORDER BY total_points DESC
                    LIMIT 10
                    """,
                    (week,)
                )
                title = f"🏆 جدول رده‌بندی هفته {week}"
            else:
                results = DatabaseManager.execute_query(
                    """
                    SELECT u.full_name, SUM(p.points) as total_points
                    FROM predictions p
                    JOIN users u ON p.user_id = u.user_id
                    WHERE p.points IS NOT NULL
                    GROUP BY p.user_id
                    ORDER BY total_points DESC
                    LIMIT 10
                    """)
                title = "🏆 جدول رده‌بندی کلی"
            
            if not results:
                await update.message.reply_text("هنوز امتیازی ثبت نشده است.")
                return
                
            response = [title]
            for i, row in enumerate(results, 1):
                response.append(f"{i}. {row['full_name']} ({row['total_points']} امتیاز)")
                
            await update.message.reply_text("\n".join(response))
            
        except Exception as e:
            logger.error(f"خطا در leaderboard: {e}")
            await update.message.reply_text("⚠️ خطایی در نمایش جدول رده‌بندی رخ داده است.")

    @staticmethod
    async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        logger.error(f"آپدیت {update} باعث خطا شد: {context.error}")
        if update.effective_message:
            await update.effective_message.reply_text("⚠️ متأسفانه خطایی رخ داده است. لطفاً دوباره امتحان کنید.")
    
    @staticmethod
    def cancel(update: Update, context: CallbackContext) -> int:
        update.message.reply_text("⛔️ عملیات لغو شد.")
        return ConversationHandler.END
    

class PredictionSystem:
    @staticmethod
    def calculate_points(
        predicted_score: str,
        predicted_winner: str,
        actual_score: str,
        home_team: str,
        away_team: str
    ) -> int:
        if not all([predicted_score, predicted_winner, actual_score, home_team, away_team]):
            return 0
            
        if predicted_score == actual_score:
            return POINTS_FOR_EXACT_SCORE
        
        try:
            pred_home, pred_away = map(int, predicted_score.split('-'))
            actual_home, actual_away = map(int, actual_score.split('-'))
            
            if actual_home == actual_away:
                actual_winner = "مساوی"
            else:
                actual_winner = home_team if actual_home > actual_away else away_team
            
            if predicted_winner == actual_winner:
                return POINTS_FOR_CORRECT_WINNER
                
            if (pred_home == actual_home) or (pred_away == actual_away):
                return POINTS_FOR_PARTIAL_SCORE
                
        except (ValueError, AttributeError) as e:
            logger.error(f"خطا در تجزیه امتیاز: {e}")
        
        return 0

def setup_bot():
    try:
        DatabaseManager.initialize_database()
        
        app = ApplicationBuilder() \
            .token(BOT_TOKEN) \
            .read_timeout(30) \
            .write_timeout(30) \
            .build()

        conv_handler = ConversationHandler(
            entry_points=[CommandHandler("start", BotHandlers.start)],
            states={
                SELECT_SCORE: [
                    CallbackQueryHandler(BotHandlers.handle_score, pattern=r"^score\|"),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, BotHandlers.handle_manual_score)
                ],
                SELECT_WINNER: [
                    CallbackQueryHandler(BotHandlers.handle_winner, pattern=r"^winner\|")
                ]
            },
            fallbacks=[CommandHandler("cancel", BotHandlers.cancel)],
            allow_reentry=True
        )

        setresult_conv = ConversationHandler(
            entry_points=[CommandHandler("setresult", BotHandlers.set_result_start)],
            states={
                SET_RESULT_MATCH: [
                    CallbackQueryHandler(BotHandlers.set_result_select_match, pattern=r"^setresult_match\|")
                ],
                SET_RESULT_SCORE: [
                    CallbackQueryHandler(BotHandlers.set_result_select_score, pattern=r"^setresult_score\|"),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, BotHandlers.set_result_manual_score)
                ],
                SET_RESULT_WINNER: [
                    CallbackQueryHandler(BotHandlers.set_result_select_winner, pattern=r"^setresult_winner\|")
                ],
                SET_RESULT_CONFIRM: [
                    CallbackQueryHandler(BotHandlers.set_result_confirm, pattern=r"^setresult_confirm\|")
                ]
            },
            fallbacks=[CommandHandler("cancel", BotHandlers.cancel)],
            allow_reentry=True
        )

        app.add_handler(setresult_conv)
        app.add_handler(conv_handler)
        app.add_handler(CommandHandler("week", BotHandlers.current_week))
        app.add_handler(CommandHandler("helpme", BotHandlers.show_help))
        app.add_handler(CommandHandler("mybets", BotHandlers.my_predictions))
        app.add_handler(CommandHandler("champion", BotHandlers.leaderboard))
        app.add_handler(CommandHandler("nextweek", BotHandlers.next_week))
        app.add_handler(CommandHandler("matches", BotHandlers.matches_handler))
        app.add_handler(CommandHandler("startweek", BotHandlers.start_week_command))
        app.add_handler(CommandHandler("myguesses", BotHandlers.my_predictions))

        app.add_handler(CallbackQueryHandler(BotHandlers.handle_quick_start, pattern="^quick_start$"))
        app.add_handler(CallbackQueryHandler(BotHandlers.handle_my_predictions, pattern="^my_predictions$"))
        app.add_handler(CallbackQueryHandler(BotHandlers.handle_leaderboard, pattern="^leaderboard$"))
        app.add_handler(CallbackQueryHandler(BotHandlers.handle_current_matches, pattern="^current_matches$"))
        app.add_error_handler(BotHandlers.error_handler)

        logger.info("راه‌اندازی ربات...")
        app.run_polling(drop_pending_updates=True)
        
    except Exception as e:
        logger.error(f"خطا در راه‌اندازی ربات: {e}")
        raise

if __name__ == "__main__":
    setup_bot()