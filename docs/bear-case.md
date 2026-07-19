# 🐻 Bear Case — Prior Literature Against

> A fourth adversarial pass, aimed at the premise rather than the implementation. The Red-Team Architecture Review, Ops & Systems Review, and Pre-Code Audit all assumed the strategy class works and attacked the execution. This page asks the prior question: does the published academic literature, independent of anything in this repo, believe DLSA-style deep-learning stat-arb earns a real edge at all? Five distinct lines of attack, ordered by how directly they bind on this project's own numbers. Each section carries a **Mitigations** block drawn from 2021–2026 literature, and the page closes with a recommendation on where mitigation effort pays most.

---

## 1. The theoretical ceiling — Da, Nagel & Xiu, "The Statistical Limit of Arbitrage" (NBER w33070, 2024)

Stefan Nagel and Dacheng Xiu (Chicago Booth) argue that when alphas are weak and rare, estimation errors prevent arbitrageurs — even ones using optimal machine learning — from exploiting all true pricing errors. This is a statistical limit, not a friction like transaction costs or short-sale constraints.

**The numbers, empirically:** using 10,000+ US equities and a 27-factor model, most individual-stock alpha t-stats sit below 2.0, and only a tiny fraction exceed 3.0. Even an optimal ML-based *feasible* strategy caps out around Sharpe **0.7** — versus Sharpe **4.8** for a hypothetical investor with perfect knowledge of the true alphas.

**Bearing on this project:** DLSA's own frictionless headline is ~4 Sharpe (math explainer §5). Read against this ceiling, most of that number plausibly reflects what a finite-sample learner *cannot* actually capture — it is closer to the unattainable 4.8 than to the feasible 0.7. Frozen param **G1.2**'s net-of-cost acceptance band (0.5–2.0) mostly sits under this ceiling; the top of the band arguably doesn't, and a result landing there should raise the same suspicion K4 already encodes for gross Sharpe > 3.

### Mitigations — literature-backed (2021–2026)

- **Empirical-Bayes signal shrinkage — the paper's own remedy.** Da–Nagel–Xiu don't just diagnose; their optimal *feasible* arbitrage portfolio is constructed via empirical-Bayes shrinkage of estimated alphas. Add a shrinkage layer between the signal net and the policy net (`dlsa/signals/shrinkage.py`): pull each name's signal toward zero as a function of the estimated cross-sectional strength and rarity of alphas, so estimation error becomes smaller positions rather than confident wrong ones. *Note: shrinkage intensity is a frozen-param candidate — set once via CPCV (see §5 mitigations), never tuned per backtest; M4 discipline applies.*
- **Seed ensembles.** Estimation variance is the ceiling's entire mechanism, and averaging the signal net over 5–10 training seeds is the cheapest direct attack on it. GPU cost is trivial at this universe size (the CNN+transformer trains on a desktop GPU per the main page), and the model registry already versions the artifacts.
- **Selectivity over coverage.** Trade only the extreme tails of the signal distribution and abstain in the middle (the Krauss-lineage top-k censoring). Weak-and-rare alphas argue for concentrating capital where estimated signal strength is highest. *Note: this also eases the C6–C8 minimum-ticket constraint — fewer, larger positions is exactly what a small account needs anyway.*
- **Contested counterpoint worth knowing:** Kelly, Malamud & Zhou ("The Virtue of Complexity in Return Prediction," Journal of Finance 2024) argue that heavily over-parameterized models with ridge shrinkage improve out-of-sample prediction even with limited data — i.e., the ceiling may bind less for the right model class. This claim has drawn published pushback and is not settled; treat it as a reason to keep ridge/shrinkage knobs in the pipeline, not as a license to expect Sharpe above the ceiling.

---

## 2. The empirical companion — Avramov, Cheng & Metzker, "Machine Learning vs. Economic Restrictions" (Management Science, 2023)

Deep-learning return-prediction signals extract most of their profitability from difficult-to-arbitrage stocks and high-limits-to-arbitrage market states. Excluding microcaps, distressed stocks, or high-volatility episodes considerably attenuates profitability; performance deteriorates further under reasonable trading costs because of high turnover and extreme tangency-portfolio positions.

**Bearing on this project:** the PIT S&P 500 universe (frozen param U1) already excludes microcaps by construction — which is exactly the population this paper says the documented ML edge depends on. Applied to a large-cap-only universe, their result predicts substantial attenuation before a single overlay fires.

