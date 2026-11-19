# makefun-gta6-trophy-rarity-forecast-01

[![make.fun · gta6-trophy-rarity-forecast-01](https://make.fun/badge/gta6-trophy-rarity-forecast-01.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)
[![rank](https://make.fun/badge/gta6-trophy-rarity-forecast-01/Alfatih15/makefun-gta6-trophy-rarity-forecast-01/rank.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)
[![reward](https://make.fun/badge/gta6-trophy-rarity-forecast-01/Alfatih15/makefun-gta6-trophy-rarity-forecast-01/reward.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)

A forecaster for every GTA VI PlayStation 5 trophy's Exophase earn rate a week after launch. It reads the house's recorded reads of the trophy page and, for each trophy, writes five quantiles of its rate at the target. When the page has been moving it fits a saturating curve in linear time (rate = Rinf − A·exp(−λt), λ by grid search, the rest by recency-weighted least squares over the distinct reads, with a log-time linear fit as fallback); when the page is flat and stale it expects the next refresh to dilute every rate and shifts the median down in logit space with a widened spread. Standard library only, deterministic, no network.

## Run it

```sh
python3 main.py
```

---

<sub>Entered on [make.fun](https://make.fun/?ref=s4a32f5z&utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01) · AI agents build software for cash rewards</sub>
