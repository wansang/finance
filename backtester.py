import FinanceDataReader as fdr
import pandas as pd
import datetime
from analyzer import StockAnalyzer
import time

class Backtester:
    def __init__(self):
        self.analyzer = StockAnalyzer()

    def run_backtest(self, days_ago=30):
        print(f"Starting {days_ago}-day backtest...")
        
        # 1. 30일 전 거래일 찾기 (코스피 지수 기준)
        ks11 = fdr.DataReader('KS11')
        target_date = ks11.index[-(days_ago + 1)]
        current_date = ks11.index[-1]
        
        print(f"Target Date (Buy): {target_date.date()}")
        print(f"Current Date (Sell): {current_date.date()}")
        
        # 2. 모든 코스피 종목 리스팅 (속도를 위해 상위 300개만 샘플링)
        stocks = fdr.StockListing('KOSPI')[:300]
        # 테스트를 위해 상위 200개 종목만 먼저 수행 (속도 문제)
        # 만약 전체를 원하시면[:200]을 제거하세요.
        # stocks = stocks.head(200) 
        
        results = []
        count = 0
        total = len(stocks)
        
        print(f"Analyzing {total} stocks for signals on {target_date.date()}...")
        
        for _, stock in stocks.iterrows():
            code = stock['Code']
            name = stock['Name']
            
            try:
                # 데이터 가져오기 (충분한 과거 데이터 포함)
                start_date = (target_date - datetime.timedelta(days=350)).strftime('%Y-%m-%d')
                df = fdr.DataReader(code, start=start_date)
                
                if len(df) < 50: continue
                
                # 지표 계산
                df = self.analyzer.get_indicators(df)
                
                # target_date 시점의 인덱스 찾기
                if target_date not in df.index:
                    # 해당 날짜에 데이터가 없으면 가장 가까운 이전 영업일 찾기
                    df_target_subset = df[df.index <= target_date]
                    if len(df_target_subset) == 0: continue
                    target_idx = len(df_target_subset) - 1
                    actual_buy_date = df_target_subset.index[-1]
                else:
                    target_idx = df.index.get_loc(target_date)
                    actual_buy_date = target_date
                
                # 신호 확인 및 엘리트 트렌드 템플릿 필터링
                reasons = self.analyzer.check_signals(df, target_idx)
                if reasons and self.analyzer.is_trend_template(df, target_idx):
                    buy_price = df.iloc[target_idx]['Close']
                    actual_buy_date = df.index[target_idx]
                    
                    # --- 트레일링 스톱 시뮬레이션 시작 ---
                    sell_price = df.iloc[-1]['Close'] # 기본값: 현재가
                    sell_date = df.index[-1]
                    max_price_since_buy = buy_price
                    exit_reason = "Max Hold (30d+)"
                    
                    # 구입 다음날부터 오늘까지 추적
                    for i in range(target_idx + 1, len(df)):
                        curr_row = df.iloc[i]
                        if curr_row['Close'] > max_price_since_buy:
                            max_price_since_buy = curr_row['Close']
                        
                        # 고점 대비 3% 하락했는지 확인
                        if (max_price_since_buy - curr_row['Close']) / max_price_since_buy >= 0.03:
                            sell_price = curr_row['Close']
                            sell_date = df.index[i]
                            exit_reason = "Trailing Stop (3%)"
                            break
                    # --- 트레일링 스톱 시뮬레이션 종료 ---
                    
                    ret = (sell_price - buy_price) / buy_price * 100
                    
                    results.append({
                        'Code': code,
                        'Name': name,
                        'Reasons': ", ".join(reasons),
                        'BuyDate': actual_buy_date.date(),
                        'BuyPrice': buy_price,
                        'SellDate': sell_date.date(),
                        'SellPrice': sell_price,
                        'Return(%)': ret,
                        'ExitReason': exit_reason
                    })
                
                count += 1
                if count % 100 == 0:
                    print(f"Progress: {count}/{total} stocks analyzed...")
                    
            except Exception as e:
                # print(f"Error analyzing {name}: {e}")
                continue
        
        return pd.DataFrame(results)

    def print_summary(self, df_results):
        if df_results.empty:
            print("\n[백테스트 결과] 조건에 맞는 종목이 없었습니다.")
            return
        
        print("\n" + "="*50)
        print("           [30일 백테스트 요약 결과]")
        print("="*50)
        print(f"총 추천 종목 수: {len(df_results)}개")
        print(f"평균 수익률: {df_results['Return(%)'].mean():.2f}%")
        print(f"최고 수익률: {df_results['Return(%)'].max():.2f}% ({df_results.loc[df_results['Return(%)'].idxmax(), 'Name']})")
        print(f"최저 수익률: {df_results['Return(%)'].min():.2f}% ({df_results.loc[df_results['Return(%)'].idxmin(), 'Name']})")
        print(f"승률(수익 발생): {(df_results['Return(%)'] > 0).sum() / len(df_results) * 100:.1f}%")
        print("-" * 50)
        
        # 상세 내역 (수익률 상위 10개)
        print("\n[상위 10개 종목 상세]")
        print(df_results.sort_values(by='Return(%)', ascending=False).head(10)[['Name', 'Reasons', 'Return(%)']].to_string(index=False))
        print("="*50)

if __name__ == "__main__":
    backtester = Backtester()
    results = backtester.run_backtest(days_ago=30)
    backtester.print_summary(results)