**Counterpoint (for balance):** this finding is contested. A later AFA-presented paper ("The Expected Returns on Machine-Learning Strategies") argues that value-weighting the portfolios and the sharp decline in trading costs over the past two decades still leave ML strategies significantly profitable — in stark contrast to Avramov et al.'s conclusion. The disagreement is live in the literature, not settled.

### Mitigations — literature-backed (2021–2026)

- **Learn portfolio weights under an economic net-of-cost objective.** Jensen, Kelly, Malamud & Pedersen, "Machine Learning and the Implementable Efficient Frontier" (Review of Financial Studies, 2026): cost-agnostic ML forecasts over-rely on fleeting small-scale characteristics, and the fix is learning weights *directly* with a trading-cost-aware objective — a generalized Gârleanu–Pedersen partial-adjustment ("aim portfolio") structure under fully nonlinear ML. Application here: give the policy net that structure explicitly (trade partway toward an aim portfolio at a rate set by the cost-vs-signal-decay tradeoff) instead of hoping SGD rediscovers it. Their code is public (`github.com/theisij/ml-and-the-implementable-efficient-frontier`). *Note: X1 already puts costs inside training — this adds the theoretically optimal* form*, not a new principle.*
- **Evaluate G1.2 as a frontier, not a point.** Report net Sharpe at two or three gross-exposure / vol-target levels. JKMP's core result is that implementability degrades with scale; a single-point backtest hides where on that curve this account sits.
- **Fleeting-signal diagnostic.** Add one monitoring metric: signal autocorrelation half-life vs. the turnover budget (X4). If the signal decays faster than the turnover cap can harvest, the edge is definitionally unimplementable for this account regardless of gross Sharpe — this is the practitioner's version of JKMP's "fleeting characteristics" finding.

---

## 3. The stat-arb decay record

Independent of machine learning, classical statistical arbitrage has a documented decline:

- Gatev, Goetzmann & Rouwenhorst's distance-based pairs trading earned strong average annualized returns over 1962–2002, but returns weakened later in their own sample.
- Do & Faff found simple pairs trading substantially less profitable after 2002, and often unprofitable after costs.
- Avellaneda & Lee's empirical study of stat-arb confirms profitability dropped after 2002–2003; Bookstaber (2006) already wrote that stat arb was "past its prime."
- Krauss et al.'s S&P 500 deep-learning/tree-ensemble stat-arb study (2016) — the direct methodological ancestor of DLSA's ensemble baselines — reported strong daily returns that were nevertheless **declining over time** within their own 1992–2015 sample.
- DLSA's own published sample ends in 2016.

**Crowding tail:** Khandani & Lo's analysis of the August 2007 "quant quake" shows how a crowded set of market-neutral strategies can deleverage together and inflict large, correlated losses that no single-strategy backtest anticipates — the loss arrives through what the *crowd* does, not what the market does. This project's crowding monitor (O3, O6) and regime overlay (O1) are walk-forward and monthly-refit; the critique is that correlated deleveraging events move faster than a monthly refit sees them, which is exactly why K1/K5 (drawdown halt, stale-book escalation) exist as a second line of defense rather than relying on the overlays alone.

### Mitigations — literature-backed (2021–2026)

- **Decay-calibrated live prior.** Falck, Rej & Thesmar ("Why and How Systematic Strategies Decay," Quantitative Finance, 2022) and McLean–Pontiff's 26%/58% haircuts give usable numbers: pre-register expected live Sharpe = backtest × (1 − haircut), and wire **G3.4's live-vs-backtest tripwire to the decayed prior**, not the raw backtest. Otherwise ordinary decay reads as malfunction (false alarm and an unnecessary pause), or the raw backtest quietly remains the bar (false comfort). *Adopted 2026-07-15 as frozen param V2 (h = 0.40); K2 and G3.4 amended.*
- **Validated crowding gauges for O6.** Upgrade the monitor's proxies to measures with literature behind them: days-to-cover as the cost of exiting crowded trades, short-interest-based arbitrage-capital tracking in the Hanson–Sunderam tradition, and residual-return-correlation crowding (Lou–Polk style). Lazo-Paz, Moneta & Chincarini ("Crowded Spaces and Anomalies," 2023) find crowding influences anomaly returns and is positively related to crash risk; "Not All Factors Crowd Equally" (arXiv 2512.11913, Dec 2025) models alpha decay factor-by-factor.
- **An orthogonal, less-crowded signal sleeve.** Price-based reversion is the crowded trade; text/news-embedding signals are differentiated and share infrastructure with the v2 news gate — one embedding pipeline can feed both a gate and a diversifying alpha sleeve.

---

## 4. Publication decay — McLean & Pontiff, "Does Academic Research Destroy Stock Return Predictability?" (Journal of Finance, 2016)

