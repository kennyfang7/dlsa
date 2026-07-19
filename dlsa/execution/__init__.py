"""
Alpaca order routing and reconciliation.

On-close orders only (time_in_force='cls', frozen param E6).
Signals from day-t close are submitted the evening of t and fill
in the t+1 closing auction.
"""
