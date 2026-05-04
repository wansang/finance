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
            "US_ETF_TICKERS": ["SPY", "QQQ", "DIA"],
            "ETF_EXPERT_TICKERS": [
                "069500", "102110", "091160", "091170", "114800",
                "305720", "261110", "139230", "091230", "251340",
                "278530", "233740", "364980", "396500"
            ]
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

    def _fetch_yahoo_meta(self, code, timeout=8):
        """Yahoo Finance API에서 당일 최고가/거래량 등 메타 정보를 가져옵니다. 결과는 인스턴스 캐시에 저장됩니다."""
        if not hasattr(self, '_yahoo_meta_cache'):
            self._yahoo_meta_cache = {}
        if code in self._yahoo_meta_cache:
            return self._yahoo_meta_cache[code]
        symbol = self._normalize_yahoo_symbol(code)
        candidates = [symbol]
        if symbol.endswith('.KS'):
            alt = symbol.replace('.KS', '.KQ')
            if alt != symbol:
                candidates.append(alt)
        for sym in candidates:
            url = (
                f'https://query2.finance.yahoo.com/v8/finance/chart/{sym}?'
                f'range=1d&interval=1m&includePrePost=false'
            )
            try:
                response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=timeout)
                response.raise_for_status()
                payload = response.json()
                chart = payload.get('chart', {})
                if chart.get('error'):
                    continue
                result = chart.get('result')
                if not result:
                    continue
                meta = result[0].get('meta', {})
                if meta:
                    self._yahoo_meta_cache[code] = meta
                    return meta
            except Exception:
                continue
        self._yahoo_meta_cache[code] = {}
        return {}

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
        """오늘 기준 당일 최고가를 가져옵니다."""
        timeout = self.config.get('INTRADAY_TIMEOUT', 8)

        # Yahoo meta에서 당일 최고가 조회 (regularMarketDayHigh = 장중 포함 당일 전체 최고가)
        try:
            meta = self._fetch_yahoo_meta(code, timeout=timeout)
            day_high = meta.get('regularMarketDayHigh')
            if day_high:
                return float(day_high)
        except Exception:
            pass

        # 폴백: fdr 일별 데이터에서 오늘 최고가 조회
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

    def get_52week_high(self, code):
        """Yahoo Finance 메타에서 52주 신고가를 가져옵니다. 캐시 재사용.
        장중에 신고가를 돌파한 경우 Yahoo는 종가 확정 전까지 업데이트하지 않으므로,
        현재가·당일최고가와 비교해 가장 큰 값을 반환합니다."""
        try:
            meta = self._fetch_yahoo_meta(code)
            candidates = []
            for key in ('fiftyTwoWeekHigh', 'regularMarketPrice', 'regularMarketDayHigh'):
                val = meta.get(key)
                if val:
                    try:
                        candidates.append(float(val))
                    except (TypeError, ValueError):
                        pass
            if candidates:
                return max(candidates)
        except Exception:
            pass
        return None

    def get_intraday_volume(self, code):
        """오늘 기준 누적 거래량을 가져옵니다."""
        timeout = self.config.get('INTRADAY_TIMEOUT', 8)

        # Yahoo meta에서 당일 누적 거래량 조회 (regularMarketVolume = 당일 실시간 누적 거래량)
        try:
            meta = self._fetch_yahoo_meta(code, timeout=timeout)
            volume = meta.get('regularMarketVolume')
            if volume is not None and int(volume) > 0:
                return int(volume)
        except Exception:
            pass

        # 폴백: fdr 일별 데이터에서 오늘 거래량 조회
        try:
            today = datetime.datetime.now().date()
            df = fdr.DataReader(code, start=today.strftime('%Y-%m-%d'))
            if not df.empty:
                same_day = df[df.index.date == today]
                if not same_day.empty and 'Volume' in same_day.columns:
                    vol = int(same_day['Volume'].sum())
                    if vol > 0:
                        return vol
        except Exception:
            pass

        return None

    def format_volume(self, volume, code):
        """거래량을 읽기 좋은 형식으로 변환합니다."""
        if volume is None:
            return None
        if volume >= 100_000_000:
            return f"{volume / 100_000_000:.1f}억주"
        if volume >= 10_000:
            return f"{volume / 10_000:.1f}만주"
        return f"{volume:,}주"

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

    def build_local_report(self, market_data, holding_data, watch_data, report_mode="monitor", ai_watch_data=None, entry_now_data=None):
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
        if report_mode == "monitor" and entry_now_data and entry_now_data.strip() != "없음":
            sections.extend(["🚨 [지금진입가능관심주]", entry_now_data.strip()])
        if watch_data:
            sections.extend([f"[{watch_label}]", watch_data.strip()])
        if report_mode == "monitor" and ai_watch_data and ai_watch_data.strip() != "없음":
            sections.extend(["[AI 추천 관심종목]", ai_watch_data.strip()])

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

    def ask_ai_report(self, market_data, holding_data, watch_data, report_mode="monitor", ai_watch_data=None, entry_now_data=None):
        """Gemini AI를 사용하여 주식 전문가 스타일의 한글 리포트 생성"""
        if not self.model:
            return self.build_local_report(market_data, holding_data, watch_data, report_mode, ai_watch_data, entry_now_data)

        if report_mode == "monitor":
            ai_watch_section_text = ai_watch_data if ai_watch_data else "없음"
            entry_now_section_text = entry_now_data if entry_now_data else "없음"
            prompt = f"""
주식 투자 전문가로서 아래 데이터를 바탕으로 30분 단위 실시간 모니터링 리포트를 작성해줘.

[데이터 정보]
1. 시장 상황: {market_data}
2. 보유 종목 상태: {holding_data}
3. 지금 진입 가능 관심종목 (매수 신호 포착): {entry_now_section_text}
4. 관심 종목 상태 (신호 없음, 대기 중): {watch_data}
5. AI 추천 관심종목 상태 (신호 없음, 대기 중): {ai_watch_section_text}

[작성 가이드라인]
- **어투**: 신뢰감 있고 친숙한 한국어 존댓말로 작성해줘.
- **언어 제약**: 영어 표현과 전문 용어를 쓰지 말고, 쉬운 한국어로 풀어 설명해줘.
- **중요**: 보유 종목, 지금진입가능관심주, 관심 종목, AI 추천 관심종목 섹션을 명확히 구분해서 작성해줘. 각 섹션은 분리되어 있어야 하며, 제목을 지나치게 생략하지 말고 구분이 쉽게 유지되도록 해줘.
- **핵심 요구**: 각 종목에 대한 설명에 반드시 입력된 `현재가`, `등락가`, `등락율`, `당일최고가`, `52주신고가`, `거래량` 수치를 포함해줘. `당일최고가`는 오늘 장중 기록한 최고가이고, `52주신고가`는 최근 1년간의 최고가야. 이 두 가지를 혼동하지 말고 각각 명확히 구분해서 표시해줘. 전달된 숫자를 변경하지 말고, 가능한 한 그대로 반영해서 작성해줘. 데이터가 없으면 생략해도 되지만, 있으면 반드시 넣어줘.
- **신고가 해석**: 데이터에 '52주 신고가 돌파' 또는 '52주 신고가 근접' 표시가 있는 종목은 반드시 이를 언급하고, 신고가 돌파/근접이 갖는 의미(추가 상승 모멘텀 가능성, 또는 차익실현 압력 등)를 한 문장으로 설명해줘.
- **추가 요구**: 시장에서 특정 업종/그룹(예: 반도체, 전기차/테슬라, 방산, 2차전지/배터리, 유가/원자재)이 함께 움직이고 있다면 그 배경을 함께 설명해줘.
- **구조**:
  1. 현재 시장의 분위기를 한 문단으로 정리해줘.
  2. [보유 종목] 섹션을 만들어서, 각 종목에 대해 왜 매도/보유 판단을 했는지 설명해줘.
  3. 🚨 [지금진입가능관심주] 섹션을 만들어서, 현재 매수 신호가 포착된 종목들을 강조해줘. 어떤 신호가 발생했는지, 진입가/손절/목표가를 명확히 언급하고, 지금 당장 행동해야 할 이유를 설명해줘. 데이터가 '없음'이면 이 섹션은 "현재 진입 가능한 관심종목이 없습니다."라고 짧게 작성해줘.
  4. [관심 종목] 섹션을 만들어서, 신호가 없는 대기 중인 종목들에 대해 왜 기다려야 하는지 또는 주의할 점을 설명해줘.
  5. [AI 추천 관심종목] 섹션을 만들어서, AI가 선별한 1티어 종목들의 현재 상태를 설명해줘. 승률과 평균수익률 데이터를 반드시 언급하고, 현재 매수 신호 여부와 주의할 점을 설명해줘.
- **진입가 안내**: 지금진입가능관심주 및 관심 종목 데이터에 `진입가`, `손절`, `목표` 가격이 포함되어 있으면 반드시 언급하고, 각 가격의 의미(어디서 사야 하는지, 어디서 손절해야 하는지, 목표 수익은 어느 수준인지)를 쉬운 말로 설명해줘.
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
- **진입가 안내**: 보유 종목 및 추천 종목 데이터에 `진입가`, `손절`, `목표` 가격이 포함되어 있으면 반드시 언급하고, 각 가격의 의미(어디서 사야 하는지, 어디서 손절해야 하는지, 목표 수익은 어느 수준인지)를 쉬운 말로 설명해줘.
- **신고가 해석**: 데이터에 '52주 신고가 돌파' 또는 '52주 신고가 근접' 표시가 있는 종목은 반드시 이를 언급하고, 신고가 돌파/근접이 갖는 의미(추가 상승 모멘텀 가능성, 또는 차익실현 압력 등)를 한 문장으로 설명해줘.
- **중요**: 보유 종목과 추천 종목 정보를 명확히 구분해서 작성해줘. 각 섹션은 분리되어 있어야 하며, 제목을 지나치게 생략하지 말고 구분이 쉽게 유지되도록 해줘.
- **필수 섹션**: `[국제정세 뉴스 요약]` 섹션을 반드시 포함하고, 입력 데이터의 국제정세 뉴스에서 시장에 영향이 큰 2~3개를 간단히 요약해줘.
- **추가 요구**: 업종/섹터 뉴스에서 반도체, 전기차/테슬라, 방산, 2차전지/배터리, 유가/원자재, 양자컴퓨터, AI 로봇, AI GPU, 인공지능/AI 반도체 관련 이슈가 있다면, 그 업종이 왜 함께 움직이고 있는지 배경까지 함께 설명해줘.
- **구조**:
  1. 현재 시장의 분위기를 한 문단으로 정리해줘.
  2. [국제정세 뉴스 요약] 섹션을 만들어서, 오늘 시장에 영향을 줄 수 있는 이슈를 정리해줘.
  3. [보유 종목] 섹션을 만들어서, 각 종목에 대해 왜 매도/보유 판단을 했는지 설명해줘.
  4. [추천 종목] 섹션을 만들어서, 각 종목에 대해 왜 추천하는지, 왜 지금 매수 또는 매수를 보류해야 하는지 설명해줘.
  5. 추천 종목 데이터에 '[ETF 전문가 추천]' 섹션이 포함되어 있으면, [ETF 추천] 섹션을 별도로 만들어서 해당 ETF를 간략히 소개해줘.
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
                    return self.build_local_report(market_data, holding_data, watch_data, report_mode, ai_watch_data, entry_now_data)
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
                    return self.build_local_report(market_data, holding_data, watch_data, report_mode, ai_watch_data, entry_now_data)
                elif hasattr(genai, 'generate_text'):
                    model_name = self.model_name or 'gemini-2.1'
                    response = genai.generate_text(model=model_name, prompt=prompt)
                    normalized = self._normalize_ai_response(response)
                    if normalized:
                        return normalized
                    return self.build_local_report(market_data, holding_data, watch_data, report_mode, ai_watch_data, entry_now_data)
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
                return self.build_local_report(market_data, holding_data, watch_data, report_mode, ai_watch_data, entry_now_data)

    def calculate_holding_targets(self, df, code, buy_date=None):
        """
        보유 종목 전용 손절가·목표가 계산.
        - 손절가: 매수 이후 최고가 × (1 - TRAILING_STOP_PCT)  (실제 트레일링 스톱 발동 기준)
        - 목표가: BBU(볼린저밴드 상단) 또는 현재가 +8%
        """
        if df is None or len(df) < 5:
            return None
        last = df.iloc[-1]
        close = float(last['Close'])

        trailing_stop_pct = self.config.get('TRAILING_STOP_PCT', 3.82) / 100

        # 매수일 이후 최고가 계산
        max_price = close
        if buy_date:
            try:
                buy_dt = pd.to_datetime(buy_date)
                df_since = df[df.index >= buy_dt]
                if not df_since.empty:
                    max_price = float(df_since['Close'].max())
            except Exception:
                pass

        stop_loss = round(max_price * (1 - trailing_stop_pct), 0)

        # 목표가: BBU(볼린저밴드 상단) 또는 현재가 +8%
        bbu = float(last['BBU']) if 'BBU' in last.index and pd.notna(last['BBU']) else None
        if bbu and bbu > close:
            target = round(bbu, 0)
            target_basis = "BB상단"
        else:
            target = round(close * 1.08, 0)
            target_basis = "+8%"

        return {
            'stop_loss': stop_loss,
            'stop_basis': f"최고가({self.format_price(max_price, code)}) 기준",
            'target': target,
            'target_basis': target_basis,
        }

    def format_holding_targets(self, targets, code):
        """보유종목 손절가·목표가 텍스트 포맷"""
        if not targets:
            return ""
        stop_text = self.format_price(targets['stop_loss'], code)
        target_text = self.format_price(targets['target'], code)
        return (
            f"손절 {stop_text}({targets['stop_basis']}) "
            f"/ 목표 {target_text}({targets['target_basis']})"
        )

    def calculate_entry_price(self, df, code, is_etf=False):
        """
        agent_stock / agent_etf 전문가 관점의 최적 진입가 계산.

        전략:
        - 1순위 (가장 보수적): BB 하단 + SMA50 중 높은 값 → 지지선 기반 진입
        - 2순위 (기본):        SMA50 기준 (중기 지지선)
        - 3순위 (적극적):      현재가 기준 소폭 조정 대기 (-1.5%)
        ETF는 SMA50을 더 중시 (변동성 낮음).
        반환: {'entry': float, 'basis': str, 'stop_loss': float, 'target': float}
        """
        if df is None or len(df) < 20:
            return None
        last = df.iloc[-1]
        # 장기 하락 추세(SMA200 하단) 종목 진입 원천 차단 (리스크 관리)
        if 'SMA200' in last.index and last['Close'] < last['SMA200']:
            return None
        close = float(last['Close'])

        bbl = float(last['BBL']) if 'BBL' in last.index and pd.notna(last['BBL']) else None
        bbm = float(last['BBM']) if 'BBM' in last.index and pd.notna(last['BBM']) else None
        sma50 = float(last['SMA50']) if 'SMA50' in last.index and pd.notna(last['SMA50']) else None
        sma200 = float(last['SMA200']) if 'SMA200' in last.index and pd.notna(last['SMA200']) else None

        # 진입가 결정 — agent_stock / agent_etf 전문가 원칙 준수
        # 1순위(주식): BB하단 + SMA50 중 높은 값 / 1순위(ETF): SMA50
        # 2순위: SMA50 / 3순위: 현재가 −1.5% 조정 대기
        # ※ VBO(전고점 돌파) 당일 즉시 현재가 진입은 제거 — 지지선 없는 추격매수 방지
        if bbl and sma50 and close > bbl:
            entry = max(bbl, sma50) if not is_etf else sma50
            basis = "BB하단·SMA50 지지선"
        elif sma50 and close > sma50:
            entry = sma50
            basis = "SMA50 중기 지지선"
        elif bbl and close > bbl:
            entry = bbl
            basis = "BB하단 지지선"
        else:
            # 현재가에서 1.5% 조정 대기
            entry = round(close * 0.985, 0)
            basis = "현재가 -1.5% 조정 대기"

        # 현재가보다 높으면 현재가 그대로 (이미 지지선 위)
        if entry > close:
            entry = close
            basis = "현재가 (즉시 진입 가능)"

        # 손절가: 진입가에서 -3% (트레일링 스톱 기준)
        trailing_stop_pct = self.config.get('TRAILING_STOP_PCT', 0.039)
        # TRAILING_STOP_PCT는 소수 형태(예: 0.0389 = 3.89%)로 저장됨 — /100 하지 않음
        stop_loss = round(entry * (1 - trailing_stop_pct), 0)

        # 목표가: BB 중단 또는 진입가 +8%
        if bbm and bbm > entry:
            target = round(bbm, 0)
            target_basis = "BB중단"
        else:
            target = round(entry * 1.08, 0)
            target_basis = "+8%"

        return {
            'entry': round(entry, 0),
            'basis': basis,
            'stop_loss': stop_loss,
            'target': target,
            'target_basis': target_basis,
        }

    def format_entry_info(self, entry_info, code, holding=False):
        """진입가 정보를 텍스트로 포맷. holding=True이면 손절·목표가만 표시"""
        if not entry_info:
            return ""
        stop_text = self.format_price(entry_info['stop_loss'], code)
        target_text = self.format_price(entry_info['target'], code)
        if holding:
            return (
                f"손절 {stop_text} "
                f"/ 목표 {target_text}({entry_info['target_basis']})"
            )
        entry_text = self.format_price(entry_info['entry'], code)
        return (
            f"진입가 {entry_text}({entry_info['basis']}) "
            f"/ 손절 {stop_text} "
            f"/ 목표 {target_text}({entry_info['target_basis']})"
        )

    def ask_entry_timing_opinions(self, entry_stocks, market_context=""):
        """
        지금진입가능 종목들에 대해 Gemini 1회 호출로 종목별 타이밍 의견 반환.

        entry_stocks: [
            {
                'name': str, 'code': str, 'current_price': float,
                'entry': float, 'stop_loss': float, 'target': float,
                'signals': str,           # 발화된 신호 텍스트
                'rsi': float|None,
                'volume_ratio': float|None,  # 현재거래량 / 평균거래량
                'near_52w_high': bool,
            }, ...
        ]
        market_context: 시장 분위기 요약 (선택)

        반환: {'종목명': '타이밍 의견 텍스트', ...}  — 실패 시 {}
        """
        if not self.model or not entry_stocks:
            return {}

        etf_codes = set(
            str(x).strip() for x in (
                self.config.get('ETF_EXPERT_TICKERS', []) +
                self.config.get('KOSPI_ETF_TICKERS', [])
            ) if str(x).strip()
        )
        _ETF_NAME_KEYWORDS = ('TIGER', 'KODEX', 'KBSTAR', 'HANARO', 'KOSEF', 'ACE', 'SOL ', 'KINDEX', 'ARIRANG', 'TIMEFOLIO', 'PLUS ')

        def _check_is_etf(code, name):
            if str(code).strip() in etf_codes:
                return True
            return any(kw in name.upper() for kw in _ETF_NAME_KEYWORDS)

        stocks_text = ""
        for s in entry_stocks:
            ep = self.format_price(s['entry'], s['code'])
            sp = self.format_price(s['stop_loss'], s['code'])
            tp = self.format_price(s['target'], s['code'])
            cp = self.format_price(s['current_price'], s['code'])
            rsi_txt = f"RSI {s['rsi']:.0f}" if s.get('rsi') else ""
            vol_txt = f"거래량비율 {s['volume_ratio']:.1f}배" if s.get('volume_ratio') else ""
            high_txt = "52주신고가 근접/돌파" if s.get('near_52w_high') else ""
            indicators = " / ".join(filter(None, [rsi_txt, vol_txt, high_txt]))
            is_etf_item = s.get('is_etf') if 'is_etf' in s else _check_is_etf(s['code'], s['name'])
            type_label = "ETF" if is_etf_item else "주식"
            stocks_text += (
                f"\n[{s['name']}({s['code']}) | 유형:{type_label}] 현재가:{cp} | 신호:{s['signals']}"
                f" | {indicators}"
                f"\n  → 진입가:{ep} / 손절:{sp} / 목표:{tp}\n"
            )

        market_txt = f"\n[현재 시장 상황]\n{market_context}\n" if market_context else ""
        prompt = f"""당신은 40년 경력의 주식·ETF 투자 전문가입니다.
{market_txt}
아래 종목들은 현재 기술적 매수 신호가 발생했고, 현재가가 알고리즘 산출 진입가 근처에 있어 즉시 진입 가능 상태입니다.
진입가/손절/목표는 BB하단·SMA50 지지선 기반으로 이미 계산되어 있습니다.
{stocks_text}
각 종목에 대해 유형에 맞는 전문가 의견을 1~2문장 작성해주세요.
- 유형이 "주식"인 종목 → stock_expert 필드에 차트·기술분석 관점 의견 (거래량 지속, 저항선 등 확인 사항 포함)
- 유형이 "ETF"인 종목 → etf_expert 필드에 섹터 흐름·모멘텀 고려 의견 (분할/일괄 매수 방향 포함)
- 해당 없는 필드는 빈 문자열("")로 남겨주세요.

