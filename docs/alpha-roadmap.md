# 🎯 10 — Alpha & Net-Sharpe Roadmap (v1)

> The fifth review pass — and the first one playing offense. The Red-Team, Ops, Pre-Code Audit, and Bear Case passes all made the project harder to fool; this page asks how to raise realized net Sharpe **within** that discipline. **Where this narrative page and 04 — Frozen Parameters disagree, the frozen parameters win** — this page is the map, that page is the territory.

**Adoption status (2026-07-16):** all four levers below are folded into the spec as **O9, C9, D7, and the amended V6 (gates G2.8, G3.7)** on page 04 and page 08, with propagation across pages 01/02/03/07/08/09, Artifacts 1–2, and the Hardened Tests (verification table on page 06). Only **D7 is active today**; everything else is dormant behind named triggers. **Phase-1 replication is untouched — this pass adds zero active behavior before G2.**

---

## The governing logic

The Da–Nagel–Xiu ceiling (Bear Case §1) is **per feasible strategy** and **gross of costs**. That framing dictates where edge can come from: not through the ceiling (a cleverer single model — every knob turned there inflates the V1 trial count and PBO), but around it. Four levers, ranked by leverage-per-unit-of-new-overfitting-surface:

---

## 1. Orthogonal return streams — the only structural escape (→ C9)

If the cap binds per strategy, two genuinely weakly-correlated books each near 0.5 combine toward something meaningfully higher. V9(a)'s OSAP ridge composite is the candidate second sleeve; **C9** pre-writes the promotion review with a five-condition compound trigger — same-engine backtest (one-code-path), measured OOS correlation ≤ 0.3 (gate G2.8: the payoff is entirely conditional on this number, so it is the gate, not a hope), per-sleeve deflated Sharpe > 0 net, capital ≥ 2×C8 (splitting capital halves ticket sizes; below the C6 floor the combined book is definitionally not runnable — at micro-book scale C9 may be permanently out of reach, and the trigger encoding that is a feature), and the named architecture review itself. Allocator v1 is a **fixed 50/50 risk-weight combiner, never learned** — a learned meta-allocator is a brand-new overfitting surface, which is the disease being treated. Constraints apply post-combination on the netted overlap.

---

## 2. Keep more of the gross — the biggest ready-made win (→ V6, amended)

The ceiling is gross; turnover and execution are where most of it leaks. The JKMP aim-portfolio form (Bear Case §2) was already flagged as the largest single net-Sharpe improvement available — it is cost-aware construction, not new alpha: trade *toward* the target, not *to* it, and stop paying to chase signal that decays inside the spread. V6 now carries a concrete adoption mechanism: **shadow mode**. Post-G2, `make daily` computes both books, trades only the baseline, and journals the shadow book's counterfactual fills through X1/X2 (`book=shadow`, submit-fenced by hardened Test 17). Gate **G3.7** decides adoption on ≥ 60 trading days of logged shadow-vs-live evidence (the draft's "G3.5" collided with page 08's existing fire-drill gate — caught and corrected during the pass). Why shadow rather than A/B: the M4 holdout is single-use and gets consumed at G2.7 — post-G2, live time is the only genuine out-of-sample left, and shadow mode manufactures a second OOS stream from the same days at zero capital risk.

---

## 3. Size into where the edge is real (→ O9)

Avramov (Bear Case §2) shows DL stat-arb profit concentrates in high-limits-to-arbitrage states; Khandani–Lo (§4) shows what crowded books do to each other. The crowding gauges pre-registered in V9(b) — days-to-cover, short interest — are promoted from *monitoring* to a formalized *sizing* input: **O9** upgrades O3's index (z-scored EWMA composite, half-life 10d, ±0.05 hysteresis per the O8 pattern) and pins the FINRA **publication-vintage join** for backtests (Test 16 — the D3/FRED lesson applied to a twice-monthly, ~T+8/9-lagged feed; conditioning day-t sizing on day-t short interest is leakage wearing a risk-management costume). Bounds stay O3's [0.3, 1.0] — **one crowding multiplier, not two**; de-risk-only in v1, with scale-up-into-scarcity pre-registered separately because levering into thin arbitrage capital is the aggressive half. Distinct from the regime overlay: O1 is drawdown control, O9 is edge timing.

---

## 4. Novel inputs — highest ceiling, sharpest knife (→ D7)

McLean–Pontiff decay (§3) happens because everyone trades the same paper; the durable escape is information the published architecture doesn't use. It is also exactly where leakage and overfitting are most dangerous — which is why **D7** activates today, before any such source exists: point-in-time vintages with enforced publication lag, hard quarantine from training/selection until a CPCV ablation clears on net *deflated*-Sharpe uplift with PBO in bound (Test 20), vintage-stamped model weights (dormant Rule 4/V8 becomes mandatory), every ablation a V1 trial, and the V2 haircut applied to the uplift claim itself. High ceiling, last in line.

---

## What this project will NOT do

No added features, deeper nets, longer window searches, or architecture A/Bs in pursuit of a bigger backtest number. Those raise the raw Sharpe and lower the deflated one — self-deception, which the corpus's own design philosophy (main page §1) names as what actually kills DIY quant. The two cheapest attacks on estimation error are already spent (V3 ensemble, V5 shrinkage); there is little left to squeeze on that axis.

---

## The adoption state machine

Every lever follows the same path: **dormant (spec'd, tested, fenced) → trigger conditions met (named on page 04) → evidence phase (shadow window / CPCV ablation / correlation measurement) → gate (G3.7, G2.8, D7 ablation gate) → adopted, logged, clock reset.** Every activation is a V1 registry trial, measured against the V2 decayed prior, and — if it lands in Phase 3 — resets the G3.1 60-day clock. An edge increase that can't survive this gauntlet was never edge; it was a new way to lose money more confidently.

---

## Timeline by phase

| phase | what changes |
|-------|-------------|
| Today | Everything spec'd; only D7 live (governs sources that don't exist yet — constrains nothing in Phases 0–2). |
| Phase 0 | FINRA vintage/publication-date column lands with the lake; hardened Tests 16 & 20 land with the suite. |
| Phase 1 | **Nothing changes.** The replication stays byte-clean or no later result is attributable. |
| Phase 2 | O9 tuned alongside the existing overlays (whipsaw bound, C5 interaction, V7 tail-scenario false-negative rate once the harness exists); OSAP sleeve built through the same engine and its OOS correlation **measured and recorded** at G2.8 — it is C9's trigger input, not an eyeball. |
| Post-G2 | V6 shadow mode starts running silently under the live baseline. |
| Phase 3 | G3.7 decides V6 adoption on shadow evidence; C9's review fires only if all five conditions hold; D7 governs any new-source attempt. |

---

> Same disclaimer as everywhere in this corpus: not financial advice; paper-trade thoroughly; only ever risk capital you can afford to lose.
