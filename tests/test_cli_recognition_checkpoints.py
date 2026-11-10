"""Offline CLI checkpoint validation, actual serialization, and output gating."""
import asyncio
from contextlib import ExitStack
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from config import Config
from checkpoint_manager import CheckpointManager
from main import SetlistGenerator, complete_checkpoint_recognitions
from track_recognizer import RecognitionIncomplete
from worker.pipeline.models import Recognition, valid_checkpoint_coverage


def row(index):
    return Recognition(index * 15, None, None, None, {'matches': []}, False, index, http_status=200)


class Tests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        self.stack.enter_context(patch('socket.socket.connect', side_effect=AssertionError('NETWORK FORBIDDEN')))
        self.stack.enter_context(patch('socket.getaddrinfo', side_effect=AssertionError('DNS FORBIDDEN')))
        self.stack.enter_context(patch('worker.db.connect', side_effect=AssertionError('DB FORBIDDEN')))

    def test_real_checkpoint_roundtrip_preserves_minimal_evidence(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            for field in ('ASSETS_DIR', 'CHECKPOINT_DIR', 'OUTPUT_DIR'):
                stack.enter_context(patch.object(Config, field, Path(directory) / field))
            stack.enter_context(patch.object(Config, 'ENABLE_CHECKPOINTS', True))
            checkpoint = CheckpointManager('https://example.invalid/set', 'synthetic')
            result = row(0)
            result.raw_data['untrusted_url'] = 'PRIVATE_URL'
            checkpoint.save_recognition_checkpoint([result], 'recognized')
            saved = checkpoint.load_checkpoint()
            self.assertIsNotNone(valid_checkpoint_coverage(saved['data']['recognitions'], 1, 15))
            self.assertNotIn('PRIVATE_URL', checkpoint.checkpoint_file.read_text())
            failure = Recognition(0, None, None, None, None, False, 0, error_type='TransportError')
            checkpoint.save_recognition_checkpoint([failure], 'recognized')
            self.assertIsNone(valid_checkpoint_coverage(checkpoint.load_checkpoint()['data']['recognitions'], 1, 15))

    def test_exact_coverage_and_geometry_required(self):
        segmenter = SimpleNamespace(segment_duration=30, overlap=15, calculate_total_segments=lambda _: 2)
        checkpoint = {'stage': 'recognized', 'data': {'recognitions': [asdict(row(1)), asdict(row(0))]}}
        self.assertEqual([r.segment_index for r in complete_checkpoint_recognitions(checkpoint, segmenter, 45)], [0, 1])
        for rows in ([asdict(row(0)), asdict(row(0))], [asdict(row(0))],
                     [asdict(row(0)), asdict(row(2))],
                     [asdict(row(0)), dict(asdict(row(1)), timestamp=16)],
                     [asdict(row(0)), dict(asdict(row(1)), raw_data=None)]):
            checkpoint['data']['recognitions'] = rows
            self.assertIsNone(complete_checkpoint_recognitions(checkpoint, segmenter, 45))
        checkpoint['data']['recognitions'] = [asdict(row(0)), asdict(row(1))]
        checkpoint['data']['geometry'] = {'segment_duration': 60, 'segment_overlap': 45}
        self.assertIsNone(complete_checkpoint_recognitions(checkpoint, segmenter, 45))

    def test_invalid_recognized_checkpoint_resumes_and_incomplete_never_outputs(self):
        checkpoint = MagicMock()
        checkpoint.load_checkpoint.return_value = {'stage': 'recognized', 'data': {'recognitions': [dict(asdict(row(0)), raw_data=None)]}}
        checkpoint.audio_file = Path('/tmp/synthetic')
        downloader = MagicMock()
        downloader.get_video_info.return_value = {'title': 'synthetic', 'duration': 45, 'uploader': 'synthetic'}
        downloader.download.return_value = checkpoint.audio_file
        segmenter = SimpleNamespace(segment_duration=30, overlap=15, calculate_total_segments=lambda _: 2)
        recognizer = SimpleNamespace(close=AsyncMock(), recognize_segments_streaming=AsyncMock(side_effect=RecognitionIncomplete('incomplete')))
        formatter = MagicMock()
        generator = object.__new__(SetlistGenerator)
        generator.builder, generator.enricher = MagicMock(), MagicMock()
        with ExitStack() as stack:
            for name, value in [('CheckpointManager', checkpoint), ('AudioDownloader', downloader),
                                ('AudioSegmenter', segmenter), ('TrackRecognizer', recognizer), ('OutputFormatter', formatter)]:
                stack.enter_context(patch('main.' + name, return_value=value))
            stack.enter_context(patch.object(Config, 'validate', return_value=[]))
            stack.enter_context(patch.object(Config, 'ENABLE_CHECKPOINTS', True))
            with self.assertRaises(RecognitionIncomplete):
                asyncio.run(generator.generate('https://example.invalid/set'))
        self.assertTrue(recognizer.recognize_segments_streaming.call_args.kwargs['resume_from_checkpoint'])
        recognizer.close.assert_awaited_once()
        generator.builder.build_setlist.assert_not_called()
        formatter.save_setlist_json.assert_not_called()
        checkpoint.cleanup_checkpoint.assert_not_called()


if __name__ == '__main__': unittest.main()
