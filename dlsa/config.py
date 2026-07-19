"""
Config loading and resolution.

load_config(path) reads a YAML config file and returns a Config object.
Config.resolved(key) returns the actual class object for class-name keys
(engine_class, factor_model_class, policy_class), enabling the test that
asserts test_min.yaml and backtest.yaml wire to the same classes.

Every run is driven by a config; nothing is hardcoded.
"""
