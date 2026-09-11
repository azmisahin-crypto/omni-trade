import unittest

from omnitrade.risk import RiskConfig, RiskManager


class TestRiskManager(unittest.TestCase):
    def test_position_stake_respects_max_position_pct(self):
        rm = RiskManager(RiskConfig(max_position_pct=0.25))
        self.assertAlmostEqual(rm.position_stake(1000.0), 250.0)

    def test_can_open_position_respects_max_open_positions(self):
        rm = RiskManager(RiskConfig(max_open_positions=2))
        self.assertTrue(rm.can_open_position(0))
        self.assertTrue(rm.can_open_position(1))
        self.assertFalse(rm.can_open_position(2))

    def test_should_stop_loss_triggers_at_threshold(self):
        rm = RiskManager(RiskConfig(stop_loss_pct=0.05))
        self.assertFalse(rm.should_stop_loss(entry_price=100, current_price=96))
        self.assertTrue(rm.should_stop_loss(entry_price=100, current_price=95))
        self.assertTrue(rm.should_stop_loss(entry_price=100, current_price=90))

    def test_stop_loss_disabled_when_pct_zero(self):
        rm = RiskManager(RiskConfig(stop_loss_pct=0.0))
        self.assertFalse(rm.should_stop_loss(entry_price=100, current_price=1))

    def test_should_take_profit_triggers_at_threshold(self):
        rm = RiskManager(RiskConfig(take_profit_pct=0.1))
        self.assertFalse(rm.should_take_profit(entry_price=100, current_price=105))
        self.assertTrue(rm.should_take_profit(entry_price=100, current_price=110))

    def test_take_profit_disabled_when_none(self):
        rm = RiskManager(RiskConfig(take_profit_pct=None))
        self.assertFalse(rm.should_take_profit(entry_price=100, current_price=1000))

    def test_kill_switch_activates_on_daily_loss_threshold(self):
        rm = RiskManager(RiskConfig(max_daily_loss_pct=0.1))
        rm.update_daily_baseline(1000.0, ts=0)
        self.assertFalse(rm.check_kill_switch(950.0))  # %5 kayıp, limit altında
        self.assertTrue(rm.check_kill_switch(890.0))  # %11 kayıp, limit aşıldı

    def test_kill_switch_stays_active_even_if_equity_recovers_same_day(self):
        rm = RiskManager(RiskConfig(max_daily_loss_pct=0.1))
        rm.update_daily_baseline(1000.0, ts=0)
        rm.check_kill_switch(880.0)  # tetiklendi
        self.assertTrue(rm.check_kill_switch(950.0))  # toparlansa da aynı gün aktif kalır

    def test_kill_switch_resets_on_new_day(self):
        rm = RiskManager(RiskConfig(max_daily_loss_pct=0.1))
        rm.update_daily_baseline(1000.0, ts=0)
        rm.check_kill_switch(850.0)
        self.assertTrue(rm.kill_switch_active)

        # 2 gün sonra (86400 * 2 saniye) yeni baseline ile sıfırlanmalı
        rm.update_daily_baseline(850.0, ts=86400 * 2)
        self.assertFalse(rm.kill_switch_active)

    def test_can_open_position_blocked_by_active_kill_switch(self):
        rm = RiskManager(RiskConfig(max_daily_loss_pct=0.1, max_open_positions=5))
        rm.update_daily_baseline(1000.0, ts=0)
        rm.check_kill_switch(850.0)
        self.assertFalse(rm.can_open_position(0))


if __name__ == "__main__":
    unittest.main()
