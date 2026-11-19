import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mentions.harvest import harvest


class HarvestMonthTests(unittest.TestCase):
    def test_only_requested_month_is_fetched(self):
        empty_feed = b'<feed xmlns="http://www.w3.org/2005/Atom" />'
        with tempfile.TemporaryDirectory() as directory:
            with patch('mentions.harvest.data_dir', return_value=Path(directory)), \
                 patch('mentions.harvest.harvest_windows', return_value=[
                     ('202609010000', '202609302359'),
                     ('202610010000', '202610312359')]), \
                 patch('mentions.harvest.fetch', return_value=empty_feed) as fetch, \
                 patch('mentions.harvest.time.sleep'):
                harvest(month='2026-10')
                self.assertEqual(fetch.call_count, 1)
                self.assertIn('202610010000', fetch.call_args.args[0])
                self.assertIn('202610312359', fetch.call_args.args[0])

    def test_invalid_or_unavailable_month_is_rejected(self):
        with patch('mentions.harvest.harvest_windows', return_value=[]):
            for month in ['2026-13', '2026-10', '../../bad']:
                with self.subTest(month=month), self.assertRaises(ValueError):
                    harvest(month=month)
