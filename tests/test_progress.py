from unittest import TestCase
from mentions.progress import format_progress

class ProgressTests(TestCase):
    def test_eta_is_for_validation_not_whole_job(self):
        output = format_progress(dict(stage='reading_and_validating_shards', archives_done=100,
                                     archives_total=400, papers_read=800, elapsed_seconds=20))
        self.assertIn('25.0%', output)
        self.assertIn('ETA 1m 00s for validation', output)
        self.assertIn('5.0 archives/s', output)

    def test_zero_progress_and_other_stages(self):
        self.assertIn('calculating', format_progress(dict(stage='reading_and_validating_shards')))
        self.assertNotIn('ETA', format_progress(dict(stage='building_database', elapsed_seconds=50)))
