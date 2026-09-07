from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / 'Windows'))
import setup_check


class SetupChecks(unittest.TestCase):
    def test_active_but_muted_endpoint_is_not_reported_ready(self):
        levels = {'playback': {'mute': True, 'volume': 0., 'channels': [0.]},
                  'capture': {'mute': False, 'volume': 1., 'channels': [1.]}}
        with patch.object(setup_check, 'cable_levels', return_value=levels):
            result = setup_check.inspect()
            self.assertFalse(result['ok'])
            self.assertIn('CABLE Input', result['message'])
            self.assertIn('음소거', result['message'])

    def test_missing_capture_endpoint_is_not_reported_ready(self):
        with patch.object(setup_check, 'cable_levels', return_value={'playback': {'mute': False, 'volume': 1., 'channels': [1.]}}):
            result = setup_check.inspect()
            self.assertFalse(result['ok'])
            self.assertIn('CABLE Output', result['message'])

    def test_read_only_check_does_not_request_volume_repair(self):
        with patch.object(setup_check, 'cable_levels', return_value={}) as levels:
            setup_check.inspect()
            levels.assert_called_once_with(False)


if __name__ == '__main__': unittest.main()