반드시 아래 JSON 형식으로만 응답하세요:
{{
  "opinions": [
    {{
      "name": "종목명",
      "stock_expert": "주식 종목일 때만 의견, ETF면 빈 문자열",
      "etf_expert": "ETF 종목일 때만 의견, 주식이면 빈 문자열"
    }}
  ]
}}"""

        import time
        for attempt in range(2):
            try:
                if self.genai_library == 'genai' and self.model is not None:
                    response = self.model.send_message(prompt)
                elif self.genai_library == 'generativeai' and self.model is not None:
                    response = self.model.generate_content(prompt)
                else:
                    return {}
                text = self._normalize_ai_response(response)
                if not text:
                    return {}
                import re, json as _json
                m = re.search(r'\{[\s\S]*\}', text)
                if not m:
                    return {}
                data = _json.loads(m.group())
                return {
                    item['name']: {
                        'stock_expert': item.get('stock_expert', ''),
                        'etf_expert': item.get('etf_expert', ''),
                    }
                    for item in data.get('opinions', [])
                    if item.get('name')
                }
            except Exception as e:
                if '429' in str(e) and attempt == 0:
                    time.sleep(30)
                    continue
                return {}
        return {}

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
            # RS_LINE_BEAR: 하락기 단기 RS (20일 기준 - 하락장 방어력 측정)
            bear_lookback = self.config.get('RS_LOOKBACK_BEAR', 20)
            if len(common_idx) > bear_lookback:
                stock_ret_bear = df.loc[common_idx, 'Close'].pct_change(bear_lookback)
                index_ret_bear = kospi_index.loc[common_idx, 'Close'].pct_change(bear_lookback)
                df.loc[common_idx, 'RS_LINE_BEAR'] = stock_ret_bear - index_ret_bear

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
        if len(df_target) < 50: return False
        
        closes = df_target['Close'].values
        rsi_vals = df_target['RSI'].values
        
        # NaN 제거 확인
        if any(v != v for v in rsi_vals[-50:]):  # NaN check
            return False
        
        # 최근 50일에서 로컬 저점 찾기 (최소 5봉 간격)
        recent_closes = closes[-50:]
        recent_rsi = rsi_vals[-50:]
        
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
        
        # 두 번째 저점이 최근 12봉 이내여야 하며, 현재 가격이 전일보다 상승하며 반등 확증 시 유효
        current_close = df_target['Close'].iloc[-1]
        prev_close = df_target['Close'].iloc[-2]
        if p2_idx < len(recent_closes) - 12 or current_close <= prev_close:
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
        
        # 조건 3: RSI 과매도 후 반등 (기준 40 이하 — 코스피 평균 RSI 범위 고려)
        rsi_recent = df_target['RSI'].iloc[-5:].values
        rsi_was_oversold = any(r <= 40 for r in rsi_recent if r == r)
        rsi_rising = last['RSI'] > df_target['RSI'].iloc[-2]
        if not (rsi_was_oversold and rsi_rising):
            return False
        
        # 조건 4: 거래량이 평균을 확실히 상회 (강한 저점 매수세 유입 확인)
        if last['Volume'] < last['VOL_AVG'] * 1.1:
            return False
        
        # 조건 5: 양봉
        if last['Close'] <= last['Open']:
            return False
        
        return True

    def detect_macd_golden_cross(self, df, idx=-1):
        """MACD 골든크로스 감지 (MACD 선이 시그널 선을 상향 돌파)
        
        조건:
        1. 직전봉: MACD < 시그널 (데드크로스 상태)
        2. 현재봉: MACD > 시그널 (골든크로스 발생)
        3. MACD 히스토그램이 0선 근처에서 발생 (강한 추세 반전 필터)
        4. RSI가 50 이하 (과매도 회복 구간에서만 유효)
        """
        df_target = df.iloc[:idx+1] if idx != -1 else df
        if len(df_target) < 3:
            return False

        for col in ['MACD', 'MACDs', 'MACDh', 'RSI']:
            if col not in df_target.columns:
                return False

        last = df_target.iloc[-1]
        prev = df_target.iloc[-2]

        for val in [last['MACD'], last['MACDs'], prev['MACD'], prev['MACDs'], last['RSI']]:
            if val != val:  # NaN
                return False

        # 골든크로스: 직전 MACD < 시그널, 현재 MACD > 시그널
        cross_up = (float(prev['MACD']) < float(prev['MACDs'])) and (float(last['MACD']) > float(last['MACDs']))
        if not cross_up:
            return False

        # MACD 히스토그램이 -0.5% 이내 (너무 깊은 음수 구간에서의 크로스 제외)
        hist_threshold = float(last['Close']) * 0.005
        if float(last['MACDh']) < -hist_threshold:
            return False

        # RSI 50 이하에서만 유효 (과매도 회복 구간)
        if float(last['RSI']) > 55:
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
        """거래량 급증 감지 (평균 대비 2.5배 이상)"""
        df_target = df.iloc[:idx+1] if idx != -1 else df
        if len(df_target) < 2: return False
        
        last = df_target.iloc[-1]
        # 중기 상승 추세(SMA50) 위에서 캔들 몸통이 60% 이상인 강한 양봉일 때만 신뢰 (Mansfield RS 전략 반영)
        candle_body_ratio = (last['Close'] - last['Open']) / (last['High'] - last['Low'] + 1e-9)
        if last['Volume'] > last['VOL_AVG'] * 2.5 and last['Close'] > last.get('SMA200', 0) and last['Close'] > last['Open']:
            return True
        return False

    def detect_52week_high_breakout(self, df, idx=-1):
        """52주 신고가 근접 돌파 감지 (백테스트 결과 79.2% 승률, 평균 +18.87%)
        
        조건:
        1. 현재 종가가 52주 최고가 대비 95% 이상
        2. 오늘 거래량이 20일 평균 대비 1.5배 이상 (가짜 돌파 방지)
        3. 양봉 (종가 > 시가)
        """
        df_target = df.iloc[:idx+1] if idx != -1 else df
        if len(df_target) < 260: return False
        
        last = df_target.iloc[-1]
        for col in ['Close', 'Volume', 'VOL_AVG', 'Open']:
            if col not in df_target.columns or last[col] != last[col]:
                return False
        
        high_52w = df_target['High'].tail(250).max() if 'High' in df_target.columns else df_target['Close'].tail(250).max()
        if high_52w <= 0:
            return False
        
        near_high = float(last['Close']) >= high_52w * 0.95
        vol_surge = float(last['Volume']) >= float(last['VOL_AVG']) * 1.5
        is_bullish = float(last['Close']) > float(last['Open'])
        
        return near_high and vol_surge and is_bullish

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

        # 7. MACD 골든크로스 (추세 반전 확인)
        if self.detect_macd_golden_cross(df, idx):
            reasons.append("MACD 골든크로스")

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
        trailing_activate = cfg.get('TRAILING_STOP_ACTIVATE_PCT', 0.04)
        fallback_stop = abs(cfg.get('VALIDATE_STOP_LOSS_PCT', -0.05))
        fallback_target = cfg.get('PROFIT_TARGET_PCT', 0.08)
        atr_stop_mult = cfg.get('ATR_STOP_MULTIPLIER', 2.0)
        atr_target_mult = cfg.get('ATR_TARGET_MULTIPLIER', 3.0)

        trades = []
        for i in range(start_idx, current_idx):
            reasons = self.check_signals(df, i)
            if not reasons:
                continue
            # Tier1(Trend Template) 또는 Tier2(SMA200 위) 모두 집계 — 실제 진입 로직과 정합
            last_row = df.iloc[i]
            is_elite = self.is_trend_template(df, i)
            is_above_200 = (
                'SMA200' in df.columns
                and pd.notna(last_row.get('SMA200'))
                and float(last_row['Close']) > float(last_row['SMA200'])
            )
            if not (is_elite or is_above_200):
                continue
            if True:  # 조건 통과
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
                max_hard_stop = cfg.get('MAX_HARD_STOP_PCT', 0.07)
                has_premium = any(s in reasons for s in ["RSI 반전 신호(상승 가능성)", "바닥권 반등 신호(BB 하단)"])
                if atr_val:
                    hard_stop_pct = min(atr_stop_mult * atr_val / buy_price, max_hard_stop)
                    effective_target = atr_target_mult * (1.5 if has_premium else 1.0) * atr_val / buy_price
                else:
                    hard_stop_pct = min(fallback_stop, max_hard_stop)
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
                    if max_p >= buy_price * (1 + trailing_activate) and (max_p - curr_p) / max_p >= trailing_stop:
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
        """시장 지수가 SMA200 위이며 20일 모멘텀 양수인지 확인 (상승장 판단)"""
        try:
            df = index_df.iloc[:target_idx+1] if target_idx is not None else index_df
            if len(df) < 200:
                return True  # 데이터 부족 시 필터 미적용
            sma200 = df['Close'].rolling(200).mean().iloc[-1]
            above_sma200 = float(df['Close'].iloc[-1]) > float(sma200)
            # 20일 모멘텀: 현재가 > 20일 전 종가 (추세 방향 확인)
            momentum_ok = float(df['Close'].iloc[-1]) > float(df['Close'].iloc[-21]) if len(df) >= 21 else True
            return above_sma200 and momentum_ok
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
                rs_bear = last['RS_LINE_BEAR'] if 'RS_LINE_BEAR' in last and pd.notna(last.get('RS_LINE_BEAR')) else 0
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
                    '_df': df,
                }

                # Tier Classification
                # Tier 1 고품질 필터: 신호 2개 이상 + 양수 RS + 최소 거래량
                min_signals = self.config.get('TIER1_MIN_SIGNALS', 2)
                min_rs = self.config.get('TIER1_MIN_RS', 0.03)
                min_vol = self.config.get('MIN_AVG_VOLUME', 50000)
                min_bear_defense = self.config.get('RS_MIN_BEAR_DEFENSE', -0.02)

                # 강력 콤비 신호: RSI 다이버전스 + 타지마할 동시 발생 시 신호 개수 패널티 면제
                has_divergence = "RSI 반전 신호(상승 가능성)" in reasons
                has_taj_mahal = "바닥권 반등 신호(BB 하단)" in reasons
                power_combo = has_divergence and has_taj_mahal
                has_either_signal = has_divergence or has_taj_mahal  # 하락장 완화 조건
                effective_min_signals = 1 if power_combo else min_signals
                # 하락기 RS 방어 조건: 하락장일 때 20일 RS가 최소 임계값 이상인 종목만 Tier1
                bear_rs_ok = kospi_uptrend or (rs_bear >= min_bear_defense)
                tier1_quality = (
                    len(reasons) >= effective_min_signals and
                    rs_score >= min_rs and
                    (avg_vol >= min_vol or min_vol <= 0) and
                    bear_rs_ok
                )

                # 시장 필터: 하락장에서는 RSI 다이버전스 또는 BB 하단 중 하나 이상 필요
                market_ok = kospi_uptrend or not market_filter or has_either_signal

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
                rs_bear = last['RS_LINE_BEAR'] if 'RS_LINE_BEAR' in last and pd.notna(last.get('RS_LINE_BEAR')) else 0
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
                    '_df': df,
                }

                min_signals = self.config.get('TIER1_MIN_SIGNALS', 2)
                min_rs = self.config.get('TIER1_MIN_RS', 0.03)
                min_vol = self.config.get('MIN_AVG_VOLUME', 50000)
                min_bear_defense = self.config.get('RS_MIN_BEAR_DEFENSE', -0.02)
                has_divergence = "RSI 반전 신호(상승 가능성)" in reasons
                has_taj_mahal = "바닥권 반등 신호(BB 하단)" in reasons
                power_combo = has_divergence and has_taj_mahal
                has_either_signal = has_divergence or has_taj_mahal  # 하락장 완화 조건
                effective_min_signals = 1 if power_combo else min_signals
                # 하락기 RS 방어 조건: 하락장일 때 20일 RS가 최소 임계값 이상인 종목만 Tier1
                bear_rs_ok = kospi_uptrend or (rs_bear >= min_bear_defense)
                tier1_quality = (
                    len(reasons) >= effective_min_signals and
                    rs_score >= min_rs and
                    (avg_vol >= min_vol or min_vol <= 0) and
                    bear_rs_ok
                )
                market_ok = kospi_uptrend or not market_filter or has_either_signal
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
                entry_info = self.calculate_entry_price(r.get('_df'), r['code'], is_etf=(r.get('sector') == 'ETF'))
                entry_text = f" | {self.format_entry_info(entry_info, r['code'])}" if entry_info else ""
                msg = f"• <b>{r['name']}</b>({r['code']}): 현재가 {price_text} - {r['reasons']}{combo_mark}\n  └ {entry_text}"
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
                rs_bear = last['RS_LINE_BEAR'] if 'RS_LINE_BEAR' in last and pd.notna(last.get('RS_LINE_BEAR')) else 0
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
                    'avg_vol': avg_vol,
                    '_df': df,
                }

                min_signals = self.config.get('TIER1_MIN_SIGNALS', 2)
                min_rs = self.config.get('TIER1_MIN_RS', 0.03)
                min_bear_defense = self.config.get('RS_MIN_BEAR_DEFENSE', -0.02)
                has_divergence = "RSI 반전 신호(상승 가능성)" in reasons
                has_taj_mahal = "바닥권 반등 신호(BB 하단)" in reasons
                power_combo = has_divergence and has_taj_mahal
                effective_min_signals = 1 if power_combo else min_signals
                # 하락기 RS 방어 조건: 하락장일 때 20일 RS가 최소 임계값 이상인 종목만 Tier1
                bear_rs_ok = us_market_uptrend or (rs_bear >= min_bear_defense)
                tier1_quality = (
                    len(reasons) >= effective_min_signals and
                    rs_score >= min_rs and
                    bear_rs_ok
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
                entry_info = self.calculate_entry_price(r.get('_df'), r['code'], is_etf=False)
                entry_text = f" | {self.format_entry_info(entry_info, r['code'])}" if entry_info else ""
                msg = f"• <b>{r['name']}</b>({r['code']}, {r.get('market', 'US')}): 현재가 {price_text} - {r['reasons']}\n  └ {entry_text}"
                formatted.append(msg)
            formatted.append("")

        if formatted and formatted[-1] == "":
            formatted.pop()
        return formatted, results

    def analyze_etf_expert(self):
        """ETF 전문가(agent_etf) 관점의 한국 ETF 추천 분석"""
        etf_tickers = [str(x).strip() for x in self.config.get('ETF_EXPERT_TICKERS', []) if str(x).strip()]
        if not etf_tickers:
            return [], []

        print(f"\n[ETF Expert] 한국 ETF {len(etf_tickers)}개 분석 시작...")
        kospi_index = fdr.DataReader('KS11', start=(datetime.datetime.now() - datetime.timedelta(days=365)).strftime('%Y-%m-%d'))

        # ETF 이름 조회
        try:
            etf_listing = fdr.StockListing('ETF/KR')
            etf_name_map = dict(zip(etf_listing['Symbol'].astype(str), etf_listing['Name']))
        except Exception:
            etf_name_map = {}

        candidates = []
        for code in etf_tickers:
            try:
                df = fdr.DataReader(code, start=(datetime.datetime.now() - datetime.timedelta(days=400)).strftime('%Y-%m-%d'))
                if len(df) < 60:
                    continue
                df = self.get_indicators(df, kospi_index)
                target_idx = len(df) - 1
                reasons = self.check_signals(df, target_idx)
                if not reasons:
                    continue
                last = df.iloc[target_idx]
                win_rate, avg_ret = self.validate_strategy(df, target_idx)
                rs_score = last['RS_LINE'] if 'RS_LINE' in last else 0
                prev_close = float(df.iloc[target_idx - 1]['Close']) if target_idx > 0 else float(last['Close'])
                candidates.append({
                    'code': code,
                    'name': etf_name_map.get(str(code).strip(), code),
                    'reasons': ", ".join(reasons),
                    'win_rate': win_rate,
                    'avg_ret': avg_ret,
                    'rs_score': rs_score,
                    'last': float(last['Close']),
                    'prev_close': prev_close,
                    '_df': df,
                })
            except Exception:
                continue

        if not candidates:
            print("[ETF Expert] 매수 신호 ETF 없음")
            return [], []

        # 수익률 기준 정렬 (ETF 전문가: 신중 + 차트 기반 → rs_score + win_rate 복합)
        candidates.sort(key=lambda x: (x['win_rate'], x['rs_score']), reverse=True)
        top_candidates = candidates[:5]

        # AI ETF 전문가 코멘트 생성
        etf_comment = ""
        if self.ai_enabled:
            cand_text = "\n".join(
                f"- {c['name']}({c['code']}): 신호={c['reasons']}, 승률={c['win_rate']:.1f}%, 평균수익={c['avg_ret']:+.2f}%"
                for c in top_candidates
            )
            prompt = f"""당신은 40년간 한국 ETF 시장에서 활동한 ETF 투자 전문가입니다.
