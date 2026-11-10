"""Finite Highkin two-original source adapter.

No fetch, database, playback or provider operations. Originals are read-only;
joined PCM is a recognition derivative, never a replacement playback source.
"""
from contextlib import ExitStack
from dataclasses import asdict, dataclass
import hashlib
from pathlib import Path
import wave


@dataclass(frozen=True)
class Piece:
    filename: str
    sha256: str
    bytes: int
    start_frame: int
    end_frame: int
    total_frames: int = 715076352
    sample_rate: int = 44100
    channels: int = 2
    sample_width: int = 3


@dataclass(frozen=True)
class JoinedSource:
    id: str
    pieces: tuple[Piece, ...]
    bounds: str

    @property
    def frames(self):
        return sum(p.end_frame-p.start_frame for p in self.pieces)

    @property
    def duration(self):
        rate = self.pieces[0].sample_rate
        if self.frames % rate:
            raise RuntimeError('reviewed_duration_must_be_whole_seconds')
        return self.frames // rate

    @property
    def windows(self):
        return (self.duration-30)//15+1

    def pins(self):
        return {'source_parts': [asdict(p) for p in self.pieces],
                'source_duration_seconds': self.duration,
                'source_total_frames': self.frames}


HIGHKIN = JoinedSource('highkin-sunday', (
    Piece('260621_0129_3-4.wav',
          'a67425f4a8f30a20912ff337b4bf7706cff6e25acfa88a48e4647592f4d31da6',
          4290463660, 535148352, 715076352),
    Piece('260621_0130_3-4.wav',
          'aa01c4b637efe4e59bac051ef67ce4014e270a1f41fad8b6cbba95310fa58aae',
          4290463660, 0, 137592000)),
    'Sunday 13:30–15:30; schedule-derived backward from approximate Jackson start; '
    'neither handoff acoustically verified; historical BWF continuity verified, no modeled gap')


def _exact(actual, expected):
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return actual.keys() == expected.keys() and all(_exact(actual[k], v) for k, v in expected.items())
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(_exact(a, b) for a, b in zip(actual, expected))
    return actual == expected


def reviewed_highkin(value):
    """Local descriptor validation only; does not authorize live execution."""
    if (not isinstance(value, dict) or value.get('source_id') != HIGHKIN.id
            or value.get('recognition_mode') != 'resumable'
            or not all(_exact(value.get(k), v) for k, v in HIGHKIN.pins().items())
            or set(value) - (set(HIGHKIN.pins()) | {'source_id', 'recognition_mode', 'source_urls'})):
        raise RuntimeError('fixed_input_mismatch')
    return HIGHKIN


def assemble_highkin(descriptor, originals, destination):
    """Verify complete originals and write one sample-exact, uncompressed derivative."""
    return _assemble(reviewed_highkin(descriptor), originals, destination)


def _assemble(source, originals, destination):
    # Private general helper exists for small synthetic tests, never descriptor input.
    paths = tuple(Path(p) for p in originals)
    destination = Path(destination)
    if len(paths) != len(source.pieces) or len(set(p.resolve() for p in paths)) != len(paths):
        raise RuntimeError('source_count_mismatch')
    if destination.exists() or destination.is_symlink() or destination.resolve() in {p.resolve() for p in paths}:
        raise RuntimeError('destination_must_be_new')
    if any(p.name != spec.filename for p, spec in zip(paths, source.pieces)):
        raise RuntimeError('source_order_mismatch')
    created = False
    try:
        with ExitStack() as stack:
            readers = []
            fmt = None
            for path, spec in zip(paths, source.pieces):
                if not 0 <= spec.start_frame < spec.end_frame <= spec.total_frames:
                    raise RuntimeError('source_bounds_mismatch')
                handle = stack.enter_context(path.open('rb'))
                handle.seek(0, 2)
                if handle.tell() != spec.bytes:
                    raise RuntimeError('source_size_mismatch')
                handle.seek(0)
                if hashlib.file_digest(handle, 'sha256').hexdigest() != spec.sha256:
                    raise RuntimeError('source_digest_mismatch')
                handle.seek(0)
                reader = stack.enter_context(wave.open(handle, 'rb'))
                actual = (reader.getnchannels(), reader.getsampwidth(), reader.getframerate())
                expected = (spec.channels, spec.sample_width, spec.sample_rate)
                if (actual != expected or (fmt is not None and actual != fmt)
                        or reader.getcomptype() != 'NONE' or reader.getnframes() != spec.total_frames):
                    raise RuntimeError('source_format_mismatch')
                fmt = actual
                readers.append(reader)
            # Exclusive creation prevents clobbering even if a target appeared meanwhile.
            with destination.open('xb') as output:
                created = True
                with wave.open(output, 'wb') as writer:
                    writer.setparams((*fmt, 0, 'NONE', 'not compressed'))
                    for reader, spec in zip(readers, source.pieces):
                        reader.setpos(spec.start_frame)
                        remaining = spec.end_frame-spec.start_frame
                        while remaining:
                            count = min(65536, remaining)
                            frames = reader.readframes(count)
                            if len(frames) != count*fmt[0]*fmt[1]:
                                raise RuntimeError('source_truncated')
                            writer.writeframesraw(frames)
                            remaining -= count
        with wave.open(str(destination), 'rb') as check:
            if check.getnframes() != source.frames:
                raise RuntimeError('joined_frame_mismatch')
        with destination.open('rb') as result:
            digest = hashlib.file_digest(result, 'sha256').hexdigest()
        return {'audio_sha256': digest, 'frames': source.frames,
                'duration_seconds': source.duration, 'expected_windows': source.windows,
                'source_id': source.id, 'source_pins': source.pins(), 'bounds': source.bounds}
    except BaseException:
        if created:
            destination.unlink(missing_ok=True)
        raise
