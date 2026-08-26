from src.engine import AdaptiveStrategy, BotConfig, RiskGate

def candles(n=120,start=100.0):
    return [{"c": start + i * 0.2} for i in range(n)]

def test_strategy_warms_up():
    assert AdaptiveStrategy().score(candles(20), {})["action"] == "HOLD"

def test_strategy_returns_signal_shape():
    result = AdaptiveStrategy().score(candles(), {"mid":124,"bid":123.99,"ask":124.01,"funding_rate":0})
    assert result["action"] in {"LONG","SHORT","HOLD"}
    assert 0 <= result["confidence"] <= 1

def test_risk_rejects_low_confidence():
    gate=RiskGate(BotConfig())
    ok,reason=gate.check(1000,0.1,1,1)
    assert not ok
    assert "confidence" in reason