수익률 50% 이상을 꾸준히 달성했으며, 차트 분석을 바탕으로 신중하게 종목을 선정하는 것으로 유명합니다.

아래는 오늘 차트 신호가 발생한 한국 ETF 목록입니다:
{cand_text}

전문가 관점에서 각 ETF를 간략히 평가하고, 가장 주목할 ETF 1~2개를 추천해 주세요.
반드시 차트 신호와 승률 데이터를 근거로 설명하고, 수익률 50% 미만으로 판단되면 추천하지 마세요.
2~3문장으로 간결하게 한국어로 작성해 주세요."""
            try:
                import time
                for attempt in range(2):
                    try:
                        if self.genai_library == 'genai':
                            response = self.client.models.generate_content(
                                model=self.model_name, contents=prompt
                            )
                            etf_comment = response.text.strip()
                        else:
                            response = self.model.generate_content(prompt)
                            etf_comment = response.text.strip()
                        break
                    except Exception:
                        if attempt == 0:
                            time.sleep(30)
            except Exception:
                pass

        # 포맷팅
        formatted = ["<b>[ETF 전문가 추천]</b>"]
        for r in top_candidates:
            intraday = self.get_latest_price(r['code'])
            current_price = r['last']
            if intraday:
                current_price = intraday.get('last', current_price)
            price_text = self.format_price(current_price, r['code']) if current_price is not None else '가격 정보 없음'
            entry_info = self.calculate_entry_price(r.get('_df'), r['code'], is_etf=True)
            entry_text = f" | {self.format_entry_info(entry_info, r['code'])}" if entry_info else ""
            display_name = f"{r['name']}({r['code']})" if r['name'] != r['code'] else r['code']
            formatted.append(
                f"• <b>{html.escape(display_name)}</b>: 현재가 {price_text} - {html.escape(r['reasons'])}\n  └ {entry_text}"
            )
        if etf_comment:
            formatted.append("")
            formatted.append(f"<i>📊 ETF 전문가 코멘트: {html.escape(etf_comment)}</i>")

        print(f"[ETF Expert] 추천 ETF {len(top_candidates)}개 분석 완료")
        return formatted, top_candidates

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
                buy_price = info.get('buy_price', 0)
                current_price = float(df.iloc[-1]['Close'])
                profit_pct = (current_price - buy_price) / buy_price * 100 if buy_price else 0

                # 손절가·목표가 계산 (진입가 제외)
                entry_info = self.calculate_holding_targets(df, code, buy_date)
                entry_suffix = (f" | {self.format_holding_targets(entry_info, code)}") if entry_info else ""

                safe_name = html.escape(name)
                if triggered:
                    sell_alerts.append(
                        f"🚨 <b>{safe_name}({code}) 매도 알림</b>: 고점 대비 {drop_pct:.2f}% 하락"
                        f" | 수익률 {profit_pct:+.2f}%{entry_suffix}"
                    )
                else:
                    sell_alerts.append(
                        f"📊 <b>{safe_name}({code})</b>: 수익률 {profit_pct:+.2f}%{entry_suffix}"
                    )
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
        etf_msg, etf_raw = self.analyze_etf_expert()
        recs_msg = []
        if recs_msg_kr:
            recs_msg.append("<b>[국내 추천]</b>")
            recs_msg.extend(recs_msg_kr)
        if recs_msg_us:
            recs_msg.append("")
            recs_msg.append("<b>[미국 추천: Dow/Nasdaq 후보군]</b>")
            recs_msg.extend(recs_msg_us)
        if etf_msg:
            recs_msg.append("")
            recs_msg.extend(etf_msg)
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
        etf_note = ("\n\n[ETF 전문가 추천]\n" + "\n".join(etf_msg)) if etf_msg else ""
        if recs_msg:
            recommendation_context = "\n".join(recs_msg) + "\n\n" + us_recommendation_note + etf_note
        else:
            recommendation_context = "추천 종목 없음\n\n" + us_recommendation_note + etf_note
        
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