Studying 97 published return predictors: returns are **26% lower out-of-sample** and **58% lower post-publication**, with larger post-publication declines for predictors that had higher in-sample returns. The authors interpret this as investors learning about mispricing from academic publications and trading it away.

**Bearing on this project:** DLSA was published (2021, later Management Science), has a named follow-up ("Attention Factors," ICAIF 2025) reporting a lower net Sharpe (~2.3) at institutional scale, and multiple public replications exist. The predictor's own high in-sample return puts it, per this paper's own finding, in the cohort that decays *fastest* post-publication — and by 2026 the DLSA paper is several years past that publication date.

### Mitigations — literature-backed (2021–2026)

- **Combine many weak signals instead of betting on one published one.** Chen & Zimmermann's Open Source Asset Pricing (Critical Finance Review, 2022 — already this project's characteristics source) and Jensen, Kelly & Pedersen ("Is There a Replication Crisis in Finance?", Journal of Finance 2023) both show that broad, shrinkage-weighted combinations of characteristics decay far more gracefully post-publication than single headline factors. Application: a ridge-combined OSAP composite as **benchmark and fallback sleeve** — marginal cost is low because IPCA already ingests the identical characteristics panel.
- **Pre-registered publication haircut.** Same mechanism as the decay prior in §3 — one config value, one formula, cross-referenced so the two never drift apart. The haircut is set *before* Phase 3 starts and logged in 04, so it cannot be adjusted to excuse live underperformance after the fact.

---

## 5. Backtest overfitting — Bailey, Borwein, López de Prado & Zhu, "Pseudo-Mathematics and Financial Charlatanism" (Notices of the AMS, 2014) and the Deflated Sharpe Ratio

Selection bias combined with backtest overfitting systematically misleads investors into allocating to strategies that will lose money out-of-sample. The Deflated Sharpe Ratio exists specifically to correct a Sharpe estimate for the number of trials implicitly run to find it.

**Bearing on this project:** the DLSA paper is itself a comparison study — multiple factor models (PCA/IPCA/Fama-French) × multiple signal extractors × multiple objectives — reporting the winning combination. Frozen param **M4** (design holdout) defends against *this project's own* design-level overfitting, correctly per the Pre-Code Audit. It cannot retroactively repair whatever selection was already baked into choosing DLSA's published architecture as the one worth replicating in the first place.

**The replication record adds no comfort.** The only independent out-of-sample replication on a recent period (2016–2024, arXiv 2412.11432) reported Sharpe ratios **occasionally exceeding 10** — which its own authors flagged as likely model overfitting, highly specific market conditions, or insufficient transaction-cost/market-impact accounting. That paper was subsequently **withdrawn by its author (Jan 2025)**, citing a static-universe survivorship error — exactly the trap this project's PIT guardrails exist to prevent (documented on page 05 and attached there as a cautionary PDF). Net effect: there is currently **no credible independent evidence the edge survives past 2016** on real, cost-adjusted, survivorship-clean data.

### Mitigations — literature-backed (2021–2026)

- **CPCV for model selection; walk-forward for the final simulation.** Arian, Norouzi & Seco ("Backtest Overfitting in the Machine Learning Era," 2024) compared out-of-sample testing methods in a controlled synthetic environment and found Combinatorial Purged Cross-Validation markedly superior at mitigating overfitting — lower Probability of Backtest Overfitting, better Deflated Sharpe statistics — while walk-forward showed notable weakness at false-discovery prevention.
- **Automated trial registry → Deflated Sharpe at every gate.** `runs/` already logs every backtest. Hash each config, count distinct trials n, and have `make backtest` report the Deflated Sharpe Ratio (Bailey–López de Prado) alongside the raw one. This turns M4's pre-registration discipline from an honor system into a computed statistic.
- **Synthetic tail scenarios for overlay tuning.** Tail-GAN (Cont, Cucuringu, Xu & Zhang, Management Science 2025) generates multi-asset scenarios that preserve Value-at-Risk and Expected Shortfall for a user-chosen class of trading strategies. Test the overlays' false-negative rate on generated crises **nobody has seen** — the direct answer to M4's deepest problem, that the designer has already seen 2008/2020/2022 and tuned on them.
- **Vintage-stamped LLMs for news gate v2.** ChronoBERT/ChronoGPT (He, Lv, Manela & Wu, 2025) are trained only on text available at each point in time, with open fixed weights, and they measure the lookahead bias of anachronistic models in news-based return prediction as modest but real. If v2 ever backtests an embedding gate, standard FinBERT/Llama weights quietly leak post-period knowledge — a leakage class that lives in *model weights*, not the data lake, and is therefore **structurally invisible to test_lookahead_bias.py**. *Note: when v2 starts, this constraint belongs as a new rule in Artifact 2 (path-scoped to the news-gate module).*

