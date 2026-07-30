import unittest

from codex_eink.quota import parse_rate_limits, quota_from_rate_limit_error


class QuotaTests(unittest.TestCase):
    def test_parse_live_rate_limits(self):
        quota = parse_rate_limits(
            {
                "rateLimitsByLimitId": {
                    "codex": {
                        "primary": {"usedPercent": 20, "resetsAt": 1000, "windowDurationMins": 300},
                        "secondary": {"usedPercent": 30, "resetsAt": 2000, "windowDurationMins": 10080},
                    }
                },
                "planType": "plus",
            }
        )
        self.assertEqual(quota.primary.remaining_percent, 80)
        self.assertEqual(quota.secondary.remaining_percent, 70)
        self.assertEqual(quota.plan_type, "plus")

    def test_missing_values_stay_unknown(self):
        quota = parse_rate_limits({})
        self.assertIsNone(quota.primary)
        self.assertIsNone(quota.secondary)

    def test_api_authentication_error_produces_api_plan(self):
        quota = quota_from_rate_limit_error(
            {"code": -32600, "message": "chatgpt authentication required to read rate limits"}
        )
        self.assertEqual(quota.plan_type, "api")

    def test_unrelated_rate_limit_error_remains_unknown(self):
        self.assertIsNone(quota_from_rate_limit_error({"code": -32600, "message": "invalid request"}))


if __name__ == "__main__":
    unittest.main()
