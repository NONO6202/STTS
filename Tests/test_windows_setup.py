from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / 'Windows'))
import setup_check


class SetupChecks(unittest.TestCase):
    def test_endpoint_identity_survives_rename_without_accepting_a_physical_mic(self):
        def device(name, adapter):
            return SimpleNamespace(FriendlyName=name, properties={setup_check.ADAPTER_PROPERTY: adapter})
        for name in ('CABLE Output (VB-Audio Virtual Cable)', 'STTS (VB-Audio Virtual Cable)', 'My microphone'):
            self.assertTrue(setup_check.is_cable_endpoint(device(name, 'VB-Audio Virtual Cable')))
        self.assertFalse(setup_check.is_cable_endpoint(device('STTS', 'Realtek Audio')))
        self.assertFalse(setup_check.is_cable_endpoint(device('STTS', 'VB-Audio Cable A')))

    def test_capture_uses_the_verified_endpoint_name_and_input_direction(self):
        import audio
        name = 'STTS (VB-Audio Virtual Cable)'
        devices = [
            {'name': 'STTS', 'max_input_channels': 1, 'hostapi': 0},
            {'name': name, 'max_input_channels': 0, 'hostapi': 0},
            {'name': name, 'max_input_channels': 2, 'hostapi': 0},
        ]
        with patch.object(setup_check, 'cable_levels', return_value={'capture': {'name': name}}), \
             patch.object(audio.sd, 'query_devices', return_value=devices), \
             patch.object(audio.sd, 'query_hostapis', return_value=[{'name': 'Windows WASAPI'}]):
            self.assertEqual(audio.cable_input(), 2)
            devices.pop()
            with self.assertRaises(RuntimeError): audio.cable_input()

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
