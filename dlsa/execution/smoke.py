"""
Broker smoke test (make broker-smoke, frozen param E6/C6).

Verifies on-close (cls) entitlement and fractional/on-close interaction:
  1. Fetch account info
  2. Fetch a recent bar
  3. Place a paper limit order with time_in_force='cls'
  4. Cancel it

Run before any paper or live run. A failed smoke test is a hard stop.
"""
