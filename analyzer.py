import FinanceDataReader as fdr
import pandas_ta_classic as ta
import pandas as pd
import numpy as np
from scipy.signal import argrelextrema
from notifier import TelegramNotifier
import datetime
import time
import json
import os
import html
import requests
import re
import xml.etree.ElementTree as ET
try:
    import google.genai as genai
    GENAI_LIBRARY = 'genai'
except ImportError:
    try:
        import google.generativeai as genai
        GENAI_LIBRARY = 'generativeai'
    except ImportError:
        genai = None
        GENAI_LIBRARY = None

class StockAnalyzer:
    def __init__(self):
        self.notifier = TelegramNotifier()
        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.holdings_file = os.path.join(self.base_dir, 'holdings.json')
        self.strategy_config_file = os.path.join(self.base_dir, 'strategy_config.json')
        self.watchlist_file = os.path.join(self.base_dir, 'watchlist.json')
        self.holdings = self.load_holdings()
        self.config = self.load_strategy_config()
        
        # Gemini AI 설정
        self.gemini_api_key = self.load_gemini_api_key()
        self.gemini_source = 'env' if os.environ.get('GEMINI_API_KEY') else ('dotenv' if self.gemini_api_key else None)
        self.model = None
        self.model_name = None
        self.client = None
        self.ai_enabled = False
        self.genai_library = GENAI_LIBRARY
        if self.gemini_api_key and genai is not None:
            for model_name in self.supported_gemini_models():
                try:
                    self.model_name = model_name
                    self.model = self.create_gemini_model(model_name)
                    self.ai_enabled = True
                    print(f"AI 초기화 성공: library={self.genai_library}, source={self.gemini_source}, model={model_name}")
                    break
                except Exception as e:
                    err_str = str(e)
                    if 'NOT_FOUND' in err_str or 'no longer available' in err_str or 'Resource not found' in err_str:
                        continue
                    print(f"AI 초기화 실패: {e}")
                    self.model = None
                    self.client = None
                    self.ai_enabled = False
                    break
            if not self.ai_enabled:
                print("Gemini 모델 초기화에 실패했습니다. 사용 가능한 모델과 키 권한을 확인하세요.")
        else:
            if self.gemini_api_key and genai is None:
                print("AI SDK 패키지가 설치되어 있지 않습니다. google.genai 또는 google.generativeai를 설치하세요.")
            elif not self.gemini_api_key:
                if os.environ.get('GEMINI_API_KEY'):
                    print("GEMINI_API_KEY 값을 가져왔지만, 초기화에 실패했습니다.")
                else:
                    print("GEMINI_API_KEY를 찾지 못했습니다. 환경변수 또는 .env 파일을 확인하세요.")
            if self.gemini_api_key:
                print(f"GEMINI_API_KEY present from {self.gemini_source}")

    def supported_gemini_models(self):
        return [
            'gemini-flash-latest',
            'gemini-pro-latest',
            'gemini-2.5-flash',
            'gemini-2.5-pro',
            'gemini-2.5-flash-lite',
            'gemini-2.0-flash',
            'gemini-2.0-flash-001'
        ]

    def create_gemini_model(self, model_name):
        if self.genai_library == 'genai':
            self.client = genai.Client(api_key=self.gemini_api_key)
            return self.client.chats.create(model=model_name)
        if self.genai_library == 'generativeai':
            genai.configure(api_key=self.gemini_api_key)
            if hasattr(genai, 'GenerativeModel'):
                return genai.GenerativeModel(model_name)
            if hasattr(genai, 'get_model'):
                return genai.get_model(model_name)
            raise RuntimeError('google.generativeai에서 모델을 생성할 수 없습니다.')
        raise RuntimeError('지원되지 않는 AI 모델 인터페이스입니다.')

    def load_gemini_api_key(self):
        key = os.environ.get('GEMINI_API_KEY')
        if key:
            return key

        env_path = os.path.join(os.getcwd(), '.env')
        if os.path.exists(env_path):
            try:
                with open(env_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        stripped = line.strip()
                        if not stripped or stripped.startswith('#'):
                            continue
                        if '=' not in stripped:
                            continue
                        name, value = stripped.split('=', 1)
                        if name.strip() == 'GEMINI_API_KEY':
                            return value.strip().strip('"').strip("'")
            except Exception:
                pass
        return None

    def load_strategy_config(self):
        """전략 파라미터를 외부 JSON 파일로 로드"""
        default = {
            "SMA50": 50,
            "SMA150": 150,
            "SMA200": 200,
            "RSI_LENGTH": 14,
            "BB_LENGTH": 20,
            "BB_STD": 2,
            "STOCH_RSI_LENGTH": 14,
            "STOCH_K": 3,
            "STOCH_D": 3,
            "MFI_LENGTH": 14,
            "VOL_AVG_WINDOW": 20,
            "TREND_TEMPLATE_LOOKBACK": 20,
            "TREND_TEMPLATE_PEAK_FACTOR": 0.75,
            "TIER1_WIN_RATE": 60,
            "TIER2_WIN_RATE": 50,
            "TRAILING_STOP_PCT": 0.03,
            "VALIDATE_LOOKBACK_DAYS": 120,
            "VALIDATE_MAX_HOLD_DAYS": 20,
            "VALIDATE_MIN_HISTORY": 200,
            "VALIDATE_STOP_LOSS_PCT": -0.03,
            "BACKTEST_SAMPLE_SIZE": 200,
            "BACKTEST_REQUIRE_US_MARKET_POSITIVE": False,
            "INTRADAY_ENABLED": True,
            "INTRADAY_TIMEOUT": 8,
            "INTRADAY_INTERVALS": ["1m", "2m", "5m", "15m"],
            "INTRADAY_MAX_RETRIES": 1,
            "PRICE_CHANGE_BASIS": "open",
            "US_RECOMMENDATION_ENABLED": True,
            "US_DOW_TICKERS": [
                "AAPL", "AMGN", "AMZN", "AXP", "BA", "CAT", "CRM", "CSCO", "CVX", "DIS",
                "GS", "HD", "HON", "IBM", "JNJ", "JPM", "KO", "MCD", "MMM", "MRK",
                "MSFT", "NKE", "NVDA", "PG", "SHW", "TRV", "UNH", "V", "VZ", "WMT"
            ],
            "US_NASDAQ_TICKERS": [
                "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "GOOG", "TSLA", "AVGO", "ADBE",
                "NFLX", "COST", "AMD", "QCOM", "INTC", "AMAT", "MU", "PANW", "CRWD", "ASML"
            ],
            "KOSPI_ETF_TICKERS": ["069500", "091170", "305720", "233740"],
            "US_ETF_TICKERS": ["SPY", "QQQ", "DIA"]
        }
        if os.path.exists(self.strategy_config_file):
            try:
                with open(self.strategy_config_file, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    default.update(loaded)
            except Exception:
                pass
        return default

    def save_strategy_config(self, config):
        with open(self.strategy_config_file, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=4)

    def load_holdings(self):
        """보유 종목 데이터 로드"""
        if os.path.exists(self.holdings_file):
            with open(self.holdings_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}

    def save_holdings(self, holdings):
        """보유 종목 데이터 저장"""
        with open(self.holdings_file, 'w', encoding='utf-8') as f:
            json.dump(holdings, f, ensure_ascii=False, indent=4)

    def load_watchlist(self):
        if os.path.exists(self.watchlist_file):
            with open(self.watchlist_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}

    def _normalize_yahoo_symbol(self, code):
        token = str(code).strip().upper()
        if token in ['US500', 'SP500', 'S&P500']:
            return '^GSPC'
        if token == 'DJI':
            return '^DJI'
        if token in ['IXIC', 'NASDAQ']:
            return '^IXIC'
        if token.startswith('^'):
            return token
        if token.endswith('.US'):
            return token[:-3]
        if token.endswith('.KS') or token.endswith('.KQ') or token.endswith('.HK') or token.endswith('.L'):
            return token
        if token.isdigit():
            return token + '.KS'
        return token

    def _fetch_yahoo_intraday(self, code, intervals=None, range_='1d', timeout=8):
        if intervals is None:
            intervals = self.config.get('INTRADAY_INTERVALS', ['1m', '2m', '5m', '15m'])
        symbol = self._normalize_yahoo_symbol(code)
        candidates = [symbol]
        if symbol.endswith('.KS'):
            alt = symbol.replace('.KS', '.KQ')
            if alt != symbol:
                candidates.append(alt)
        for symbol in candidates:
            for interval in intervals:
                url = (
                    f'https://query2.finance.yahoo.com/v8/finance/chart/{symbol}?'
                    f'range={range_}&interval={interval}&includePrePost=false'
                )
                response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=timeout)
                response.raise_for_status()
                payload = response.json()
                chart = payload.get('chart', {})
                error = chart.get('error')
                if error:
                    continue
                result = chart.get('result')
                if not result:
                    continue
                result = result[0]
                timestamps = result.get('timestamp') or []
                quote = result.get('indicators', {}).get('quote', [{}])[0]
                if not timestamps or not quote:
                    continue
                df = pd.DataFrame({
                    'Open': quote.get('open', []),
                    'High': quote.get('high', []),
                    'Low': quote.get('low', []),
                    'Close': quote.get('close', []),
                    'Volume': quote.get('volume', [])
                }, index=pd.to_datetime(timestamps, unit='s'))
                df = df.dropna(subset=['Close'])
                if df.empty:
                    continue
                return df
        raise ValueError(f'Yahoo intraday data not available for {code}')

    def _is_kr_stock_code(self, code):
        token = str(code).upper()
        return token.isdigit() or token.endswith(('.KS', '.KQ'))

    def _naver_symbol(self, code):
        token = str(code).upper()
        if token.endswith('.KS') or token.endswith('.KQ'):
            return token.split('.')[0]
        if token.isdigit():
            return token
        return None

    def _fetch_naver_intraday(self, code, timeout=8):
        symbol = self._naver_symbol(code)
        if not symbol:
            raise ValueError(f'Naver intraday unavailable for {code}')
        url = f'https://fchart.stock.naver.com/sise.nhn?symbol={symbol}&timeframe=minute&count=120&requestType=0'
        response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=timeout)
        response.raise_for_status()
        text = response.text
        items = re.findall(r'<item data="(.*?)" />', text)
        if not items:
            raise ValueError(f'Naver intraday returned no data for {code}')
        records = []
        for item in items:
            parts = item.split('|')
            if len(parts) < 6:
                continue
            dt_text, open_text, high_text, low_text, close_text, volume_text = parts[:6]
            try:
                dt = datetime.datetime.strptime(dt_text, '%Y%m%d%H%M')
                close = float(close_text)
                open_p = float(open_text) if open_text not in ('null', '') else close
                high_p = float(high_text) if high_text not in ('null', '') else close
                low_p = float(low_text) if low_text not in ('null', '') else close
                volume = float(volume_text) if volume_text not in ('null', '') else 0.0
                records.append((dt, open_p, high_p, low_p, close, volume))
            except Exception:
                continue
        if not records:
            raise ValueError(f'Naver intraday parsed no valid rows for {code}')
        df = pd.DataFrame(records, columns=['Datetime', 'Open', 'High', 'Low', 'Close', 'Volume'])
        df = df.set_index('Datetime')
        return df

    def _fetch_intraday(self, code, timeout=8):
        intervals = self.config.get('INTRADAY_INTERVALS', ['1m', '2m', '5m', '15m'])
        try:
            return self._fetch_yahoo_intraday(code, intervals=intervals, timeout=timeout)
        except Exception:
            if self._is_kr_stock_code(code):
                return self._fetch_naver_intraday(code, timeout=timeout)
            raise

    def _resolve_reference_price(self, code, current_price, intraday_time=None):
        """
        등락 계산 기준 가격을 반환합니다.
        - prev_close: 전일 종가 대비 (기본)
        - open: 당일 시가 대비
        """
        basis = str(self.config.get("PRICE_CHANGE_BASIS", "open")).strip().lower()
        session_date = intraday_time.date() if intraday_time is not None else None

        prev_close = None
        open_price = None
        try:
            daily = fdr.DataReader(code, start=(datetime.datetime.now() - datetime.timedelta(days=20)).strftime('%Y-%m-%d'))
            if not daily.empty:
                daily = daily.sort_index()
                if session_date is None:
                    session_date = daily.index[-1].date()

                same_day = daily[daily.index.date == session_date]
                if not same_day.empty:
                    open_val = same_day.iloc[-1].get('Open')
                    if pd.notna(open_val):
                        open_price = float(open_val)
                    prev_rows = daily[daily.index.date < session_date]
                    if not prev_rows.empty:
                        prev_close = float(prev_rows.iloc[-1]['Close'])
                else:
                    open_val = daily.iloc[-1].get('Open')
                    if pd.notna(open_val):
                        open_price = float(open_val)
                    if len(daily) >= 2:
                        prev_close = float(daily.iloc[-2]['Close'])
                    else:
                        prev_close = float(daily.iloc[-1]['Close'])
        except Exception:
            pass

        reference = prev_close
        if basis == "open":
            reference = open_price if open_price not in (None, 0) else prev_close
        if reference in (None, 0):
            reference = current_price

        return {
            'basis': basis,
            'reference': float(reference),
            'prev_close': float(prev_close) if prev_close not in (None, 0) else None,
            'open': float(open_price) if open_price not in (None, 0) else None
        }

    def get_latest_price(self, code):
        """15분 지연 인트라데이 데이터를 우선 사용하고, 실패 시 일별 데이터로 폴백합니다."""
        if not self.config.get('INTRADAY_ENABLED', True):
            raise RuntimeError('Intraday data is disabled in configuration.')
        timeout = self.config.get('INTRADAY_TIMEOUT', 8)
        try:
            df = self._fetch_intraday(code, timeout=timeout)
            if len(df) >= 2:
                last = df.iloc[-1]
                current_price = float(last['Close'])
                refs = self._resolve_reference_price(code, current_price, intraday_time=df.index[-1])
                previous_price = refs['prev_close'] if refs['prev_close'] is not None else refs['reference']
                return {
                    'source': 'intraday',
                    'last': current_price,
                    'previous': previous_price,
                    'prev_close': refs['prev_close'],
                    'open': refs['open'],
                    'basis': refs['basis'],
                    'time': df.index[-1]
                }
            if len(df) == 1:
                last = df.iloc[-1]
                current_price = float(last['Close'])
                refs = self._resolve_reference_price(code, current_price, intraday_time=df.index[-1])
                previous_price = refs['prev_close'] if refs['prev_close'] is not None else refs['reference']
                return {
                    'source': 'intraday',
                    'last': current_price,
                    'previous': previous_price,
                    'prev_close': refs['prev_close'],
                    'open': refs['open'],
                    'basis': refs['basis'],
                    'time': df.index[-1]
                }
        except Exception:
            pass
        try:
            df = fdr.DataReader(code, start=(datetime.datetime.now() - datetime.timedelta(days=7)).strftime('%Y-%m-%d'))
            if len(df) >= 2:
                last = df.iloc[-1]
                current_price = float(last['Close'])
                refs = self._resolve_reference_price(code, current_price, intraday_time=df.index[-1])
                previous_price = refs['prev_close'] if refs['prev_close'] is not None else refs['reference']
                return {
                    'source': 'daily',
                    'last': current_price,
                    'previous': previous_price,
                    'prev_close': refs['prev_close'],
                    'open': refs['open'],
                    'basis': refs['basis'],
                    'time': df.index[-1]
                }
        except Exception:
            pass
        return None

    def get_intraday_high(self, code):
        """조회 시점 기준 최고가를 가져옵니다."""
        try:
            df = self._fetch_intraday(code, timeout=self.config.get('INTRADAY_TIMEOUT', 8))
            if not df.empty and 'High' in df.columns:
                return float(df['High'].max())
        except Exception:
            pass

        try:
            today = datetime.datetime.now().date()
            df = fdr.DataReader(code, start=today.strftime('%Y-%m-%d'))
            if not df.empty:
                same_day = df[df.index.date == today]
                if not same_day.empty:
                    return float(same_day['High'].max())
        except Exception:
            pass

        return None

    def fetch_price_history(self, code, start=None, end=None):
        """기존 일별 시세를 그대로 호출하는 헬퍼."""
        return fdr.DataReader(code, start=start, end=end)

    def get_us_market_summary(self):
        """미국 주요 지수 요약 (S&P 500, Nasdaq, Dow)"""
        indices = {
            'S&P 500': 'US500', 
            'Nasdaq': 'IXIC', 
            'Dow': 'DJI'
        }
        summary = "<b>[미국 시장 요약]</b>\n"
        for name, symbol in indices.items():
            try:
                latest = self.get_latest_price(symbol)
                if latest:
                    change = latest['last'] - latest['previous']
                    pct_change = (change / latest['previous']) * 100 if latest['previous'] else 0
                    emoji = "📈" if change > 0 else "📉"
                    summary += f"{emoji} {name}: {latest['last']:.2f} ({pct_change:+.2f}%)\n"
                else:
                    raise ValueError('Intraday unavailable')
            except Exception:
                try:
                    df = fdr.DataReader(symbol)
                    last_row = df.iloc[-1]
                    prev_row = df.iloc[-2]
                    change = last_row['Close'] - prev_row['Close']
                    pct_change = (change / prev_row['Close']) * 100
                    emoji = "📈" if change > 0 else "📉"
                    summary += f"{emoji} {name}: {last_row['Close']:.2f} ({pct_change:+.2f}%)\n"
                except Exception:
                    summary += f"⚠️ {name}: 데이터 오류\n"
        return summary

    def get_us_market_condition(self, target_date=None):
        """타겟 날짜 기준 미국 주요 지수(Dow, Nasdaq, S&P 500) 상태를 반환합니다."""
        if target_date is None:
            target_date = datetime.datetime.now().date()
        if isinstance(target_date, datetime.datetime):
            target_date = target_date.date()

        target_timestamp = pd.Timestamp(target_date)

        indices = {
            'S&P 500': '^GSPC',
            'Nasdaq': '^IXIC',
            'Dow': '^DJI'
        }
        condition = {}
        overall_positive = True
        for name, symbol in indices.items():
            try:
                start = (target_date - datetime.timedelta(days=10)).strftime('%Y-%m-%d')
                end = target_date.strftime('%Y-%m-%d')
                df = fdr.DataReader(symbol, start=start, end=end)
                if df.empty:
                    raise ValueError('No data')
                if target_timestamp not in df.index:
                    df = df[df.index <= target_timestamp]
                    if df.empty:
                        raise ValueError('No trading day before target')
                last = df.iloc[-1]
                prev = df.iloc[-2]
                change = float(last['Close'] - prev['Close'])
                pct = float((change / prev['Close']) * 100) if prev['Close'] != 0 else 0.0
                positive = change >= 0
                condition[name] = {
                    'symbol': symbol,
                    'date': last.name.date() if hasattr(last.name, 'date') else last.name,
                    'last': float(last['Close']),
                    'previous': float(prev['Close']),
                    'change': change,
                    'pct_change': pct,
                    'positive': positive
                }
                if not positive:
                    overall_positive = False
            except Exception:
                condition[name] = {
                    'symbol': symbol,
                    'date': None,
                    'last': None,
                    'previous': None,
                    'change': None,
                    'pct_change': None,
                    'positive': False
                }
                overall_positive = False
        condition['all_positive'] = overall_positive
        condition['summary'] = " | ".join(
            [
                f"{name}: {'+' if info['positive'] else '-'}{info['pct_change']:+.2f}%" if info['pct_change'] is not None else f"{name}: 데이터 없음"
                for name, info in condition.items() if name in indices
            ]
        )
        return condition

    def save_watchlist(self, watchlist):
        with open(self.watchlist_file, 'w', encoding='utf-8') as f:
            json.dump(watchlist, f, ensure_ascii=False, indent=4)

    def detect_price_unit(self, code):
        code = str(code).upper()
        if code.isdigit() or code.endswith(('.KS', '.KQ', '.KR')):
            return '원'
        if code.endswith('.TO') or code.endswith(':TO') or code.startswith('TSX:'):
            return 'CAD'
        if code.endswith(('.US', '.O', '.N', '.A')) or code.startswith(('NASDAQ:', 'NYSE:', 'AMEX:')):
            return '달러'
        if code.endswith('.HK'):
            return '홍콩달러'
        if code.endswith('.L'):
            return '파운드'
        if code.isalpha():
            return '달러'
        return '원'

    def get_price_label(self, code):
        unit = self.detect_price_unit(code)
        if unit == '원':
            return '원'
        if unit == 'CAD':
            return 'CAD'
        if unit == '달러':
            return '달러'
        if unit == '홍콩달러':
            return 'HKD'
        if unit == '파운드':
            return 'GBP'
        return unit

    def format_price(self, price, code):
        label = self.get_price_label(code)
        if isinstance(price, float) and price != int(price):
            return f"{price:,.2f}{label}"
        return f"{price:,.0f}{label}"

    def format_price_change(self, current_price, previous_price, code):
        if previous_price is None or previous_price == 0:
            return "(변동 없음)"
        amount = current_price - previous_price
        percent = (amount / previous_price) * 100
        label = self.get_price_label(code)
        marker = '🔴' if amount > 0 else ('🔵' if amount < 0 else '⏺')
        if label == '원':
            amount_text = f"{amount:+,.0f}{label}"
        else:
            amount_text = f"{amount:+,.2f}{label}"
        percent_text = f"{percent:+.2f}%"
        return f"{marker} 등락가 {amount_text}, 등락율 {percent_text}"

    def clean_watchlist(self):
        """자동 추천으로 추가된 watchlist 항목 중 1주일 경과 후 holdings에 없는 항목만 삭제"""
        watchlist = self.load_watchlist()
        if not watchlist:
            return

        today = datetime.datetime.now().date()
        changed = False
        for code in list(watchlist.keys()):
            entry = watchlist[code]
            if entry.get('source') != 'auto_recommendation':
                continue
            add_date = entry.get('add_date')
            if not add_date:
                continue
            try:
                add_date_obj = datetime.datetime.strptime(add_date, '%Y-%m-%d').date()
            except Exception:
                continue

            days_passed = (today - add_date_obj).days
            if days_passed > 7 and code not in self.holdings:
                del watchlist[code]
                changed = True
                print(f"watchlist에서 자동추천 항목 {code}를 {days_passed}일 경과로 인해 자동 삭제했습니다.")

        if changed:
            self.save_watchlist(watchlist)

    def add_top_recommendation_to_watchlist(self, results):
        """Tier 1 추천 종목을 watchlist에 자동 추가"""
        if not results or 1 not in results or len(results[1]) == 0:
            return []

        watchlist = self.load_watchlist()
        added_codes = []
        today = datetime.datetime.now().strftime('%Y-%m-%d')

        for stock in results[1]:
            code = stock.get('code')
            if not code:
                continue
            if code in self.holdings:
                continue

            stock_name = html.unescape(stock.get('name', code))
            entry = watchlist.get(code)
            if entry:
                if entry.get('source') == 'auto_recommendation':
                    entry['name'] = stock_name
                    entry['add_date'] = today
                    watchlist[code] = entry
                    added_codes.append(code)
                continue

            watchlist[code] = {
                'name': stock_name,
                'add_date': today,
                'source': 'auto_recommendation'
            }
            added_codes.append(code)

        if added_codes:
            self.save_watchlist(watchlist)
        return added_codes

    def get_stock_news(self):
        """오늘의 주요 주식/업종/국제정세 뉴스를 함께 수집합니다."""
        try:
            market_news = self._fetch_google_news_items("주식 증시", limit=3)
            sector_news = self._fetch_google_news_items(
                "반도체 OR 전기차 OR 방산 OR 2차전지 OR 배터리 OR 테슬라 OR 유가 OR 양자컴퓨터 OR AI 로봇 OR AI GPU OR 인공지능 OR AI 반도체",
                limit=3
            )
            geo_news = self._fetch_google_news_items(
                "국제정세 전쟁 분쟁 관세 제재 유가 환율 금리 중앙은행",
                limit=3
            )

            lines = []
            lines.append("[오늘의 주요 주식 뉴스]")
            if market_news:
                lines.extend(market_news)
            else:
                lines.append("- 관련 뉴스가 없습니다.")

            lines.append("")
            lines.append("[업종/섹터 뉴스]")
            if sector_news:
                lines.extend(sector_news)
            else:
                lines.append("- 관련 뉴스가 없습니다.")

            lines.append("")
            lines.append("[국제정세 뉴스 (시장 영향 가능)]")
            if geo_news:
                lines.extend(geo_news)
            else:
                lines.append("- 관련 뉴스가 없습니다.")

            return "\n".join(lines)
        except Exception:
            return (
                "[오늘의 주요 주식 뉴스]\n- 뉴스를 가져오는 데 실패했습니다.\n\n"
                "[업종/섹터 뉴스]\n- 뉴스를 가져오는 데 실패했습니다.\n\n"
                "[국제정세 뉴스 (시장 영향 가능)]\n- 뉴스를 가져오는 데 실패했습니다."
            )

    def _fetch_google_news_items(self, query, limit=3):
        url = f"https://news.google.com/rss/search?q={requests.utils.quote(query + ' when:1d')}&hl=ko&gl=KR&ceid=KR:ko"
        headers = {
            'User-Agent': 'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)'
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        root = ET.fromstring(response.text)
        items = root.findall('.//item')

        lines = []
        for item in items[:limit]:
            title_el = item.find('title')
            link_el = item.find('link')
            pub_el = item.find('pubDate')
            title = title_el.text if title_el is not None else '제목 없음'
            link = link_el.text if link_el is not None else None
            pub = pub_el.text if pub_el is not None else ''
            if link:
                lines.append(f"- {title} ({pub})\n  {link}")
            else:
                lines.append(f"- {title} ({pub})")
        return lines

    def get_market_sentiment(self):
        """코스피 지수의 이평선 기반 시장 심리 분석 (상세 한글 설명 추가)"""
        try:
            today = datetime.datetime.now()
            start_date = (today - datetime.timedelta(days=100)).strftime('%Y-%m-%d')
            
            ks = fdr.DataReader('KS11', start=start_date)
            
            def analyze_index(df, name):
                if len(df) < 20: return f"{name}: 데이터 부족", False, "데이터 부족"
                df['SMA20'] = df['Close'].rolling(window=20).mean()
                df['SMA5'] = df['Close'].rolling(window=5).mean()
                last = df.iloc[-1]
                prev = df.iloc[-2]
                curr_p = last['Close']
                change = (curr_p - prev['Close']) / prev['Close'] * 100
                is_above_20 = curr_p > last['SMA20']
                is_up_trend = last['SMA5'] > prev['SMA5']
                
                if is_above_20 and is_up_trend:
                    status = "우호적"
                    desc = "지수가 이평선 위에서 안정적인 상승 흐름을 보이고 있습니다."
                    emoji = "🚀"
                elif is_above_20:
                    status = "보통"
                    desc = "지수가 이평선 위에 있으나 단기 숨고르기 중입니다."
                    emoji = "➡️"
                else:
                    status = "주의"
                    desc = "지수가 이평선 아래에 있어 하락 압력이 거셉니다. 보수적인 접근이 필요합니다."
                    emoji = "⚠️"
                
                msg = f"{emoji} <b>{name}</b>: {curr_p:,.2f} ({change:+.2f}%) - {status}\n    └ {desc}"
                return msg, status == "우호적"

            ks_msg, ks_pos = analyze_index(ks, "코스피")
            full_msg = "[국내 시장 상태 분석]\n" + ks_msg
            return full_msg, ks_pos
        except Exception as e:
            return f"⚠️ 시장 분석 오류: {e}", False

    def build_local_report(self, market_data, holding_data, watch_data, report_mode="monitor"):
        """AI 미사용 시에도 읽기 쉬운 로컬 요약 리포트를 생성"""
        header = "🤖 자동 기술적 분석 리포트 (로컬 요약)"
        if report_mode == "monitor":
            title = "[실시간 모니터링 요약]"
            watch_label = "관심 종목"
        else:
            title = "[일간 종합 투자 요약]"
            watch_label = "추천 종목"

        sections = [header, title, "[시장 요약]", market_data.strip()]
        if holding_data:
            sections.extend(["[보유 종목]", holding_data.strip()])
        if watch_data:
            sections.extend([f"[{watch_label}]", watch_data.strip()])

        return "\n\n".join(sections).strip()

    @staticmethod
    def extract_text_from_content(content):
        """Convert a Gemini Content object or candidate content to plain text."""
        if content is None:
            return None
        if isinstance(content, str):
            return content
        if isinstance(content, (list, tuple)):
            text_parts = []
            for part in content:
                part_text = StockAnalyzer.extract_text_from_content(part)
                if part_text:
                    text_parts.append(part_text)
            return "".join(text_parts).strip() or None
        if isinstance(content, dict):
            if 'text' in content:
                return StockAnalyzer.extract_text_from_content(content['text'])
            if 'content' in content:
                return StockAnalyzer.extract_text_from_content(content['content'])
            if 'parts' in content:
                return StockAnalyzer.extract_text_from_content(content['parts'])
            return str(content)
        if hasattr(content, 'text'):
            return StockAnalyzer.extract_text_from_content(content.text)
        if hasattr(content, 'content'):
            return StockAnalyzer.extract_text_from_content(content.content)
        if hasattr(content, 'parts') and content.parts:
            text_parts = []
            for part in content.parts:
                if not part:
                    continue
                part_text = StockAnalyzer.extract_text_from_content(part)
                if part_text:
                    text_parts.append(part_text)
            return "".join(text_parts).strip() or None
        if hasattr(content, 'inline_data') and content.inline_data is not None:
            return None
        return str(content)

    def _normalize_ai_response(self, response):
        text = StockAnalyzer.extract_text_from_content(response)
        if text:
            return text.strip()
        if hasattr(response, 'text'):
            text = StockAnalyzer.extract_text_from_content(response.text)
            if text:
                return text.strip()
        if hasattr(response, 'candidates') and response.candidates:
            text = StockAnalyzer.extract_text_from_content(response.candidates[0].content)
            if text:
                return text.strip()
        if hasattr(response, 'parts'):
            text = StockAnalyzer.extract_text_from_content(response.parts)
            if text:
                return text.strip()
        return None

    def ask_ai_report(self, market_data, holding_data, watch_data, report_mode="monitor"):
        """Gemini AI를 사용하여 주식 전문가 스타일의 한글 리포트 생성"""
        if not self.model:
            return self.build_local_report(market_data, holding_data, watch_data, report_mode)

        if report_mode == "monitor":
            prompt = f"""
주식 투자 전문가로서 아래 데이터를 바탕으로 30분 단위 실시간 모니터링 리포트를 작성해줘.

[데이터 정보]
1. 시장 상황: {market_data}
2. 보유 종목 상태: {holding_data}
3. 관심 종목 상태: {watch_data}

[작성 가이드라인]
- **어투**: 신뢰감 있고 친숙한 한국어 존댓말로 작성해줘.
- **언어 제약**: 영어 표현과 전문 용어를 쓰지 말고, 쉬운 한국어로 풀어 설명해줘.
- **중요**: 보유 종목과 관심 종목 정보를 명확히 구분해서 작성해줘. 각 섹션은 분리되어 있어야 하며, 제목을 지나치게 생략하지 말고 구분이 쉽게 유지되도록 해줘.
- **핵심 요구**: 각 종목에 대한 설명에 반드시 입력된 `현재가`, `등락가`, `등락율` 수치를 포함해줘. 전달된 숫자를 변경하지 말고, 가능한 한 그대로 반영해서 작성해줘.
- **추가 요구**: 시장에서 특정 업종/그룹(예: 반도체, 전기차/테슬라, 방산, 2차전지/배터리, 유가/원자재)이 함께 움직이고 있다면 그 배경을 함께 설명해줘.
- **구조**:
  1. 현재 시장의 분위기를 한 문단으로 정리해줘.
  2. [보유 종목] 섹션을 만들어서, 각 종목에 대해 왜 매도/보유 판단을 했는지 설명해줘.
  3. [관심 종목] 섹션을 만들어서, 각 종목에 대해 왜 기다려야 하는지 또는 주의할 점을 설명해줘.
- **표현 금지**: '트레일링 스톱', '깃발형 패턴', '에너지 응축', '변동성 수렴' 등의 전문 용어를 쓰지 말고, '고점 대비 하락 기준', '급등 후 숨고르기', '거래가 조용해진 구간' 같은 쉬운 설명으로 바꿔줘.
- **문장 구성**: 각 설명은 새 문단으로 구분하고, 항목 사이에는 빈 줄을 넣어줘.
- **가장 중요한 것**: 왜 그런 판단을 했는지 이유를 분명하게 설명해줘.
"""
        else:
            prompt = f"""
주식 투자 전문가로서 아래 데이터를 바탕으로 일간 종합 투자 리포트를 작성해줘.

[데이터 정보]
1. 시장 상황: {market_data}
2. 보유 종목 상태: {holding_data}
3. 추천 종목 상태: {watch_data}

[작성 가이드라인]
- **어투**: 신뢰감 있고 친숙한 한국어 존댓말로 작성해줘.
- **언어 제약**: 영어 표현과 전문 용어를 쓰지 말고, 쉬운 한국어로 풀어 설명해줘.
- **핵심 요구**: 각 추천 종목 설명에 반드시 입력된 `현재가` 수치를 포함해줘. 전달된 숫자를 변경하지 말고, 가능한 한 그대로 반영해서 작성해줘.
- **중요**: 보유 종목과 추천 종목 정보를 명확히 구분해서 작성해줘. 각 섹션은 분리되어 있어야 하며, 제목을 지나치게 생략하지 말고 구분이 쉽게 유지되도록 해줘.
- **필수 섹션**: `[국제정세 뉴스 요약]` 섹션을 반드시 포함하고, 입력 데이터의 국제정세 뉴스에서 시장에 영향이 큰 2~3개를 간단히 요약해줘.
- **추가 요구**: 업종/섹터 뉴스에서 반도체, 전기차/테슬라, 방산, 2차전지/배터리, 유가/원자재, 양자컴퓨터, AI 로봇, AI GPU, 인공지능/AI 반도체 관련 이슈가 있다면, 그 업종이 왜 함께 움직이고 있는지 배경까지 함께 설명해줘.
- **구조**:
  1. 현재 시장의 분위기를 한 문단으로 정리해줘.
  2. [국제정세 뉴스 요약] 섹션을 만들어서, 오늘 시장에 영향을 줄 수 있는 이슈를 정리해줘.
  3. [보유 종목] 섹션을 만들어서, 각 종목에 대해 왜 매도/보유 판단을 했는지 설명해줘.
  4. [추천 종목] 섹션을 만들어서, 각 종목에 대해 왜 추천하는지, 왜 지금 매수 또는 매수를 보류해야 하는지 설명해줘.
- **표현 금지**: '트레일링 스톱', '깃발형 패턴', '에너지 응축', '변동성 수렴' 등의 전문 용어를 쓰지 말고, 쉬운 설명으로 바꿔줘.
- **문장 구성**: 각 설명은 새 문단으로 구분하고, 항목 사이에는 빈 줄을 넣어줘.
- **가장 중요한 것**: 왜 추천하는지 이유를 분명하게 설명해줘.
"""
        import time
        wait_times = [30, 60]
        for attempt in range(3):
            try:
                if self.genai_library == 'genai' and self.model is not None:
                    response = self.model.send_message(prompt)
                    normalized = self._normalize_ai_response(response)
                    if normalized:
                        return normalized
                    return self.build_local_report(market_data, holding_data, watch_data, report_mode)
                elif self.genai_library == 'generativeai' and self.model is not None:
                    if not hasattr(self.model, 'generate_content') and hasattr(genai, 'GenerativeModel'):
                        self.model = genai.GenerativeModel(self.model_name)
                    if hasattr(self.model, 'generate_content'):
                        response = self.model.generate_content(prompt)
                    elif hasattr(self.model, 'generate_text'):
                        response = self.model.generate_text(prompt)
                    elif hasattr(self.model, 'send_message'):
                        response = self.model.send_message(prompt)
                    else:
                        raise RuntimeError('google.generativeai 모델 객체에서 지원되는 호출 메서드가 없습니다.')
                    normalized = self._normalize_ai_response(response)
                    if normalized:
                        return normalized
                    return self.build_local_report(market_data, holding_data, watch_data, report_mode)
                elif hasattr(genai, 'generate_text'):
                    model_name = self.model_name or 'gemini-2.1'
                    response = genai.generate_text(model=model_name, prompt=prompt)
                    normalized = self._normalize_ai_response(response)
                    if normalized:
                        return normalized
                    return self.build_local_report(market_data, holding_data, watch_data, report_mode)
                else:
                    raise RuntimeError('지원되지 않는 AI 모델 인터페이스입니다.')
            except Exception as e:
                err_str = str(e)
                if "429" in err_str and attempt < 2:
                    wait_sec = wait_times[attempt]
                    print(f"AI 호출 한도 초과, {wait_sec}초 후 재시도... ({attempt+1}/3)")
                    time.sleep(wait_sec)
                    continue
                print(f"AI 호출 중 오류 발생: {e}")
                return self.build_local_report(market_data, holding_data, watch_data, report_mode)

    def get_indicators(self, df, kospi_index=None):
        """기술적 지표 계산 (SMA, RSI, MACD, BB, StochRSI, MFI)"""
        df = df.copy()
        if len(df) < 2:
            return df

        # SMAs for Trend Template
        sma50 = ta.sma(df['Close'], length=self.config.get('SMA50', 50))
        sma150 = ta.sma(df['Close'], length=self.config.get('SMA150', 150))
        sma200 = ta.sma(df['Close'], length=self.config.get('SMA200', 200))
        df['SMA50'] = sma50 if sma50 is not None else np.nan
        df['SMA150'] = sma150 if sma150 is not None else np.nan
        df['SMA200'] = sma200 if sma200 is not None else np.nan

        # Relative Strength vs Index (50일 기준 - 진짜 주도주 식별)
        if kospi_index is not None:
            common_idx = df.index.intersection(kospi_index.index)
            if len(common_idx) > 50:
                stock_returns = df.loc[common_idx, 'Close'].pct_change(50)
                index_returns = kospi_index.loc[common_idx, 'Close'].pct_change(50)
                df.loc[common_idx, 'RS_LINE'] = stock_returns - index_returns

        # RSI
        rsi = ta.rsi(df['Close'], length=self.config.get('RSI_LENGTH', 14))
        df['RSI'] = rsi if rsi is not None else np.nan

        # MACD
        df['MACD'] = np.nan
        df['MACDs'] = np.nan
        df['MACDh'] = np.nan
        macd = ta.macd(df['Close'])
        if isinstance(macd, dict):
            if 'MACD_12_26_9' in macd and macd['MACD_12_26_9'] is not None:
                df['MACD'] = macd['MACD_12_26_9']
            if 'MACDs_12_26_9' in macd and macd['MACDs_12_26_9'] is not None:
                df['MACDs'] = macd['MACDs_12_26_9']
            if 'MACDh_12_26_9' in macd and macd['MACDh_12_26_9'] is not None:
                df['MACDh'] = macd['MACDh_12_26_9']

        # Bollinger Bands
        bb_length = self.config.get('BB_LENGTH', 20)
        bb_std = self.config.get('BB_STD', 2)
        df['BBU'] = np.nan
        df['BBM'] = np.nan
        df['BBL'] = np.nan
        df['BBW'] = np.nan
        bbands = ta.bbands(df['Close'], length=bb_length, std=bb_std)
        if bbands is not None:
            bbu_col = f'BBU_{bb_length}_{bb_std}.0'
            bbm_col = f'BBM_{bb_length}_{bb_std}.0'
            bbl_col = f'BBL_{bb_length}_{bb_std}.0'
            if bbu_col in bbands and bbands[bbu_col] is not None:
                df['BBU'] = bbands[bbu_col]
            if bbm_col in bbands and bbands[bbm_col] is not None:
                df['BBM'] = bbands[bbm_col]
            if bbl_col in bbands and bbands[bbl_col] is not None:
                df['BBL'] = bbands[bbl_col]
            if df['BBU'].notna().any() and df['BBL'].notna().any() and df['BBM'].notna().any():
                df['BBW'] = (df['BBU'] - df['BBL']) / df['BBM']

        # Stochastic RSI
        df['STOCH_K'] = np.nan
        df['STOCH_D'] = np.nan
        stoch = ta.stochrsi(
            df['Close'],
            length=self.config.get('STOCH_RSI_LENGTH', 14),
            rsi_length=self.config.get('RSI_LENGTH', 14),
            k=self.config.get('STOCH_K', 3),
            d=self.config.get('STOCH_D', 3)
        )
        if stoch is not None:
            k_col = f'STOCHRSIk_{self.config.get("STOCH_RSI_LENGTH", 14)}_{self.config.get("RSI_LENGTH", 14)}_{self.config.get("STOCH_K", 3)}_{self.config.get("STOCH_D", 3)}'
            d_col = f'STOCHRSId_{self.config.get("STOCH_RSI_LENGTH", 14)}_{self.config.get("RSI_LENGTH", 14)}_{self.config.get("STOCH_K", 3)}_{self.config.get("STOCH_D", 3)}'
            if k_col in stoch and stoch[k_col] is not None:
                df['STOCH_K'] = stoch[k_col]
            if d_col in stoch and stoch[d_col] is not None:
                df['STOCH_D'] = stoch[d_col]

        # MFI (Money Flow Index)
        mfi = ta.mfi(df['High'], df['Low'], df['Close'], df['Volume'], length=self.config.get('MFI_LENGTH', 14))
        df['MFI'] = mfi if mfi is not None else np.nan

        # Volume Average
        df['VOL_AVG'] = df['Volume'].rolling(window=self.config.get('VOL_AVG_WINDOW', 20)).mean()

        # ATR (Average True Range) - 종목별 변동성 기반 손절/목표가 계산용
        atr_length = self.config.get('ATR_LENGTH', 14)
        atr = ta.atr(df['High'], df['Low'], df['Close'], length=atr_length)
        df['ATR'] = atr if atr is not None else np.nan

        return df

    def detect_divergence(self, df, idx=-1):
        """RSI 상승 다이버전스 감지 (정석: 실제 저점 2개 비교)
        
        조건:
        1. 가격 저점2 < 저점1 (더 낮은 저점)
        2. RSI 저점2 > RSI 저점1 (더 높은 RSI) → 다이버전스
        3. RSI가 현재 상승 중 (추가 확인)
        4. 최근 RSI가 과매도권(40 이하)에서 발생한 경우만 유효
        """
        df_target = df.iloc[:idx+1] if idx != -1 else df
        if len(df_target) < 40: return False
        
        closes = df_target['Close'].values
        rsi_vals = df_target['RSI'].values
        
        # NaN 제거 확인
        if any(v != v for v in rsi_vals[-40:]):  # NaN check
            return False
        
        # 최근 40일에서 로컬 저점 찾기 (최소 5봉 간격)
        recent_closes = closes[-40:]
        recent_rsi = rsi_vals[-40:]
        
        local_lows = []
        for i in range(2, len(recent_closes) - 2):
            if (recent_closes[i] < recent_closes[i-1] and
                recent_closes[i] < recent_closes[i-2] and
                recent_closes[i] < recent_closes[i+1] and
                recent_closes[i] < recent_closes[i+2]):
                local_lows.append((i, recent_closes[i], recent_rsi[i]))
        
        if len(local_lows) < 2:
            return False
        
        # 가장 최근 두 저점 비교
        p1_idx, p1_price, p1_rsi = local_lows[-2]
        p2_idx, p2_price, p2_rsi = local_lows[-1]
        
        # 다이버전스 조건: 가격은 하락, RSI는 상승
        if p2_price >= p1_price:
            return False
        if p2_rsi <= p1_rsi:
            return False
        
        # RSI가 과매도권(45 이하)에서 발생해야 유효
        if p2_rsi > 45:
            return False
        
        # 두 번째 저점이 최근 10봉 이내여야 함 (타이밍 유효성)
        if p2_idx < len(recent_closes) - 10:
            return False
        
        return True

    def detect_patterns(self, df, idx=-1):
        """Wedge & Flag 패턴 감지 (단순화된 로직)"""
        df_target = df.iloc[:idx+1] if idx != -1 else df
        if len(df_target) < 20: return ""
        
        recent_vol = df_target['High'].tail(10).max() - df_target['Low'].tail(10).min()
        prev_vol = df_target['High'].iloc[-20:-10].max() - df_target['Low'].iloc[-20:-10].min()
        
        patterns = []
        if recent_vol < prev_vol * 0.7:
            patterns.append("거래가 조용해져 다음 움직임을 준비하는 모습입니다.")
            
        # Flag 패턴: 급등 후 횡보
        returns = df_target['Close'].pct_change(5).iloc[-10:-5]
        if len(returns) > 0 and returns.max() > 0.05: # 5일간 5% 이상 급등 후
            curr_returns = df_target['Close'].pct_change(5).iloc[-1]
            if abs(curr_returns) < 0.02: # 현재는 횡보 중
                patterns.append("최근 급등 뒤 숨고르기 구간에 진입했습니다.")
                
        return ", ".join(patterns)

    def is_taj_mahal_signal(self, df, idx=-1):
        """타지마할 밴드 (BB 하단 지지 + RSI 반등) - 강화 버전
        
        조건 (모두 충족 필요):
        1. 최근 3일 내 가격이 BB 하단에 터치 또는 하단 아래로 내려갔다가 회복
        2. 현재 가격이 BB 하단 위에 있음 (반등 확인)
        3. RSI가 35 이하 과매도 후 현재 상승 중
        4. 거래량이 평균 이상 (가짜 반등 필터)
        5. 캔들이 양봉 (현재가 > 시가)
        """
        df_target = df.iloc[:idx+1] if idx != -1 else df
        if len(df_target) < 5: return False
        
        last = df_target.iloc[-1]
        
        # 필수값 유효성 확인
        for col in ['Close', 'BBL', 'RSI', 'Volume', 'VOL_AVG', 'Open']:
            if col not in df_target.columns:
                return False
            if last[col] != last[col]:  # NaN
                return False
        
        # 조건 1+2: 최근 3일 내 BB 하단 터치 후 현재 위에 있음
        recent_3 = df_target.iloc[-3:]
        touched_lower = any(row['Close'] <= row['BBL'] * 1.02 for _, row in recent_3.iterrows())
        above_lower_now = last['Close'] > last['BBL']
        if not (touched_lower and above_lower_now):
            return False
        
        # 조건 3: RSI 과매도 후 반등
        rsi_recent = df_target['RSI'].iloc[-5:].values
        rsi_was_oversold = any(r <= 38 for r in rsi_recent if r == r)
        rsi_rising = last['RSI'] > df_target['RSI'].iloc[-2]
        if not (rsi_was_oversold and rsi_rising):
            return False
        
        # 조건 4: 거래량 평균 이상
        if last['Volume'] < last['VOL_AVG'] * 0.8:
            return False
        
        # 조건 5: 양봉
        if last['Close'] <= last['Open']:
            return False
        
        return True

    def detect_bb_squeeze(self, df, idx=-1):
        """Bollinger Band Squeeze 감지 (변동성 수렴)"""
        df_target = df.iloc[:idx+1] if idx != -1 else df
        if len(df_target) < 30: return False
        
        # 현재 BBW가 최근 30일 중 하위 10% 수준인지 확인
        current_bbw = df_target['BBW'].iloc[-1]
        bbw_history = df_target['BBW'].tail(30)
        
        if current_bbw <= bbw_history.quantile(0.1):
            return True
        return False

    def detect_volume_spike(self, df, idx=-1):
        """거래량 급증 감지 (평균 대비 2.5배 이상 - 기존 2배에서 강화)"""
        df_target = df.iloc[:idx+1] if idx != -1 else df
        if len(df_target) < 2: return False
        
        last = df_target.iloc[-1]
        if last['Volume'] > last['VOL_AVG'] * 2.5:
            return True
        return False

    def detect_stoch_mfi_rebound(self, df, idx=-1):
        """Stochastic RSI & MFI 기반 과매도 반등 감지"""
        df_target = df.iloc[:idx+1] if idx != -1 else df
        if len(df_target) < 2: return False
        
        last = df_target.iloc[-1]
        prev = df_target.iloc[-2]
        
        # StochRSI K가 D를 골든크로스하고 20 이하(과매도)에서 반등할 때
        if prev['STOCH_K'] < prev['STOCH_D'] and last['STOCH_K'] > last['STOCH_D']:
            if last['STOCH_K'] < 30 or last['MFI'] < 30:
                return True
        return False

    def check_signals(self, df, idx=-1):
        """다양한 기술적 지표들을 종합하여 매수 신호 확인"""
        reasons = []
        
        # 1. RSI 다이버전스
        if self.detect_divergence(df, idx):
            reasons.append("RSI 반전 신호(상승 가능성)")
            
        # 2. Wedge/Flag 패턴
        patterns = self.detect_patterns(df, idx)
        if patterns:
            reasons.append(patterns)
            
        # 3. 타지마할 밴드 (BB 하단 지지 + RSI 반등)
        if self.is_taj_mahal_signal(df, idx):
            reasons.append("바닥권 반등 신호(BB 하단)")
            
        # 4. 볼린저 밴드 스퀴즈 (변동성 수렴)
        if self.detect_bb_squeeze(df, idx):
            reasons.append("거래가 조용해지며 다음 변동성을 준비하는 구간입니다.")
            
        # 5. 거래량 급증
        if self.detect_volume_spike(df, idx):
            reasons.append("거래량 급증")
            
        # 6. Stochastic RSI & MFI 과매도 반등
        if self.detect_stoch_mfi_rebound(df, idx):
            reasons.append("과매도 반등 신호")
            
        return reasons

    def check_trailing_stop(self, df, buy_date, threshold=0.03):
        """트레일링 스톱 감지 (고점 대비 일정 비율 하락 시 매도)"""
        # buy_date 이후의 데이터만 추출
        df_since_buy = df[df.index >= buy_date]
        if len(df_since_buy) < 1: return False, 0
        
        # 구매 이후 최고가 찾기
        peak_price = df_since_buy['Close'].max()
        current_price = df_since_buy['Close'].iloc[-1]
        
        # 하락률 계산
        drop_pct = (peak_price - current_price) / peak_price
        
        if drop_pct >= threshold:
            return True, drop_pct * 100
        return False, drop_pct * 100

    def is_trend_template(self, df, idx=-1):
        """마크 미너비니의 Trend Template (상승 추세 확인)"""
        df_target = df.iloc[:idx+1] if idx != -1 else df
        if len(df_target) < 200: return False
        
        last = df_target.iloc[-1]
        
        # 1. 현재가가 150일, 200일 이평선 위에 있음
        c1 = last['Close'] > last['SMA150'] and last['Close'] > last['SMA200']
        # 2. 150일 이평선이 200일 이평선 위에 있음
        c2 = last['SMA150'] > last['SMA200']
        # 3. 200일 이평선이 최소 1개월간 상승 추세
        lookback = self.config.get('TREND_TEMPLATE_LOOKBACK', 20)
        c3 = last['SMA200'] > df_target['SMA200'].iloc[-lookback]
        # 4. 50일 이평선이 150일, 200일 위에 있음
        c4 = last['SMA50'] > last['SMA150'] and last['SMA50'] > last['SMA200']
        # 5. 현재가가 52주 신고가 대비 일정 비율 이내
        peak_factor = self.config.get('TREND_TEMPLATE_PEAK_FACTOR', 0.75)
        high_52w = df_target['Close'].tail(250).max()
        c5 = last['Close'] >= (high_52w * peak_factor)
        
        return c1 and c2 and c3 and c4 and c5

    def validate_strategy(self, df, current_idx, config_override=None):
        """특정 종목의 과거 6개월 승률 검증 (미니 백테스트)
        
        손익 구조:
        - 하드 손절: 매수가 기준 -5% (초기 고정)
        - 수익 목표: +8% 도달 시 청산 (손익비 1:1.6)
        - 트레일링 스톱: 고점 대비 3.5% 하락 시 청산
        - 타임컷: VALIDATE_MAX_HOLD_DAYS 경과 시 청산
        """
        cfg = {**self.config, **config_override} if config_override else self.config
        lookback = cfg.get('VALIDATE_LOOKBACK_DAYS', 120)
        start_idx = max(cfg.get('VALIDATE_MIN_HISTORY', 200), current_idx - lookback)
        max_hold = cfg.get('VALIDATE_MAX_HOLD_DAYS', 20)
        trailing_stop = cfg.get('TRAILING_STOP_PCT', 0.035)
        fallback_stop = abs(cfg.get('VALIDATE_STOP_LOSS_PCT', -0.05))
        fallback_target = cfg.get('PROFIT_TARGET_PCT', 0.08)
        atr_stop_mult = cfg.get('ATR_STOP_MULTIPLIER', 2.0)
        atr_target_mult = cfg.get('ATR_TARGET_MULTIPLIER', 3.0)

        trades = []
        for i in range(start_idx, current_idx):
            reasons = self.check_signals(df, i)
            if reasons and self.is_trend_template(df, i):
                # 다음날 시가 매수 (현실적 진입 - 당일 종가 매수 비현실적 문제 해결)
                buy_idx = i + 1
                if buy_idx >= current_idx:
                    continue
                open_col = 'Open' if 'Open' in df.columns else 'Close'
                buy_price = float(df.iloc[buy_idx][open_col])
                if buy_price <= 0:
                    buy_price = float(df.iloc[i]['Close'])

                # ATR 기반 손절/목표가 (없으면 고정값 폴백)
                atr_val = None
                if 'ATR' in df.columns:
                    v = df.iloc[i]['ATR']
                    if pd.notna(v) and v > 0:
                        atr_val = float(v)
                has_premium = any(s in reasons for s in ["RSI 반전 신호(상승 가능성)", "바닥권 반등 신호(BB 하단)"])
                if atr_val:
                    hard_stop_pct = atr_stop_mult * atr_val / buy_price
                    effective_target = atr_target_mult * (1.5 if has_premium else 1.0) * atr_val / buy_price
                else:
                    hard_stop_pct = fallback_stop
                    effective_target = fallback_target * (1.5 if has_premium else 1.0)

                max_p = buy_price
                result = -hard_stop_pct
                for j in range(buy_idx, min(buy_idx + max_hold + 1, current_idx + 1)):
                    curr_p = float(df.iloc[j]['Close'])
                    if curr_p > max_p:
                        max_p = curr_p
                    pct_from_buy = (curr_p - buy_price) / buy_price
                    if pct_from_buy <= -hard_stop_pct:
                        result = -hard_stop_pct
                        break
                    if pct_from_buy >= effective_target:
                        result = effective_target
                        break
                    if max_p > buy_price and (max_p - curr_p) / max_p >= trailing_stop:
                        result = pct_from_buy
                        break
                    if j == buy_idx + max_hold:
                        result = pct_from_buy
                trades.append(result)
        
        if not trades: return 0, 0
        win_rate = len([t for t in trades if t > 0]) / len(trades) * 100
        avg_ret = sum(trades) / len(trades) * 100
        return win_rate, avg_ret

    def _is_market_in_uptrend(self, index_df, target_idx=None):
        """시장 지수가 SMA200 위에 있는지 확인 (상승장 판단)"""
        try:
            df = index_df.iloc[:target_idx+1] if target_idx is not None else index_df
            if len(df) < 200:
                return True  # 데이터 부족 시 필터 미적용
            sma200 = df['Close'].rolling(200).mean().iloc[-1]
            return float(df['Close'].iloc[-1]) > float(sma200)
        except Exception:
            return True

    def analyze_kospi(self, target_date=None):
        """코스피 전 종목 정밀 분석 (Tiered System)"""
        stocks = fdr.StockListing('KOSPI')
        kospi_index = fdr.DataReader('KS11', start=(datetime.datetime.now() - datetime.timedelta(days=365)).strftime('%Y-%m-%d'))
        etf_tickers = [str(x).strip() for x in self.config.get('KOSPI_ETF_TICKERS', []) if str(x).strip()]
        stock_codes = {str(code).strip() for code in stocks['Code']}
        extra_etfs = [code for code in etf_tickers if code not in stock_codes]
        
        # 시장 상태 판단 (KS11 SMA200 기준)
        market_filter = self.config.get('MARKET_FILTER_ENABLED', True)
        kospi_uptrend = self._is_market_in_uptrend(kospi_index)
        if market_filter and not kospi_uptrend:
            print("⚠️ 코스피 하락장 감지 (SMA200 이하): Tier1 진입 기준 강화 (Power Combo만 허용)")
        
        results = {1: [], 2: [], 3: []}
        count = 0
        total = len(stocks) + len(extra_etfs)
        
        if extra_etfs:
            print(f"Adding {len(extra_etfs)} extra KOSPI ETF candidates: {', '.join(extra_etfs)}")
        print(f"Starting Tiered Analysis for {total} candidates...")
        
        for _, stock in stocks.iterrows():
            code = str(stock['Code']).strip()
            name = stock['Name']
            
            try:
                df = fdr.DataReader(code, start=(datetime.datetime.now() - datetime.timedelta(days=400)).strftime('%Y-%m-%d'))
                if len(df) < 200: continue
                
                df = self.get_indicators(df, kospi_index)
                target_idx = len(df) - 1
                if target_date:
                    df_target = df[df.index <= target_date]
                    if len(df_target) < 1: continue
                    target_idx = len(df_target) - 1
                
                reasons = self.check_signals(df, target_idx)
                if not reasons: continue

                # 지표 추출
                last = df.iloc[target_idx]
                win_rate, avg_ret = self.validate_strategy(df, target_idx)
                is_elite = self.is_trend_template(df, target_idx)
                is_above_200 = last['Close'] > last['SMA200']
                rs_score = last['RS_LINE'] if 'RS_LINE' in last else 0
                avg_vol = float(df['Volume'].tail(20).mean()) if 'Volume' in df.columns else 0
                
                safe_name = html.escape(name)
                safe_reasons = html.escape(", ".join(reasons))
                sector = str(stock.get('Sector', '') or '기타').strip()
                
                prev_close = float(df.iloc[target_idx - 1]['Close']) if target_idx > 0 else float(last['Close'])
                stock_data = {
                    'name': safe_name,
                    'code': code,
                    'reasons': safe_reasons,
                    'win_rate': win_rate,
                    'avg_ret': avg_ret,
                    'rs_score': rs_score,
                    'last': float(last['Close']),
                    'prev_close': prev_close,
                    'avg_vol': avg_vol,
                    'sector': sector,
                }

                # Tier Classification
                # Tier 1 고품질 필터: 신호 2개 이상 + 양수 RS + 최소 거래량
                min_signals = self.config.get('TIER1_MIN_SIGNALS', 2)
                min_rs = self.config.get('TIER1_MIN_RS', 0.0)
                min_vol = self.config.get('MIN_AVG_VOLUME', 50000)
                
                # 강력 콤비 신호: RSI 다이버전스 + 타지마할 동시 발생 시 신호 개수 패널티 면제
                has_divergence = "RSI 반전 신호(상승 가능성)" in reasons
                has_taj_mahal = "바닥권 반등 신호(BB 하단)" in reasons
                power_combo = has_divergence and has_taj_mahal
                
                effective_min_signals = 1 if power_combo else min_signals
                tier1_quality = (
                    len(reasons) >= effective_min_signals and
                    rs_score >= min_rs and
                    (avg_vol >= min_vol or min_vol <= 0)
                )
                
                # 시장 필터: 하락장에서는 power_combo만 Tier1 허용, 나머지는 Tier2로 강등
                market_ok = kospi_uptrend or not market_filter or power_combo

                is_tier1 = is_elite and win_rate >= self.config.get('TIER1_WIN_RATE', 60) and tier1_quality and market_ok
                # 포지션 사이징: PowerCombo 1.5배, Tier1 1.0배, Tier2/3 0.5배
                if power_combo:
                    position_size = 1.5
                elif is_tier1:
                    position_size = 1.0
                else:
                    position_size = 0.5
                stock_data['power_combo'] = power_combo
                stock_data['position_size'] = position_size
                if is_tier1:
                    results[1].append(stock_data)
                elif is_above_200 and win_rate >= self.config.get('TIER2_WIN_RATE', 50):
                    results[2].append(stock_data)
                elif win_rate >= 40:
                    results[3].append(stock_data)
                
                count += 1
                if count % 200 == 0: print(f"Analyzed {count}/{total} stocks...")
            except Exception:
                continue

        for code in extra_etfs:
            name = code
            try:
                df = fdr.DataReader(code, start=(datetime.datetime.now() - datetime.timedelta(days=400)).strftime('%Y-%m-%d'))
                if len(df) < 200:
                    continue

                df = self.get_indicators(df, kospi_index)
                target_idx = len(df) - 1
                if target_date:
                    df_target = df[df.index <= target_date]
                    if len(df_target) < 1: continue
                    target_idx = len(df_target) - 1

                reasons = self.check_signals(df, target_idx)
                if not reasons: continue

                last = df.iloc[target_idx]
                win_rate, avg_ret = self.validate_strategy(df, target_idx)
                is_elite = self.is_trend_template(df, target_idx)
                is_above_200 = last['Close'] > last['SMA200']
                rs_score = last['RS_LINE'] if 'RS_LINE' in last else 0
                avg_vol = float(df['Volume'].tail(20).mean()) if 'Volume' in df.columns else 0
                safe_name = html.escape(name)
                safe_reasons = html.escape(", ".join(reasons))
                prev_close = float(df.iloc[target_idx - 1]['Close']) if target_idx > 0 else float(last['Close'])
                stock_data = {
                    'name': safe_name,
                    'code': code,
                    'reasons': safe_reasons,
                    'win_rate': win_rate,
                    'avg_ret': avg_ret,
                    'rs_score': rs_score,
                    'last': float(last['Close']),
                    'prev_close': prev_close,
                    'avg_vol': avg_vol,
                    'sector': 'ETF',
                }

                min_signals = self.config.get('TIER1_MIN_SIGNALS', 2)
                min_rs = self.config.get('TIER1_MIN_RS', 0.0)
                min_vol = self.config.get('MIN_AVG_VOLUME', 50000)
                has_divergence = "RSI 반전 신호(상승 가능성)" in reasons
                has_taj_mahal = "바닥권 반등 신호(BB 하단)" in reasons
                power_combo = has_divergence and has_taj_mahal
                effective_min_signals = 1 if power_combo else min_signals
                tier1_quality = (
                    len(reasons) >= effective_min_signals and
                    rs_score >= min_rs and
                    (avg_vol >= min_vol or min_vol <= 0)
                )
                market_ok = kospi_uptrend or not market_filter or power_combo
                is_tier1 = is_elite and win_rate >= self.config.get('TIER1_WIN_RATE', 60) and tier1_quality and market_ok
                if power_combo:
                    position_size = 1.5
                elif is_tier1:
                    position_size = 1.0
                else:
                    position_size = 0.5
                stock_data['power_combo'] = power_combo
                stock_data['position_size'] = position_size
                if is_tier1:
                    results[1].append(stock_data)
                elif is_above_200 and win_rate >= self.config.get('TIER2_WIN_RATE', 50):
                    results[2].append(stock_data)
                elif win_rate >= 40:
                    results[3].append(stock_data)

                count += 1
                if count % 200 == 0: print(f"Analyzed {count}/{total} candidates...")
            except Exception:
                continue

        # 결과 포맷팅
        formatted_recs = []
        tier_names = {1: "🥇 지금 매수", 2: "🥈 신중히 매수", 3: "🥉 추가 확인 후 매수"}
        
        for t in [1, 2, 3]:
            if not results[t]: continue
            # power_combo(RSI다이버전스+타지마할) 우선, 그 다음 RS 점수 순 정렬
            results[t].sort(key=lambda x: (x.get('power_combo', False), x['rs_score']), reverse=True)
            # Tier1: 섹터 분산 + 포지션 한도 적용 (포트폴리오 리스크 관리)
            if t == 1:
                max_pos = self.config.get('MAX_POSITIONS', 10)
                max_sec = self.config.get('MAX_SECTOR_POSITIONS', 2)
                available = max(0, max_pos - len(self.holdings))
                diversified, sec_cnt = [], {}
                for s in results[1]:
                    sec = s.get('sector', '기타')
                    if sec_cnt.get(sec, 0) < max_sec and len(diversified) < available:
                        diversified.append(s)
                        sec_cnt[sec] = sec_cnt.get(sec, 0) + 1
                results[1] = diversified
            formatted_recs.append(f"<b>{tier_names[t]}</b>")
            for r in results[t][:5]: # 각 등급별 상위 5개만 노출
                current_price = r.get('last')
                intraday = self.get_latest_price(r['code'])
                if intraday:
                    current_price = intraday.get('last', current_price)
                price_text = self.format_price(current_price, r['code']) if current_price is not None else '가격 정보 없음'
                combo_mark = " ⭐" if r.get('power_combo') else ""
                msg = f"• <b>{r['name']}</b>({r['code']}): 현재가 {price_text} - {r['reasons']}{combo_mark}"
                formatted_recs.append(msg)
            formatted_recs.append("")
            
        if formatted_recs and formatted_recs[-1] == "":
            formatted_recs.pop()
        return formatted_recs, results

    def merge_tier_results(self, left, right):
        merged = {1: [], 2: [], 3: []}
        for tier in [1, 2, 3]:
            merged[tier].extend(left.get(tier, []))
            merged[tier].extend(right.get(tier, []))
            merged[tier].sort(key=lambda x: x.get('rs_score', 0), reverse=True)
        return merged

    def analyze_us_candidates(self, target_date=None):
        """다우/나스닥 대표 종목 후보군 분석"""
        if not self.config.get("US_RECOMMENDATION_ENABLED", True):
            return [], {1: [], 2: [], 3: []}

        dow_candidates = self.config.get("US_DOW_TICKERS", [])
        nasdaq_candidates = self.config.get("US_NASDAQ_TICKERS", [])
        us_etf_tickers = self.config.get("US_ETF_TICKERS", [])
        dow_set = {str(x).strip().upper() for x in dow_candidates}
        candidates = []
        seen = set()
        for code in dow_candidates + nasdaq_candidates + us_etf_tickers:
            token = str(code).strip().upper()
            if not token or token in seen:
                continue
            seen.add(token)
            market = "DOW" if token in dow_set else "NASDAQ"
            candidates.append((token, market))

        if not candidates:
            return [], {1: [], 2: [], 3: []}

        results = {1: [], 2: [], 3: []}
        start = (datetime.datetime.now() - datetime.timedelta(days=400)).strftime('%Y-%m-%d')
        try:
            dow_index = fdr.DataReader('DJI', start=start)
        except Exception:
            dow_index = None
        try:
            nasdaq_index = fdr.DataReader('IXIC', start=start)
        except Exception:
            nasdaq_index = None
        try:
            sp500_index = fdr.DataReader('US500', start=start)
        except Exception:
            sp500_index = None
        
        # 미국 시장 필터 (S&P500 SMA200 기준)
        market_filter = self.config.get('MARKET_FILTER_ENABLED', True)
        us_market_uptrend = self._is_market_in_uptrend(sp500_index) if sp500_index is not None else True

        print(f"Starting US candidate analysis for {len(candidates)} stocks...")
        # US 전용 파라미터 오버라이드 (거래세 없음, 더 넓은 ATR 스톱, 낮은 진입 기준)
        us_cfg_override = {
            'VALIDATE_STOP_LOSS_PCT': self.config.get('US_VALIDATE_STOP_LOSS_PCT', -0.07),
            'PROFIT_TARGET_PCT': self.config.get('US_PROFIT_TARGET_PCT', 0.10),
            'ATR_STOP_MULTIPLIER': self.config.get('US_ATR_STOP_MULTIPLIER', 2.5),
            'ATR_TARGET_MULTIPLIER': self.config.get('US_ATR_TARGET_MULTIPLIER', 4.0),
            'TRAILING_STOP_PCT': self.config.get('US_TRAILING_STOP_PCT', 0.05),
            'VALIDATE_MAX_HOLD_DAYS': self.config.get('US_VALIDATE_MAX_HOLD_DAYS', 30),
            'TRANSACTION_COST_BUY_PCT': self.config.get('US_TRANSACTION_COST_BUY_PCT', 0.0001),
            'TRANSACTION_COST_SELL_PCT': self.config.get('US_TRANSACTION_COST_SELL_PCT', 0.0005),
        }
        for code, market in candidates:
            try:
                df = fdr.DataReader(code, start=start)
                if len(df) < 200:
                    continue

                benchmark = dow_index if market == "DOW" else nasdaq_index
                df = self.get_indicators(df, benchmark)
                target_idx = len(df) - 1
                if target_date:
                    df_target = df[df.index <= target_date]
                    if len(df_target) < 1:
                        continue
                    target_idx = len(df_target) - 1

                reasons = self.check_signals(df, target_idx)
                if not reasons:
                    continue

                last = df.iloc[target_idx]
                win_rate, avg_ret = self.validate_strategy(df, target_idx, config_override=us_cfg_override)
                is_elite = self.is_trend_template(df, target_idx)
                is_above_200 = last['Close'] > last['SMA200']
                rs_score = last['RS_LINE'] if 'RS_LINE' in last else 0
                safe_reasons = html.escape(", ".join(reasons))
                prev_close = float(df.iloc[target_idx - 1]['Close']) if target_idx > 0 else float(last['Close'])

                avg_vol = float(df['Volume'].tail(20).mean()) if 'Volume' in df.columns else 0
                stock_data = {
                    'name': html.escape(code),
                    'code': code,
                    'market': market,
                    'reasons': safe_reasons,
                    'win_rate': win_rate,
                    'avg_ret': avg_ret,
                    'rs_score': rs_score,
                    'last': float(last['Close']),
                    'prev_close': prev_close,
                    'avg_vol': avg_vol
                }

                min_signals = self.config.get('TIER1_MIN_SIGNALS', 2)
                min_rs = self.config.get('TIER1_MIN_RS', 0.0)
                has_divergence = "RSI 반전 신호(상승 가능성)" in reasons
                has_taj_mahal = "바닥권 반등 신호(BB 하단)" in reasons
                power_combo = has_divergence and has_taj_mahal
                effective_min_signals = 1 if power_combo else min_signals
                tier1_quality = (
                    len(reasons) >= effective_min_signals and
                    rs_score >= min_rs
                )
                market_ok = us_market_uptrend or not market_filter or power_combo
                is_tier1 = is_elite and win_rate >= self.config.get('US_TIER1_WIN_RATE', 45) and tier1_quality and market_ok
                if power_combo:
                    position_size = 1.5
                elif is_tier1:
                    position_size = 1.0
                else:
                    position_size = 0.5
                stock_data['power_combo'] = power_combo
                stock_data['position_size'] = position_size
                if is_tier1:
                    results[1].append(stock_data)
                elif is_above_200 and win_rate >= self.config.get('US_TIER2_WIN_RATE', 40):
                    results[2].append(stock_data)
                elif win_rate >= 40:
                    results[3].append(stock_data)
            except Exception:
                continue

        for t in [1, 2, 3]:
            results[t].sort(key=lambda x: (x.get('power_combo', False), x.get('rs_score', 0)), reverse=True)

        # Tier1 포지션 한도 적용 (MAX_POSITIONS, 최대 5개)
        max_us_pos = min(5, self.config.get('MAX_POSITIONS', 10))
        results[1] = results[1][:max_us_pos]

        formatted = []
        tier_names = {1: "🥇 지금 매수", 2: "🥈 신중히 매수", 3: "🥉 추가 확인 후 매수"}
        for t in [1, 2, 3]:
            if not results[t]:
                continue
            formatted.append(f"<b>{tier_names[t]} (미국)</b>")
            for r in results[t][:5]:
                current_price = r.get('last')
                intraday = self.get_latest_price(r['code'])
                if intraday:
                    current_price = intraday.get('last', current_price)
                price_text = self.format_price(current_price, r['code']) if current_price is not None else '가격 정보 없음'
                msg = f"• <b>{r['name']}</b>({r['code']}, {r.get('market', 'US')}): 현재가 {price_text} - {r['reasons']}"
                formatted.append(msg)
            formatted.append("")

        if formatted and formatted[-1] == "":
            formatted.pop()
        return formatted, results

    def analyze_holdings(self):
        """보유 종목의 매도 타이밍(트레일링 스톱) 분석"""
        sell_alerts = []
        if not self.holdings: return sell_alerts
        
        print(f"Analyzing {len(self.holdings)} current holdings...")
        for code, info in self.holdings.items():
            try:
                name = info.get('name', code)
                buy_date = info.get('buy_date')
                if not buy_date: continue
                
                # 충분한 데이터 가져오기
                df = fdr.DataReader(code, start=(datetime.datetime.now() - datetime.timedelta(days=100)).strftime('%Y-%m-%d'))
                df = self.get_indicators(df)
                
                triggered, drop_pct = self.check_trailing_stop(df, buy_date)
                
                if triggered:
                    safe_name = html.escape(name)
                    sell_alerts.append(f"🚨 <b>{safe_name}({code}) 매도 알림</b>: 고점 대비 {drop_pct:.2f}% 하락 (트레일링 스톱)")
            except Exception as e:
                continue
        return sell_alerts

    def run(self):
        """매일 아침 수행하는 종합 분석 및 AI 리포트 전송"""
        import sys
        import holidays
        import os
        
        today = datetime.datetime.now()
        kr_holidays = holidays.KR()
        is_manual = os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
        force_run = os.environ.get("FORCE_RUN", "").lower() in ("1", "true", "yes")
        
        # 주말(5: 토요일, 6: 일요일) 또는 공휴일인 경우 스케줄 실행 안함
        # 단, 수동 실행(workflow_dispatch) 또는 FORCE_RUN=true일 경우에는 강제 실행합니다.
        if today.weekday() >= 5 or today.date() in kr_holidays:
            if is_manual or force_run:
                print(f"[{today}] 수동 실행/강제 실행 모드로 주말/공휴일 체크를 무시하고 분석을 진행합니다.")
            else:
                print(f"[{today}] 주말 또는 한국 공휴일 휴장일입니다. 종합 분석을 건너뜁니다.")
                sys.exit(0)
        
        if force_run and not is_manual:
            print("FORCE_RUN이 활성화되어 있어 강제 실행합니다.")
        
        print("종합 분석 및 AI 리포트 생성 시작...")
        
        # watchlist 정리
        self.holdings = self.load_holdings()
        self.clean_watchlist()

        # 1.데이터 수집
        us_summary = self.get_us_market_summary()
        sentiment_msg, is_positive = self.get_market_sentiment()
        recs_msg_kr, recs_raw_kr = self.analyze_kospi()
        recs_msg_us, recs_raw_us = self.analyze_us_candidates()
        recs_msg = []
        if recs_msg_kr:
            recs_msg.append("<b>[국내 추천]</b>")
            recs_msg.extend(recs_msg_kr)
        if recs_msg_us:
            recs_msg.append("")
            recs_msg.append("<b>[미국 추천: Dow/Nasdaq 후보군]</b>")
            recs_msg.extend(recs_msg_us)
        recs_raw = self.merge_tier_results(recs_raw_kr, recs_raw_us)
        sell_alerts = self.analyze_holdings()

        # 추천 종목 1등급 자동 추가
        added_codes = self.add_top_recommendation_to_watchlist(recs_raw)
        if added_codes:
            print(f"추천 종목 1등급 {', '.join(added_codes)}을(를) watchlist에 자동 추가했습니다.")
        else:
            if recs_raw and 1 in recs_raw and len(recs_raw[1]) == 0:
                print("오늘은 1등급 추천 종목이 없습니다. watchlist 자동 추가를 건너뜁니다.")
            else:
                current_watchlist = self.load_watchlist()
                skipped = [stock.get('code') for stock in recs_raw[1]
                           if stock.get('code') in self.holdings or stock.get('code') in current_watchlist]
                if skipped:
                    print("추천 종목 1등급 종목이 없거나 이미 watchlist/holdings에 있는 항목이어서 자동 추가가 수행되지 않았습니다.")
                    print(f"이미 watchlist/holdings에 있는 종목: {', '.join(skipped)}")
                else:
                    print("추천 종목 1등급 종목이 없거나 1등급 결과가 올바르지 않아 자동 추가가 수행되지 않았습니다.")
        
        # 2. AI에게 전달할 데이터 정리
        news_msg = self.get_stock_news()
        market_context = us_summary + "\n" + sentiment_msg + "\n" + news_msg
        holding_context = "\n".join(sell_alerts) if sell_alerts else "매도 신호 없음"
        
        # 추천 종목을 'watch_data' 항목으로 전달
        us_recommendation_note = "[미국 주요 지수 참고]\n" + us_summary
        if recs_msg:
            recommendation_context = "\n".join(recs_msg) + "\n\n" + us_recommendation_note
        else:
            recommendation_context = "추천 종목 없음\n\n" + us_recommendation_note
        
        # 3. AI 리포트 생성
        final_report = self.ask_ai_report(
            market_data=market_context,
            holding_data=holding_context,
            watch_data=recommendation_context,
            report_mode="daily"
        )

        # 제목 및 추가 정보 결합
        today = datetime.datetime.now().strftime('%Y-%m-%d')
        styled_report = f"📅 <b>[오늘의 AI 종합 투자 리포트 - {today}]</b>\n\n" + final_report
        
        # 4. 내역 기록 및 전송
        self.log_recommendations(recs_raw)
        self.notifier.send_message(styled_report)
        print("종합 분석 리포트 전송 완료.")

    def log_recommendations(self, results):
        """추천 결과를 recommendations.csv 파일에 저장"""
        csv_file = 'recommendations.csv'
        today = datetime.datetime.now().strftime('%Y-%m-%d')
        
        new_rows = []
        tier_names = {1: "지금 매수", 2: "신중히 매수", 3: "추가 확인 후 매수"}
        
        for tier, stocks in results.items():
            for s in stocks:
                new_rows.append({
                    'Date': today,
                    'Tier': tier_names[tier],
                    'Name': s['name'],
                    'Code': s['code'],
                    'Reasons': s['reasons'],
                    'WinRate': f"{s['win_rate']:.1f}%",
                    'AvgReturn': f"{s['avg_ret']:.1f}%",
                    'BuyPrice': s.get('last', '')
                })
        
        if new_rows:
            df_new = pd.DataFrame(new_rows)
            if os.path.exists(csv_file):
                df_new.to_csv(csv_file, mode='a', header=False, index=False, encoding='utf-8-sig')
            else:
                df_new.to_csv(csv_file, index=False, encoding='utf-8-sig')
            print(f"Logged {len(new_rows)} recommendations to {csv_file}")

if __name__ == "__main__":
    analyzer = StockAnalyzer()
    analyzer.run()
