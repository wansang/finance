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
        self.holdings_file = 'holdings.json'
        self.strategy_config_file = 'strategy_config.json'
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
            "BACKTEST_SAMPLE_SIZE": 200
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
                df = fdr.DataReader(symbol)
                last_row = df.iloc[-1]
                prev_row = df.iloc[-2]
                change = last_row['Close'] - prev_row['Close']
                pct_change = (change / prev_row['Close']) * 100
                emoji = "📈" if change > 0 else "📉"
                summary += f"{emoji} {name}: {last_row['Close']:.2f} ({pct_change:+.2f}%)\n"
            except Exception as e:
                summary += f"⚠️ {name}: 데이터 오류\n"
        return summary

    def load_watchlist(self):
        if os.path.exists('watchlist.json'):
            with open('watchlist.json', 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}

    def save_watchlist(self, watchlist):
        with open('watchlist.json', 'w', encoding='utf-8') as f:
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
        arrow = '🔺' if amount > 0 else ('🔽' if amount < 0 else '⏺')
        amount_text = f"{amount:+,.0f}{label}"
        percent_text = f"{percent:+.2f}%"
        return f"{arrow} 등락가 {amount_text}, 등락율 {percent_text}"

    def clean_watchlist(self):
        """watchlist 항목 중 1주일 경과 후 holdings에 없는 항목을 자동 삭제"""
        watchlist = self.load_watchlist()
        if not watchlist:
            return

        today = datetime.datetime.now().date()
        changed = False
        for code in list(watchlist.keys()):
            entry = watchlist[code]
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
                print(f"watchlist에서 {code}를 {days_passed}일 경과로 인해 자동 삭제했습니다.")

        if changed:
            self.save_watchlist(watchlist)

    def add_top_recommendation_to_watchlist(self, results):
        """Tier 1 추천 종목 중 최상위 1개를 watchlist에 자동 추가"""
        if not results or 1 not in results or len(results[1]) == 0:
            return None

        top_stock = results[1][0]
        if not top_stock.get('code'):
            return None

        code = top_stock['code']
        if code in self.holdings:
            return None

        watchlist = self.load_watchlist()
        if code in watchlist:
            return None

        stock_name = html.unescape(top_stock.get('name', code))
        watchlist[code] = {
            'name': stock_name,
            'add_date': datetime.datetime.now().strftime('%Y-%m-%d')
        }
        self.save_watchlist(watchlist)
        return code

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
- **중요**: 보유 종목과 추천 종목 정보를 명확히 구분해서 작성해줘. 각 섹션은 분리되어 있어야 하며, 제목을 지나치게 생략하지 말고 구분이 쉽게 유지되도록 해줘.
- **구조**:
  1. 현재 시장의 분위기를 한 문단으로 정리해줘.
  2. [보유 종목] 섹션을 만들어서, 각 종목에 대해 왜 매도/보유 판단을 했는지 설명해줘.
  3. [추천 종목] 섹션을 만들어서, 각 종목에 대해 왜 추천하는지, 왜 지금 매수 또는 매수를 보류해야 하는지 설명해줘.
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

        # Relative Strength vs KOSPI Index
        if kospi_index is not None:
            common_idx = df.index.intersection(kospi_index.index)
            if len(common_idx) > 20:
                stock_returns = df.loc[common_idx, 'Close'].pct_change(20)
                index_returns = kospi_index.loc[common_idx, 'Close'].pct_change(20)
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

        return df

    def detect_divergence(self, df, idx=-1):
        """RSI 상승 다이버전스 감지 (가격은 하락, RSI는 상승)"""
        if len(df[:idx if idx != -1 else len(df)]) < 20: return False
        
        # 기준 시점까지의 데이터
        df_target = df.iloc[:idx+1] if idx != -1 else df
        df_recent = df_target.tail(20)
        
        lows = df_recent['Close'].values
        rsi_vals = df_recent['RSI'].values
        
        if len(lows) < 20: return False
        
        # 최근 5일 vs 그 전 15일
        p1 = lows[:-5].min()
        p2 = lows[-5:].min()
        r1 = rsi_vals[:-5][lows[:-5].argmin()]
        r2 = rsi_vals[-5:][lows[-5:].argmin()]
        
        if p2 < p1 and r2 > r1:
            return True
        return False

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
        """타지마할 밴드 유사 로직 (BB 하단 지지 + RSI 반등)"""
        df_target = df.iloc[:idx+1] if idx != -1 else df
        if len(df_target) < 2: return False
        
        last = df_target.iloc[-1]
        prev = df_target.iloc[-2]
        
        # 가격이 BB 하단 부근에서 반등하고 RSI가 40 이상으로 올라올 때
        if prev['Close'] <= prev['BBL'] * 1.01 and last['Close'] > last['BBL']:
            if last['RSI'] > 40 and last['RSI'] > prev['RSI']:
                return True
        return False

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
        """거래량 급증 감지 (평균 대비 2배 이상)"""
        df_target = df.iloc[:idx+1] if idx != -1 else df
        if len(df_target) < 2: return False
        
        last = df_target.iloc[-1]
        if last['Volume'] > last['VOL_AVG'] * 2:
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

    def validate_strategy(self, df, current_idx):
        """특정 종목의 과거 6개월 승률 검증 (미니 백테스트)"""
        # current_idx 기준 과거 VALIDATE_LOOKBACK_DAYS 분석
        lookback = self.config.get('VALIDATE_LOOKBACK_DAYS', 120)
        start_idx = max(self.config.get('VALIDATE_MIN_HISTORY', 200), current_idx - lookback)
        max_hold = self.config.get('VALIDATE_MAX_HOLD_DAYS', 20)
        stop_loss_pct = self.config.get('VALIDATE_STOP_LOSS_PCT', -0.03)
        
        trades = []
        for i in range(start_idx, current_idx):
            reasons = self.check_signals(df, i)
            # 트렌드 템플릿도 맞아야 함
            if reasons and self.is_trend_template(df, i):
                buy_price = df.iloc[i]['Close']
                # 트레일링 스톱 시뮬레이션
                max_p = buy_price
                result = stop_loss_pct # 기본 손절
                for j in range(i + 1, min(i + max_hold + 1, current_idx + 1)):
                    curr_p = df.iloc[j]['Close']
                    if curr_p > max_p: max_p = curr_p
                    if (max_p - curr_p) / max_p >= abs(stop_loss_pct):
                        result = (curr_p - buy_price) / buy_price
                        break
                    if j == i + max_hold: # 타임컷
                        result = (curr_p - buy_price) / buy_price
                trades.append(result)
        
        if not trades: return 0, 0
        win_rate = len([t for t in trades if t > 0]) / len(trades) * 100
        avg_ret = sum(trades) / len(trades) * 100
        return win_rate, avg_ret

    def analyze_kospi(self, target_date=None):
        """코스피 전 종목 정밀 분석 (Tiered System)"""
        stocks = fdr.StockListing('KOSPI')
        kospi_index = fdr.DataReader('KS11', start=(datetime.datetime.now() - datetime.timedelta(days=365)).strftime('%Y-%m-%d'))
        
        results = {1: [], 2: [], 3: []}
        count = 0
        total = len(stocks)
        
        print(f"Starting Tiered Analysis for {total} stocks...")
        
        for _, stock in stocks.iterrows():
            code = stock['Code']
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
                    'prev_close': prev_close
                }

                # Tier Classification
                if is_elite and win_rate >= self.config.get('TIER1_WIN_RATE', 60):
                    results[1].append(stock_data)
                elif is_above_200 and win_rate >= self.config.get('TIER2_WIN_RATE', 50):
                    results[2].append(stock_data)
                elif win_rate >= 40:
                    results[3].append(stock_data)
                
                count += 1
                if count % 200 == 0: print(f"Analyzed {count}/{total} stocks...")
            except Exception:
                continue

        # 결과 포맷팅
        formatted_recs = []
        tier_names = {1: "🥇 지금 매수", 2: "🥈 신중히 매수", 3: "🥉 추가 확인 후 매수"}
        
        for t in [1, 2, 3]:
            if not results[t]: continue
            # RS_SCORE 기준 정렬
            results[t].sort(key=lambda x: x['rs_score'], reverse=True)
            
            formatted_recs.append(f"<b>{tier_names[t]}</b>")
            for r in results[t][:5]: # 각 등급별 상위 5개만 노출
                price_text = self.format_price(r['last'], r['code']) if r.get('last') is not None else '가격 정보 없음'
                change_text = self.format_price_change(r['last'], r.get('prev_close'), r['code']) if r.get('last') is not None and r.get('prev_close') is not None else ''
                msg = f"• <b>{r['name']}</b>({r['code']}): 현재가 {price_text} {change_text} - {r['reasons']}"
                formatted_recs.append(msg)
            formatted_recs.append("")
            
        if formatted_recs and formatted_recs[-1] == "":
            formatted_recs.pop()
        return formatted_recs, results

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
        self.clean_watchlist()

        # 1.데이터 수집
        us_summary = self.get_us_market_summary()
        sentiment_msg, is_positive = self.get_market_sentiment()
        recs_msg, recs_raw = self.analyze_kospi()
        sell_alerts = self.analyze_holdings()

        # 추천 종목 1위 자동 추가
        added_code = self.add_top_recommendation_to_watchlist(recs_raw)
        if added_code:
            print(f"추천 종목 최상위 {added_code}을(를) watchlist에 자동 추가했습니다.")
        else:
            if recs_raw and 1 in recs_raw and len(recs_raw[1]) == 0:
                print("오늘은 1등급 추천 종목이 없습니다. watchlist 자동 추가를 건너뜁니다.")
            else:
                print("추천 종목 최상위 1등급 종목이 없거나 이미 watchlist에 있는 항목이어서 자동 추가가 수행되지 않았습니다.")
        
        # 2. AI에게 전달할 데이터 정리
        market_context = us_summary + "\n" + sentiment_msg
        holding_context = "\n".join(sell_alerts) if sell_alerts else "매도 신호 없음"
        
        # 추천 종목을 'watch_data' 항목으로 전달
        recommendation_context = "\n".join(recs_msg) if recs_msg else "추천 종목 없음"
        
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
                    'AvgReturn': f"{s['avg_ret']:.1f}%"
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
