from twcosts import BrokerFees, broker, is_etf, net_return


def test_yuanta_defaults():
    b = BrokerFees()
    assert b.fee_discount == 0.6 and b.min_fee == 20 and b.min_fee_odd == 1
    assert abs(b.eff_fee_rate - 0.000855) < 1e-12


def test_fee_floor_and_minimums():
    b = BrokerFees()
    assert b.fee(100, 1000) == 85            # 100,000 x 0.0855% = 85.5 → 無條件捨去
    assert b.fee(10, 1000) == 20             # 整股低消 20
    assert b.fee(100, 10) == 1               # 零股低消 1
    assert b.fee(100, 1500) == 85 + 42       # 1 張 + 500 股零股分開計
    assert b.fee(100, 0) == 0


def test_tax_rates():
    b = BrokerFees()
    assert b.tax(100, 1000) == 300 and b.tax(100, 1000, daytrade=True) == 150
    assert b.tax(100, 1000, etf=True) == 100 and b.tax(100, 1000, etf="bond") == 0
    assert is_etf("0050") is True and is_etf("00679B") == "bond" and is_etf("2330") is False


def test_net_return_and_discount_setting():
    flat = net_return(100, 100)
    assert abs(flat - (-(85 + 85 + 300) / 100085)) < 1e-9
    assert net_return(100, 100, fees=broker(1.0)) < flat      # 沒折扣更貴
    assert broker(None).fee_discount == 0.6 and broker(0.28).fee_discount == 0.28
    rt = BrokerFees().round_trip(100, 102, 1000, daytrade=True)
    assert rt["net_pnl"] == 2000 - 85 - 87 - 153
