# TODO

## High Priority
- [ ] Backtest realism: add transaction costs, slippage, and liquidity-based execution constraints.
- [ ] Walk-forward validation: split by time windows (train/validate/test) and run rolling evaluation.
- [ ] Market regime logic: separate rules for bull/sideways/bear phases.
- [ ] Position sizing: add volatility-based sizing (ATR/vol targeting), not just entry/exit.

## Risk Control
- [ ] Portfolio risk limits: max position size, sector concentration cap, daily loss limit (kill switch).
- [ ] Improve stop/exit policy: volatility-aware trailing stop and partial take-profit rules.

## Signal/Model Upgrade
- [ ] Factor expansion: volume trend, relative strength, and additional momentum quality filters.
- [ ] Recommendation scoring: expose weighted score breakdown in reports (trend/momentum/volume/risk).

## Reliability & Ops
- [ ] Data reliability metrics: log source usage, fallback rate, and request failure rate.
- [ ] Monitoring/alerts: notify when real-time data fails repeatedly or fallback ratio spikes.
- [ ] GitHub Actions maintenance: upgrade deprecated action versions and Python runtime.

