from risk_support import RiskTestCase, session_double, db_error
from core.errors import ServiceUnavailable


class TransactionTests(RiskTestCase):
    def test_factory_failure_is_safe_and_following_request_healthy(self):
        self.factory.side_effect = [db_error(), self.db]
        response = self.post_risk()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['detail']['code'], 'DATABASE_UNAVAILABLE')
        self.osm.assert_not_called()
        self.assertEqual(self.post_risk().status_code, 200)
        self.db.close.assert_called_once()

    def test_query_add_flush_commit_failure_rolls_back_and_next_request_is_healthy(self):
        for stage in ('query', 'add', 'flush', 'commit'):
            failed, clean = session_double(), session_double()
            if stage == 'flush':
                # SQLAlchemy commit performs flush, so model that boundary explicitly.
                failed.flush.side_effect = db_error()
                failed.commit.side_effect = failed.flush
            else:
                getattr(failed, stage).side_effect = db_error()
            self.factory.side_effect = [failed, clean]
            self.elevation.side_effect = [0, 8, 0, 8]
            with self.subTest(stage=stage):
                response = self.post_risk()
                self.assertEqual(response.status_code, 503, response.text)
                self.assertEqual(response.json()['detail']['code'], 'DATABASE_UNAVAILABLE')
                self.assertNotIn('private', response.text)
                failed.rollback.assert_called_once()
                failed.close.assert_called_once()
                failed.refresh.assert_not_called()
                self.assertEqual(self.post_risk().status_code, 200)
                clean.add.assert_called_once()
                clean.commit.assert_called_once()
                clean.rollback.assert_not_called()
                clean.close.assert_called_once()

    def test_confirmed_commit_survives_close_failure_and_logs_no_details(self):
        for error in (db_error(), RuntimeError('private cleanup')):
            with self.subTest(error=type(error).__name__):
                self.db.reset_mock()
                self.db.close.side_effect = error
                self.elevation.side_effect = [0, 8]
                with self.assertLogs('database', level='ERROR') as logs:
                    response = self.post_risk()
                self.assertEqual(response.status_code, 200, response.text)
                self.db.commit.assert_called_once()
                self.db.rollback.assert_not_called()
                self.db.refresh.assert_not_called()
                self.db.close.assert_called_once()
                self.assertNotIn('private', '\n'.join(logs.output))

    def test_prior_errors_survive_failed_rollback_and_close(self):
        for error, status in ((ServiceUnavailable('AI_UNAVAILABLE'), 503),
                              (ValueError('private programming bug'), 500)):
            self.db.reset_mock()
            self.db.rollback.side_effect = db_error()
            self.db.close.side_effect = db_error()
            self.ai.side_effect = error
            self.elevation.side_effect = [0, 8]
            with self.subTest(status=status), self.assertLogs('database', level='ERROR') as logs:
                response = self.post_risk()
                self.assertEqual(response.status_code, status)
                self.assertNotIn('private', response.text)
                self.assertNotIn('private', '\n'.join(logs.output))
                self.db.add.assert_not_called()
                self.db.commit.assert_not_called()
                self.db.rollback.assert_called_once()
                self.db.close.assert_called_once()