---

## Synthesis — what this changes, and what it doesn't

This project's existing frozen parameters already price in most of the *operational* half of this critique: K4's suspicion threshold (Sharpe > 3 is a bug, not a result) is the practitioner's version of Da–Nagel–Xiu's ceiling; X1/X2 cost and borrow modeling is the practitioner's version of Avramov et al.'s cost-erosion finding; the crowding monitor and regime overlay are direct responses to the Khandani–Lo crowding literature; M4's design holdout is the practitioner's version of Bailey et al.'s overfitting correction.

What none of that can engineer away: the combination of a hard statistical ceiling (Sharpe ~0.7 feasible, per Da–Nagel–Xiu), two decades of documented stat-arb decay, a four-plus-year-old publication clock (McLean–Pontiff), and a withdrawn recent-period replication jointly predict that the realistic base-rate outcome for this specific architecture, traded now, is **net Sharpe near zero** — not the ~2.3 the 2025 institutional follow-up reports, and nowhere near the paper's own frictionless ~4.

**Practical implication for the phase gates (page 08):** G0.7 (the OU baseline, built and beaten) is the project's first empirical contact with this literature. If OU earns close to its numeric floor (~0.3) rather than comfortably clearing it, that is Do & Faff's post-2002 decay finding confirming itself on this project's own data lake, before a single dollar or week is spent on the neural signal/policy nets. G1.2's net Sharpe band should be read with its *upper* bound as suspicious, not just its lower bound as a pass/fail line — a result near 2.0 net deserves the same scrutiny K4 already gives to gross Sharpe > 3, given Da–Nagel–Xiu's feasible ceiling sits well below it.

Nothing here argues against building the system — the phased plan (page 08) is itself the correct falsification instrument, and the honest-gotchas section on the main architecture page already sets expectations at "a modest, real edge if everything is clean." This page exists so that a modest or negative result at Phase 0–1 is read as **the literature's base rate playing out**, not as a bug to keep tuning away — which is precisely the failure mode M4 was frozen to prevent.

---

## Sources

- Da, R., Nagel, S., & Xiu, D. (2024). *The Statistical Limit of Arbitrage.* NBER Working Paper 33070.
- Avramov, D., Cheng, S., & Metzker, L. (2023). *Machine Learning vs. Economic Restrictions: Evidence from Stock Return Predictability.* Management Science, 69(5), 2587–2619.
- *(Counterpoint) The Expected Returns on Machine-Learning Strategies* — AFA-presented working paper responding to Avramov et al.
- Gatev, E., Goetzmann, W., & Rouwenhorst, K. G. *Pairs Trading: Performance of a Relative-Value Arbitrage Rule.*
- Do, B., & Faff, R. *Does Simple Pairs Trading Still Work?*
- Avellaneda, M., & Lee, J. H. *Statistical Arbitrage in the U.S. Equities Market.*
- Krauss, C., Do, X. A., & Huck, N. (2017). *Deep neural networks, gradient-boosted trees, random forests: Statistical arbitrage on the S&P 500.* European Journal of Operational Research.
- Khandani, A., & Lo, A. W. (2011). *What Happened to the Quants in August 2007?* Journal of Financial Markets.
- McLean, R. D., & Pontiff, J. (2016). *Does Academic Research Destroy Stock Return Predictability?* Journal of Finance, 71(1), 5–32.
- Bailey, D. H., Borwein, J., López de Prado, M., & Zhu, Q. J. (2014). *Pseudo-Mathematics and Financial Charlatanism.* Notices of the AMS, 61(5), 458–471.
- Bailey, D. H., & López de Prado, M. (2014). *The Deflated Sharpe Ratio.* Journal of Portfolio Management, 40(5), 94–107.
- Long, W., & Xiao, V. (2024). *A Deep Learning Approach for Trading Factor Residuals.* arXiv:2412.11432 (v1 preprint; **withdrawn by author, Jan 2025**).
- Guijarro-Ordonez, J., Pelger, M., & Zanotti, G. (2021/2022). *Deep Learning Statistical Arbitrage.* Management Science.

**Mitigation sources (2021–2026):**

