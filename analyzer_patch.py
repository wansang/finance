import json
import os
import datetime
import FinanceDataReader as fdr

def load_watchlist(self):
    if os.path.exists('watchlist.json'):
        with open('watchlist.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def get_market_sentiment(self):
    """코스피/코스닥 지수의 이평선 기반 시장 심리 분석 (상세 한글 설명 추가)"""
    try:
        today = datetime.datetime.now()
        start_date = (today - datetime.timedelta(days=100)).strftime('%Y-%m-%d')
        
        ks = fdr.DataReader('KS11', start=start_date)
        kq = fdr.DataReader('KQ11', start=start_date)
        
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
            return msg, status == "우호적", status

        ks_msg, ks_pos, ks_status = analyze_index(ks, "코스피")
        kq_msg, kq_pos, kq_status = analyze_index(kq, "코스닥")
        full_msg = "[국내 시장 상태 분석]\n" + ks_msg + "\n" + kq_msg
        return full_msg, (ks_pos or kq_pos)
    except Exception as e:
        return f"⚠️ 시장 분석 오류: {e}", False
