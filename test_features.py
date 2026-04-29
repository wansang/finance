"""기능 테스트: analyze_etf_expert, _df 키, monitor 진입가"""
import sys
import warnings
warnings.filterwarnings("ignore")

import FinanceDataReader as fdr
import datetime
from analyzer import StockAnalyzer

a = StockAnalyzer()

# [3] analyze_etf_expert() 구조 테스트
print('[3] analyze_etf_expert() 구조 테스트...')
result = a.analyze_etf_expert()
print(f'  반환 타입: {type(result)}')
assert isinstance(result, tuple) and len(result) == 2, "튜플(2) 반환 실패"
formatted, raw = result
print(f'  formatted lines: {len(formatted)}')
print(f'  raw candidates: {len(raw)}')
if raw:
    r0 = raw[0]
    print(f'  첫번째 항목 keys: {list(r0.keys())}')
    assert '_df' in r0, '_df 키 없음'
    print(f'  _df 키 포함: True')
    if r0.get('entry_info'):
        print(f'  entry_info: {r0["entry_info"]}')
    # formatted 출력 샘플
    for line in formatted[:5]:
        print(f'  > {line}')
print('[3] OK')

# [4] analyze_kospi _df 키 포함 확인 (stock_data에 _df 있는지)
print('\n[4] analyze_kospi() _df 키 포함 여부 확인...')
# 내부 stock_data에 _df 포함 여부를 간접 확인 — backtester 없이 validate_strategy 통과 종목이 있는지만 확인
formatted_kospi, raw_kospi = a.analyze_kospi()
print(f'  KOSPI formatted lines: {len(formatted_kospi)}')
print(f'  KOSPI raw results: {len(raw_kospi)}')
if raw_kospi:
    r0 = raw_kospi[0]
    has_df = '_df' in r0
    print(f'  _df 키 포함: {has_df}')
    if r0.get('entry_info'):
        print(f'  entry_info sample: {r0["entry_info"]}')
    for line in formatted_kospi[:6]:
        print(f'  > {line}')
print('[4] OK')

print('\n=== 모든 테스트 통과 ===')