- Jensen, T. I., Kelly, B. T., Malamud, S., & Pedersen, L. H. (2026). *Machine Learning and the Implementable Efficient Frontier.* Review of Financial Studies.
- Kelly, B., Malamud, S., & Zhou, K. (2024). *The Virtue of Complexity in Return Prediction.* Journal of Finance. (Contested — cited as counterpoint only.)
- Jensen, T. I., Kelly, B. T., & Pedersen, L. H. (2023). *Is There a Replication Crisis in Finance?* Journal of Finance.
- Chen, A. Y., & Zimmermann, T. (2022). *Open Source Cross-Sectional Asset Pricing.* Critical Finance Review.
- Falck, A., Rej, A., & Thesmar, D. (2022). *Why and How Systematic Strategies Decay.* Quantitative Finance.
- Lazo-Paz, R., Moneta, F., & Chincarini, L. (2023). *Crowded Spaces and Anomalies.* Working paper.
- *Not All Factors Crowd Equally: Modeling, Measuring, and Trading on Alpha Decay.* arXiv:2512.11913 (2025).
- Hanson, S., & Sunderam, A. (2014). *The Growth and Limits of Arbitrage: Evidence from Short Interest.* Review of Financial Studies.
- Arian, H. R., Norouzi M., D., & Seco, L. A. (2024). *Backtest Overfitting in the Machine Learning Era: A Comparison of Out-of-Sample Testing Methods in a Synthetic Controlled Environment.*
- Cont, R., Cucuringu, M., Xu, R., & Zhang, C. (2025). *Tail-GAN: Learning to Simulate Tail Risk Scenarios.* Management Science.
- He, S., Lv, L., Manela, A., & Wu, J. (2025). *Chronologically Consistent Large Language Models.* arXiv:2502.21206.

---

## Recommendation — where mitigation effort pays most

> The corpus's own design philosophy (main page, §1) says DIY quant projects die of self-deception — leakage, survivorship, overfitting — not weak signals. So the highest-positive-effect mitigations are the ones that harden the project's *epistemics* at near-zero cost, ahead of the ones that might add alpha.

**Adoption status (2026-07-15):** the five "adopt now / schedule next" items below are **folded into the spec** as frozen params V1–V5, propagated across pages 01/02/03/04/07/08/09, Artifacts 1–2, and the Hardened Tests. The four "park" items are **pre-registered** as V6–V9 with named triggers on page 04. This section is now the record of *why the tiers were cut where they were*, not a to-do list.

**Offense adopted (2026-07-16):** the fifth pass turned this page's defense into an edge roadmap — 10 — Alpha & Net-Sharpe Roadmap. The mapping: **C9** ↔ §1's per-strategy feasible ceiling; **V6's shadow mechanism** ↔ §2's JKMP net-of-cost result; **O9** ↔ §2/§4's limits-to-arbitrage and crowding findings; **D7** ↔ §3/§5's publication decay and weight-borne leakage.

**Adopt now (Phase 0–1; near-free; no frozen-param or contract changes):**
1. **Trial registry + Deflated Sharpe at every gate** (§5) — the single highest-leverage item on this page. Every number this project will ever produce becomes more trustworthy at once; it converts the strongest standing critique — selection and overfitting — into a computed statistic.
2. **Decay-calibrated prior wired into G3.4** (§3/§4) — protects the most consequential live decision the system makes (pause vs. continue) from both failure modes.
3. **Seed ensembles for the signal net** (§1) — the cheapest real attack on estimation error, which is the mechanism behind the statistical ceiling itself.

**Schedule next (moderate lift; log as frozen-param candidates in 04 before implementing):**
1. **CPCV for hyperparameter/architecture selection** (§5) — the strongest evidence-backed validation upgrade available; leaves the one-code-path walk-forward simulation untouched.
2. **Empirical-Bayes shrinkage layer** (§1) — turns the bear case's flagship paper into a component, and pairs naturally with the ensembles.

**Park explicitly for Phase 2+ (write them down now so they aren't invented mid-drawdown):**
1. JKMP aim-portfolio structure + frontier-style G1.2 reporting (§2) — the largest *potential* net-Sharpe improvement on this page, but it touches the core policy net.
2. Tail-GAN overlay stress harness (§5) — belongs in Phase 2 alongside overlay tuning.
3. ChronoBERT/ChronoGPT embeddings (§5) — only if/when news gate v2 begins; at that point it becomes mandatory, not optional.
4. OSAP ridge-combo fallback sleeve (§4) and upgraded O6 crowding gauges (§3) — Phase 2–3 additions.

**If forced to pick one: the trial registry + Deflated Sharpe.** Every other item's evidence — including the evidence for or against adopting the rest of this list — flows through the project's backtest numbers. This is the only mitigation that upgrades the credibility of *all* of them simultaneously.
