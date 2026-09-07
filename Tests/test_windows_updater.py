import hashlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parents[1] / 'Windows'))
import updater


def release(version, payload=b'installer'):
    name = f'STTS-{version}-setup-x64.exe'
    return {'tag_name': 'v' + version, 'assets': [{
        'name': name, 'size': len(payload),
        'browser_download_url': f'{updater.DOWNLOADS}v{version}/{name}',
        'digest': 'sha256:' + hashlib.sha256(payload).hexdigest()}]}


class UpdateTests(unittest.TestCase):
    def test_failed_check_is_reported_and_can_be_retried(self):
        import app
        window = app.App.__new__(app.App)
        window.status = Mock(); window.update_button = Mock(); window.update_busy = Mock()
        window.update_checking = True
        window.update_checked(None, 'network unavailable', True)
        self.assertFalse(window.update_checking)
        self.assertIn('network unavailable', window.status.setText.call_args.args[0])
        window.update_busy.assert_called_once()

    def test_newer_mac_only_release_does_not_hide_windows_update(self):
        self.assertEqual(updater.select_release([
            {'tag_name': 'v0.0.6', 'assets': []}, release('0.0.5'), release('0.0.4')], '0.0.4')['version'], '0.0.5')

    def test_no_downgrade_prerelease_or_untrusted_asset(self):
        pre = dict(release('0.0.6'), prerelease=True)
        wrong = release('0.0.7'); wrong['assets'][0]['browser_download_url'] = 'https://example.com/setup.exe'
        self.assertIsNone(updater.select_release([pre, wrong, release('0.0.4')], '0.0.4'))

    def test_valid_download_promotes_only_verified_bytes(self):
        data = b'installer'; asset = updater.select_release([release('0.0.5', data)], '0.0.4')
        with tempfile.TemporaryDirectory() as folder, patch.object(updater, 'open_url', return_value=io.BytesIO(data)):
            path = updater.download_installer(asset, folder, '0.0.4', Mock())
            self.assertEqual(path.read_bytes(), data)
            self.assertFalse(path.with_suffix('.part').exists())

    def test_corruption_truncation_and_failure_never_leave_installable_file(self):
        asset = updater.select_release([release('0.0.5')], '0.0.4')
        for data in (b'corrupted', b'inst', b'installer extra'):
            with self.subTest(data=data), tempfile.TemporaryDirectory() as folder, patch.object(updater, 'open_url', return_value=io.BytesIO(data)):
                with self.assertRaises(ValueError): updater.download_installer(asset, folder, '0.0.4', Mock())
                self.assertEqual(list(Path(folder).iterdir()), [])

    def test_missing_digest_never_downloads(self):
        asset = updater.select_release([release('0.0.5')], '0.0.4'); asset.pop('digest')
        with tempfile.TemporaryDirectory() as folder, patch.object(updater, 'open_url') as opened:
            with self.assertRaises(ValueError): updater.download_installer(asset, folder, '0.0.4', Mock())
            opened.assert_not_called()
