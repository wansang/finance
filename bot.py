import logging
import json
import os
import datetime
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler
from analyzer import StockAnalyzer

# 로깅 설정
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

class StockBot:
    def __init__(self):
        self.analyzer = StockAnalyzer()
        self.token = os.environ.get('TELEGRAM_TOKEN')
        self.chat_id = os.environ.get('TELEGRAM_CHAT_ID')

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await context.bot.send_message(
            chat_id=update.effective_chat.id, 
            text="안녕하세요! 주식 분석 봇입니다.\n\n"
                 "<b>[명령어 안내]</b>\n"
                 "/buy [코드] [가격] - 종목 추가\n"
                 "/sell [코드] - 종목 삭제\n"
                 "/list - 현재 포트폴리오 확인\n"
                 "/analyze - 지금 즉시 코스피 분석 실행",
            parse_mode='HTML'
        )

    async def buy(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            if len(context.args) < 2:
                await update.message.reply_text("사용법: /buy [종목코드] [매수가]\n예: /buy 005930 75000")
                return

            code = context.args[0]
            price = context.args[1]
            
            # holdings.json 업데이트
            holdings = self.analyzer.load_holdings()
            holdings[code] = {
                "name": code, # 나중에 analyzer에서 이름을 채울 수 있음
                "buy_date": datetime.datetime.now().strftime('%Y-%m-%d'),
                "buy_price": int(price.replace(',', ''))
            }
            self.analyzer.save_holdings(holdings)
            
            await update.message.reply_text(f"✅ {code} 종목이 포트폴리오에 추가되었습니다. (매수가: {price})")
        except Exception as e:
            await update.message.reply_text(f"❌ 오류 발생: {e}")

    async def sell(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            if len(context.args) < 1:
                await update.message.reply_text("사용법: /sell [종목코드]")
                return

            code = context.args[0]
            holdings = self.analyzer.load_holdings()
            
            if code in holdings:
                del holdings[code]
                self.analyzer.save_holdings(holdings)
                await update.message.reply_text(f"🗑 {code} 종목이 포트폴리오에서 삭제되었습니다.")
            else:
                await update.message.reply_text("품목을 찾을 수 없습니다.")
        except Exception as e:
            await update.message.reply_text(f"❌ 오류 발생: {e}")

    async def list_holdings(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        holdings = self.analyzer.load_holdings()
        if not holdings:
            await update.message.reply_text("현재 보유 중인 종목이 없습니다.")
            return

        text = "<b>[현재 포트폴리오]</b>\n\n"
        for code, info in holdings.items():
            text += f"• {info.get('name', code)}({code})\n"
            text += f"  - 매수일: {info['buy_date']}\n"
            text += f"  - 매수가: {info['buy_price']:,}원\n\n"
        
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text, parse_mode='HTML')

    async def analyze_now(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("🔍 코스피 전체 분석을 시작합니다. (잠시만 기다려 주세요...)")
        self.analyzer.run() # 기존 run 메소드가 텔레그램으로 전송함
        await update.message.reply_text("✅ 분석이 완료되어 리포트가 전송되었습니다.")

    def run(self):
        if not self.token:
            print("TELEGRAM_TOKEN이 설정되지 않았습니다.")
            return

        application = ApplicationBuilder().token(self.token).build()
        
        application.add_handler(CommandHandler('start', self.start))
        application.add_handler(CommandHandler('buy', self.buy))
        application.add_handler(CommandHandler('sell', self.sell))
        application.add_handler(CommandHandler('list', self.list_holdings))
        application.add_handler(CommandHandler('analyze', self.analyze_now))
        
        print("Bot is running... Press Ctrl+C to stop.")
        application.run_polling()

if __name__ == '__main__':
    bot = StockBot()
    bot.run()
