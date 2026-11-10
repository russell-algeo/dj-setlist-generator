"""Finite reviewed private inputs. Capability URLs belong only in private DB rows."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Source:
    id: str
    sha256: str
    bytes: int
    start: int
    end: int
    bounds: str

    @property
    def duration(self):
        return self.end - self.start

    @property
    def windows(self):
        return (self.duration - 30) // 15 + 1

    def pins(self):
        return dict(source_sha256=self.sha256, source_bytes=self.bytes,
                    source_start_seconds=self.start, source_end_seconds=self.end)


JACKSON = Source('jackson-sunday',
    'aa01c4b637efe4e59bac051ef67ce4014e270a1f41fad8b6cbba95310fa58aae',
    4290463660, 3120, 10320, 'approximate; end schedule-derived')
# Direct owner start anchor; two-hour end remains provisional, not verified.
DONALD = Source('donald-two-hour',
    'f8dd7ca1282c64ae4889fdb06fdb3a5e1a373849fe3062f7f47f8c86cdb95d1c',
    4290463660, 3371, 10571, 'owner start anchor; two-hour end provisional')
# Schedule-derived continuation after Jackson; neither boundary acoustically verified.
HALO = Source('halo-varga-sunday',
    'aa01c4b637efe4e59bac051ef67ce4014e270a1f41fad8b6cbba95310fa58aae',
    4290463660, 10320, 15720, 'provisional schedule-derived start and end')
CATALOG = {source.id: source for source in (JACKSON, DONALD, HALO)}


def reviewed_source(value):
    if not isinstance(value, dict):
        raise RuntimeError('fixed_input_mismatch')
    source = CATALOG.get(value.get('source_id', JACKSON.id))
    if (source is None or any(type(value.get(k)) is not type(v) or value.get(k) != v
                              for k, v in source.pins().items())
            or (source != JACKSON and value.get('recognition_mode') != 'resumable')):
        raise RuntimeError('fixed_input_mismatch')
    return source
