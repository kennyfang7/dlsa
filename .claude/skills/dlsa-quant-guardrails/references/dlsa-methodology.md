# DLSA Paper Math — Equation-by-Equation Explainer

A reference walkthrough of the mathematics in **Guijarro-Ordonez, Pelger & Zanotti, "Deep Learning Statistical Arbitrage"** (arXiv:2106.04028) — every equation restated, then translated into plain language. Use this while implementing `factors/`, `signals/`, and `policy/` with any model.

# 0. The problem in one line

Statistical arbitrage has three parts: **(1)** build a long-short portfolio that isolates a mispricing, **(2)** statistically model how that mispricing moves through time, **(3)** turn the model into trades. Classical stat-arb makes a hand-picked parametric choice at every step. The paper's contribution is replacing steps 2–3 with neural networks trained *end-to-end on the trading objective itself*.

> **In plain terms:** old-school pairs trading says "GM and Ford should move together; when the gap stretches, bet it snaps back, sized by a formula I chose in advance." This paper says "let the data decide what a stretched gap looks like AND how to bet on it — judged only by trading profit."

# 1. Stage one — residuals from a factor model

The return of stock i is decomposed by a conditional factor model:

```
R_{t+1} = β_t F_{t+1} + ε_{t+1}
```

where for N stocks and K factors: R is the N-vector of returns over day t→t+1, β_t is the N×K matrix of factor exposures **known at t**, F is the K-vector of factor returns, and ε is the N-vector of **residuals** — the arbitrage portfolios.

> **In plain terms:** each stock's daily move = "the part explained by broad forces everyone is exposed to" + "this company's private wiggle." The private wiggle ε is what we trade: it has (approximately) no market exposure by construction, and economic logic says similar assets' private wiggles shouldn't wander far — the law of one price pulls them back.

The residual to a factor model is itself a **portfolio**: ε_i is the return of holding $1 of stock i hedged with −β_i dollars of the factor-mimicking portfolios. That's why the paper calls them *residual portfolios* — they are directly tradable.

## 1.1 PCA version

Estimate the covariance matrix of returns on a trailing window, take the top-K eigenvectors as loadings:

```
Σ̂ = (1/T) Σ_t (R_t − R̄)(R_t − R̄)'
β̂ = top-K eigenvectors of Σ̂
```

Residual: `ε_{t+1} = (I − β̂(β̂'β̂)⁻¹β̂') R_{t+1}` — returns minus their projection onto the factor space.

> **In plain terms:** PCA asks "what are the K strongest patterns of stocks moving together?" and subtracts them. The projection formula is just "remove the part of today's returns that lines up with those patterns."

⚠️ **Implementation trap (red-team finding 1.1):** the eigenvectors used for the residual at date t must come from a window ending *before* t's refit period. Eigenvectors fit through t "know" future co-movement → leaked residuals → inflated backtest.

## 1.2 IPCA version (the paper's stronger variant)

Instrumented PCA (Kelly–Pruitt–Su) makes exposures a function of firm characteristics:

```
β_{i,t} = Γ' z_{i,t}
```

so the return model is

```
r_{i,t+1} = z_{i,t}' Γ F_{t+1} + ε_{i,t+1}
```

with z_{i,t} an L-vector of characteristics known at t (size, book-to-market, momentum, … — rank-standardized cross-sectionally to (−0.5, 0.5) each day) and Γ an L×K matrix mapping characteristics to exposures.

> **In plain terms:** instead of estimating a separate, slowly-staling beta per stock, IPCA learns one reusable **rulebook** Γ: "a firm this big, this cheap, with this much momentum has this factor exposure." Each stock's beta then updates itself automatically as its characteristics change — and brand-new stocks get sensible betas on day one.

**Estimation — alternating least squares.** Neither Γ nor F is observed, but each is a regression given the other, so alternate until converged:

```
F̂_{t+1} = (Bt'Bt)⁻¹ Bt' R_{t+1},   Bt = Zt Γ̂       (per period: cross-sectional OLS)

Γ̂ = argmin_Γ Σ_t ‖R_{t+1} − Zt Γ F̂_{t+1}‖²          (one pooled regression, vec/kron trick)
```

with the identification convention Γ'Γ = I (Γ and F only appear as a product, so one of them must be pinned or "double Γ, halve F" drifts forever).

> **In plain terms:** step 1 asks "given the rulebook, what did each factor earn each day?" Step 2 asks "given what the factors earned, which characteristics best explain who earned them?" Ping-pong until the answers stop changing.

A verified reference implementation with these exact steps is in `ref_ipca.py` (Fable-window deliverables).

## 1.3 The cumulative residual window

Signals aren't extracted from a single day's ε but from the **path**. For each stock, accumulate residuals over a lookback window of L ≈ 30 days:

```
x^(i)_τ = Σ_{s=t−L+τ}^{t} ε_{i,s},   τ = 1, …, L
```

> **In plain terms:** x is the 30-day "price chart" of stock i's private wiggle — a little synthetic asset that starts at 0 and drifts as the mispricing builds or fades. Its *shape* (how stretched, how fast it's been snapping back, whether it's still trending) is the raw material for the signal.

# 2. Stage two — signal extraction

## 2.1 The classical benchmark: Ornstein–Uhlenbeck

Classical stat-arb assumes the cumulative residual is an OU process — continuous-time mean reversion:

```
dx_t = κ(μ − x_t) dt + σ dW_t
```

κ = speed of reversion, μ = long-run level, σ = noise. Discretized daily, this is exactly an AR(1) regression `x_{t+1} = a + b x_t + ξ_{t+1}`, with

