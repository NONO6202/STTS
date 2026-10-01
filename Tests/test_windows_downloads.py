import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / 'Windows'))
import downloads
import worker


class Response(io.BytesIO):
    status = 206
    def __init__(self, data, size=None):
        super().__init__(data)
        self.headers = {'Content-Range': f'bytes 0-{(size or len(data))-1}/{size or len(data)}'}


class ModelDownloads(unittest.TestCase):
    def test_completed_parts_resume_without_network_and_join_exactly(self):
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / 'model.bin'
            with patch.object(downloads.urllib.request, 'urlopen', return_value=Response(b'weights')) as network:
                temp, parts, count = downloads.download('https://example.test/model', target, 7, lambda _: None)
                self.assertEqual(temp.read_bytes(), b'weights')
                downloads.download('https://example.test/model', target, 7, lambda _: None)
                self.assertEqual(network.call_count, 1)
                downloads.finish_parts(parts, count)
                self.assertFalse(parts.exists())

    def test_truncated_file_does_not_become_completed_part(self):
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / 'model.bin'
            with patch.object(downloads.urllib.request, 'urlopen', side_effect=lambda *a, **kw: Response(b'bad', 7)), patch.object(downloads.time, 'sleep'):
                with self.assertRaises(ValueError): downloads.download('https://example.test/model', target, 7, lambda _: None)
            self.assertFalse(target.exists())
            self.assertFalse((Path(root) / '.model.bin.parts/0').exists())

    def test_catalog_pins_prequantized_files_and_their_content_hashes(self):
        for key, asset in worker.CATALOG.items():
            self.assertEqual(asset['bits'], 8)
            self.assertEqual(len(asset['revision']), 40)
            for entry in asset['files']:
                self.assertTrue(entry.get('sha256') or entry.get('git_sha1'))
                self.assertGreater(entry['size'], 0)
                self.assertNotIn('..', Path(entry['path']).parts)
            if key.startswith('qwen'):
                self.assertEqual(asset['format'], 'qwen-int8-scalar')
                self.assertIn('-INT8', asset['repo'])
            elif key != 'supertonic3': self.assertIn('int8', asset['repo'])
        converted = [f for f in worker.CATALOG['supertonic3']['files'] if 'remote_path' in f]
        self.assertEqual(len(converted), 2)
        self.assertTrue(all(f['remote_path'].endswith('.int8.onnx') for f in converted))


if __name__ == '__main__': unittest.main()
