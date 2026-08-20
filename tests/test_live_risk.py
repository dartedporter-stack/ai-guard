import unittest

from guard.live_risk import analyze_live_transcript
from guard.risk_engine import calculate_fraud_risk


class LiveRiskTest(unittest.TestCase):
    def test_detects_bank_sms_code_pressure(self):
        analysis = analyze_live_transcript(
            "Я сотрудник банка. Срочно назовите код из СМС, "
            "иначе ваши деньги будут потеряны."
        )
        score, _ = calculate_fraud_risk(analysis)

        self.assertTrue(analysis.bank_impersonation)
        self.assertTrue(analysis.sms_code_request)
        self.assertTrue(analysis.urgency_pressure)
        self.assertGreaterEqual(score, 60)

    def test_detects_kazakh_money_request(self):
        analysis = analyze_live_transcript(
            "Дәл қазір ақша аударыңыз және растау кодын айтыңыз."
        )
        score, _ = calculate_fraud_risk(analysis)

        self.assertTrue(analysis.money_request)
        self.assertTrue(analysis.sms_code_request)
        self.assertTrue(analysis.urgency_pressure)
        self.assertGreaterEqual(score, 60)

    def test_normal_conversation_stays_low(self):
        analysis = analyze_live_transcript(
            "Добрый день. Встречаемся завтра в десять часов."
        )
        score, _ = calculate_fraud_risk(analysis)

        self.assertLess(score, 30)
        self.assertEqual(analysis.red_flags, [])


if __name__ == "__main__":
    unittest.main()