```
κ = −ln(b)/Δt,   μ = a/(1−b),   σ_eq = σ_ξ / √(1−b²)
```

and the trading signal is the **s-score**:

```
s_t = (x_t − μ) / σ_eq
```

traded with threshold rules (open short when s > +s̄, close when it returns toward 0, etc.).

> **In plain terms:** OU says the wiggle behaves like a ball on a spring — the further it's pulled from center (μ), the harder it's yanked back, at speed κ. The s-score answers "how many of its *own* typical deviations is the ball from center right now?" — s = +2 means unusually stretched high, so short it and wait for the spring. The weakness: real mispricings aren't always springs. In crises they trend; around news they jump and *stay*. A model that can only see springs mis-trades everything else — that misspecification is precisely the gap the neural version exploits.

## 2.2 The learned filter: CNN + Transformer

The paper replaces the OU assumption with a flexible learned map from the whole window to a signal:

```
S^(i)_t = g_θ( x^(i)_{t−L+1:t} )
```

Architecture: **1-D convolutions** over the 30-day window (a bank of learned pattern filters — the data-driven replacement for "is it shaped like a spring?"), feeding a **single-layer transformer** whose self-attention re-weights which parts of the window matter and shares context, producing one number per stock per day.

> **In plain terms:** the CNN is a set of learned stencils slid along the 30-day chart — one might light up on "sharp drop then stabilization," another on "steady grind away from zero." Attention then decides which lit-up stencils, from which parts of the window, deserve weight *for making money* — e.g., learning that a stretch that happened 3 weeks ago matters less than one still widening yesterday. Crucially, θ is never trained to *forecast* anything; gradients flow in from the trading objective below, so the filters are selected purely for profitable decisions.

# 3. Stage three — the trading policy and its objective

A second network maps signals to portfolio weights, with **self-financing normalization**:

```
w̃_t = h_φ(S_t)
w_t = (w̃_t − w̄̃_t) / ‖w̃_t − w̄̃_t‖₁
```

demeaning makes the book dollar-neutral (longs = shorts, market exposure ≈ 0); dividing by the gross makes leverage constant at 1.

> **In plain terms:** subtracting the average score means every dollar long is funded by a dollar short — the market itself cancels out. Dividing by the total size fixes the amount of capital at risk, so the network can't "improve" its score by simply betting bigger. Both operations happen inside the network's computation so the optimizer feels how favoring one stock squeezes all the others.

The whole pipeline (θ and φ jointly) is trained by stochastic gradient ascent on the **risk-adjusted return of the strategy itself** over the training window:

```
max_{θ,φ}  [ E[w_t' ε_{t+1}] − c E[‖w_t − w_{t−1}‖₁] ] / √Var(w_t' ε_{t+1})
```

i.e. maximize the Sharpe ratio of the portfolio's daily return series, with transaction costs (cost rate c × turnover) subtracted **inside** the objective, subject to the constraints baked into the normalization.

> **In plain terms:** the network's report card is not "did you predict returns?" but "over the whole training period, how good was your profit per unit of risk, AFTER paying your trading bills?" Because the cost term charges for *changing* positions, the optimizer learns on its own to hold positions longer, trade smaller in marginal names, and ignore signals too weak to cover their own costs. This is why cost-aware training beats bolting a cost penalty onto the backtest afterwards: the *policy itself* changes, not just its measured performance.

**v1 implementation freeze (frozen params M1/M3, added 2026-07-12):** implement the objective as the M1 Sharpe of **net** daily returns — r^net_t = w_{t−1}' ε_t − c‖w_t − w_{t−1}‖₁, maximize mean(r^net)/std(r^net) — **not** the literal form above, whose denominator is the variance of gross w'ε with costs only in the numerator. The two differ (the turnover chain enters the variance in one and not the other), and having both documented meant two different optimizers depending on which page the implementer read. M3 pins net/net so the training objective, `BacktestResult.sharpe`, and the K2 monitor are literally one function: `dlsa/metrics.py::sharpe`.

**Training subtleties that are easy to get wrong** (all demonstrated working in `ref_policy_training.py`): the turnover term needs yesterday's weights *without* detaching them from the gradient graph (otherwise the optimizer never learns persistence); the Sharpe must be computed over contiguous windows of days, never shuffled samples (the days interact through the shared standard deviation and the turnover chain); validation must be a later, *embargoed* block (gap ≥ the 30-day input window, or early stopping peeks).

# 4. Putting the stages together

```
returns  →[Γ, β_t]→  ε_t  →[cumsum L=30]→  x_t  →[g_θ]→  S_t  →[h_φ]→  w_t  →[net Sharpe]→  gradients flow all the way back
```

Only the factor model is estimated separately (by least squares, walk-forward); everything from the residual window to the weights is one differentiable program trained on the trading objective.

# 5. Results, and what to actually expect

On daily US equities (CRSP, 1998–2016) the paper reports out-of-sample annual Sharpe around 4 **before frictions**, beating OU-threshold benchmarks and pure forecasting approaches, with performance robust across factor-model choices (IPCA residuals strongest). The authors' 2025 follow-up ("Attention Factors," ICAIF) jointly learns factors and policy and reports ~2.3 **net of costs** at institutional scale. Independent free-data replications scatter widely — including one reporting implausible double-digit Sharpe, best read as a leakage/overfitting cautionary tale rather than a target.

> **In plain terms:** with clean CRSP data, no trading costs, and thousands of names, the method prints beautiful numbers. Your build has free data, real costs, and hundreds of names — a realistic goal is a *modest, honest* net edge, and the difference between that and fiction is entirely in the data layer and the alignment discipline, not the network. That's why the leakage test suite and the PIT rules are first-class citizens of this project.
