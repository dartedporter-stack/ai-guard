import unittest
from unittest.mock import patch

from guard.models import GuardAnalysis
from guard.service import analyze_and_format, contains_url


class UrlDetectionTests(unittest.TestCase):

    def test_detects_https_url(self):
        self.assertTrue(
            contains_url("Перейдите на https://example.com/login")
        )

    def test_detects_www_url(self):
        self.assertTrue(
            contains_url("Откройте www.example.com")
        )

    def test_detects_domain_without_protocol(self):
        self.assertTrue(
            contains_url("Адрес сайта: example.kz/payment")
        )

    def test_does_not_detect_plain_text_or_email(self):
        self.assertFalse(
            contains_url("Напишите пользователю user@example.com")
        )

    @patch("guard.service.format_guard_result")
    @patch("guard.service.calculate_fraud_risk")
    @patch("guard.service.analyze_text")
    def test_service_passes_detected_url_to_formatter(
        self,
        analyze_text_mock,
        calculate_risk_mock,
        format_result_mock,
    ):
        analysis = GuardAnalysis(
            category="Фишинг",
            initiated_by_user=False,
            unknown_caller=True,
            user_intent="OBSERVATION",
            sms_code_request=False,
            money_request=False,
            personal_data_request=False,
            suspicious_link=True,
            urgency_pressure=False,
            bank_impersonation=False,
            fake_support=False,
            fake_prize=False,
            guaranteed_profit=False,
            suspicious_deal=False,
            fake_job=False,
            rental_scam=False,
            no_inspection=False,
            remote_seller=False,
            advance_payment=False,
            regulated_or_illicit_document_offer=False,
            harmful_or_unsafe_action=False,
            red_flags=[],
            actions=[],
            conclusion="Обнаружена ссылка.",
        )
        analyze_text_mock.return_value = analysis
        calculate_risk_mock.return_value = (20, [])
        format_result_mock.return_value = "result"

        result = analyze_and_format("Проверьте example.com/login")

        self.assertEqual(result, "result")
        format_result_mock.assert_called_once_with(
            analysis=analysis,
            fraud_score=20,
            has_url=True,
        )


if __name__ == "__main__":
    unittest.main()
