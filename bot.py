import logging
import json
import os
import subprocess
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
        self.github_pat = os.environ.get('GITHUB_PAT')
        self.base_dir = os.path.dirname(os.path.abspath(__file__))

    def _git_push(self, files: list, message: str):
        """변경된 파일을 GitHub에 push한다."""
        if not self.github_pat:
            logging.warning("GITHUB_PAT 미설정 — git push 건너뜀")
            return
        try:
            repo_url_with_pat = None
            result = subprocess.run(
                ['git', 'remote', 'get-url', 'origin'],
                cwd=self.base_dir, capture_output=True, text=True
            )
            remote_url = result.stdout.strip()
            # https://github.com/... → https://<PAT>@github.com/...
            if remote_url.startswith('https://'):
                repo_url_with_pat = remote_url.replace(
                    'https://', f'https://{self.github_pat}@', 1
                )
                subprocess.run(
                    ['git', 'remote', 'set-url', 'origin', repo_url_with_pat],
                    cwd=self.base_dir, check=True
                )
            subprocess.run(
                ['git', 'add'] + files,
                cwd=self.base_dir, check=True
            )
            subprocess.run(
                ['git', 'config', 'user.email', 'bot@finance'],
                cwd=self.base_dir, check=True
            )
            subprocess.run(
                ['git', 'config', 'user.name', 'StockBot'],
                cwd=self.base_dir, check=True
            )
            diff = subprocess.run(
                ['git', 'diff', '--cached', '--quiet'],
                cwd=self.base_dir
            )
            if diff.returncode == 0:
                logging.info("git push: 변경사항 없음, 건너뜀")
                return
            subprocess.run(
                ['git', 'commit', '-m', message],
                cwd=self.base_dir, check=True
            )
            subprocess.run(
                ['git', 'push', 'origin', 'main'],
                cwd=self.base_dir, check=True
            )
            logging.info(f"git push 완료: {message}")
        except subprocess.CalledProcessError as e:
            logging.error(f"git push 실패: {e}")

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await context.bot.send_message(
            chat_id=update.effective_chat.id, 
            text="안녕하세요! 주식 분석 봇입니다.\n\n"
                 "<b>[보유주 관리]</b>\n"
                 "/buy [코드] [가격] - 보유주 추가\n"
                 "/sell [코드] - 보유주 삭제\n"
                 "/list - 보유주 목록 확인\n\n"
                 "<b>[관심주 관리]</b>\n"
                 "/watch [코드] - 관심주 추가\n"
                 "/unwatch [코드] - 관심주 삭제\n"
                 "/watchlist - 관심주 목록 확인\n\n"
                 "<b>[분석]</b>\n"
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

            # 종목명 조회 (KOSPI/KOSDAQ/ETF 순서로 시도)
            stock_name = code
            try:
                import FinanceDataReader as fdr
                for market in ['KOSPI', 'KOSDAQ', 'ETF/KR']:
                    try:
                        listing = fdr.StockListing(market)
                        sym_col = 'Symbol' if 'Symbol' in listing.columns else 'Code'
                        name_col = 'Name'
                        row = listing[listing[sym_col] == code]
                        if not row.empty:
                            stock_name = row.iloc[0][name_col]
                            break
                    except Exception:
                        continue
            except Exception:
                pass

            # holdings.json 업데이트
            holdings = self.analyzer.load_holdings()
            holdings[code] = {
                "name": stock_name,
                "buy_date": datetime.datetime.now().strftime('%Y-%m-%d'),
                "buy_price": int(price.replace(',', ''))
            }
            self.analyzer.save_holdings(holdings)
            self._git_push(['holdings.json'], f'bot: /buy {code} {stock_name} 추가 [skip ci]')

            await update.message.reply_text(f"✅ {stock_name}({code}) 종목이 포트폴리오에 추가되었습니다. (매수가: {price})")
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
                self._git_push(['holdings.json'], f'bot: /sell {code} 삭제 [skip ci]')
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

    async def watch(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            if len(context.args) < 1:
                await update.message.reply_text("사용법: /watch [종목코드]\n예: /watch 005930")
                return

            code = context.args[0]
            
            # watchlist.json 업데이트
            watchlist = self.analyzer.load_watchlist()
            if code in watchlist:
                await update.message.reply_text(f"⚠️ {code} 종목은 이미 관심주 목록에 있습니다.")
                return
            
            watchlist[code] = {
                "name": code,
                "add_date": datetime.datetime.now().strftime('%Y-%m-%d'),
                "source": "manual"
            }
            self.analyzer.save_watchlist(watchlist)
            self._git_push(['watchlist.json'], f'bot: /watch {code} 추가 [skip ci]')

            await update.message.reply_text(f"⭐ 종목이 관심주 목록에 추가되었습니다.")
        except Exception as e:
            await update.message.reply_text(f"❌ 오류 발생: {e}")

    async def unwatch(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            if len(context.args) < 1:
                await update.message.reply_text("사용법: /unwatch [종목코드]")
                return

            code = context.args[0]
            watchlist = self.analyzer.load_watchlist()
            
            if code in watchlist:
                del watchlist[code]
                self.analyzer.save_watchlist(watchlist)
                self._git_push(['watchlist.json'], f'bot: /unwatch {code} 삭제 [skip ci]')
                await update.message.reply_text(f"🗑 {code} 종목이 관심주 목록에서 삭제되었습니다.")
            else:
                await update.message.reply_text(f"❌ {code} 종목을 관심주 목록에서 찾을 수 없습니다.")
        except Exception as e:
            await update.message.reply_text(f"❌ 오류 발생: {e}")

    async def list_watchlist(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            watchlist = self.analyzer.load_watchlist()
            if not watchlist:
                await update.message.reply_text("현재 관심주 목록이 비어있습니다.")
                return

            text = "<b>[관심주 목록]</b>\n\n"
            for code, info in watchlist.items():
                source = info.get('source', '알 수 없음')
                add_date = info.get('add_date', '알 수 없음')
                text += f"• {info.get('name', code)}({code})\n"
                text += f"  - 추가일: {add_date}\n"
                text += f"  - 출처: {source}\n\n"
            
            await context.bot.send_message(chat_id=update.effective_chat.id, text=text, parse_mode='HTML')
        except Exception as e:
            await update.message.reply_text(f"❌ 오류 발생: {e}")

    def run(self):
        if not self.token:
            print("TELEGRAM_TOKEN이 설정되지 않았습니다.")
            return

        application = ApplicationBuilder().token(self.token).build()
        
        application.add_handler(CommandHandler('start', self.start))
        application.add_handler(CommandHandler('buy', self.buy))
        application.add_handler(CommandHandler('sell', self.sell))
        application.add_handler(CommandHandler('list', self.list_holdings))
        application.add_handler(CommandHandler('watch', self.watch))
        application.add_handler(CommandHandler('unwatch', self.unwatch))
        application.add_handler(CommandHandler('watchlist', self.list_watchlist))
        application.add_handler(CommandHandler('analyze', self.analyze_now))
        
        print("Bot is running... Press Ctrl+C to stop.")
        application.run_polling()

if __name__ == '__main__':
    bot = StockBot()
    bot.run()
