"""
CNN+Transformer signal network (PyTorch).

Signal path (fixed order, V3/V5):
  signal net → ensemble mean (V3) → shrink() (V5) → policy

The policy always consumes SHRUNK signals. Collapsing the ensemble to one seed
or bypassing shrinkage are bugs, not simplifications.
"""
