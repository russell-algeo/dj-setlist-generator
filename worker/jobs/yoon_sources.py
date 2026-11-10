"""Finite reviewed private inputs. Capability URLs belong only in private DB rows."""
from dataclasses import dataclass
from worker.jobs.yoon_highkin_source import HIGHKIN, reviewed_highkin


@dataclass(frozen=True)
class Source:
    id: str
    sha256: str
    bytes: int
    start: int | float
    end: int | float
    bounds: str
    start_frame: int | None = None
    end_frame: int | None = None
    sample_rate: int | None = None

    @property
    def duration(self):
        if self.sample_rate is not None:
            frames = self.end_frame - self.start_frame
            if frames % self.sample_rate:
                raise RuntimeError('reviewed_duration_must_be_whole_seconds')
            return frames // self.sample_rate
        return self.end - self.start

    @property
    def windows(self):
        return (self.duration - 30) // 15 + 1

    def pins(self):
        pins = dict(source_sha256=self.sha256, source_bytes=self.bytes,
                    source_start_seconds=self.start, source_end_seconds=self.end)
        if self.sample_rate is not None:
            pins.update(source_start_frame=self.start_frame, source_end_frame=self.end_frame,
                        source_sample_rate=self.sample_rate)
        return pins

    @property
    def seek_seconds(self):
        return self.start if self.sample_rate is None else self.start_frame // self.sample_rate

    def crop_filter_args(self):
        if self.sample_rate is None:
            return []
        # Integer-second input seek followed by a sample-exact residual trim.
        residual = self.start_frame % self.sample_rate
        end = residual + self.end_frame - self.start_frame
        return ['-af', f'atrim=start_sample={residual}:end_sample={end},asetpts=PTS-STARTPTS']


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
# Sunday slot yoon-36, inferred from the approximate Jackson anchor.
# Frame pins are authoritative; binary float subtraction is not exact here.
GRISHA = Source('grisha-sunday',
    'a67425f4a8f30a20912ff337b4bf7706cff6e25acfa88a48e4647592f4d31da6',
    4290463660, 4934.883265306123, 12134.883265306122,
    'provisional schedule-derived boundaries from approximate Jackson anchor',
    start_frame=217628352, end_frame=535148352, sample_rate=44100)
CATALOG = {source.id: source for source in (JACKSON, DONALD, HALO, GRISHA, HIGHKIN)}


def reviewed_source(value):
    if not isinstance(value, dict):
        raise RuntimeError('fixed_input_mismatch')
    if value.get('source_id') == HIGHKIN.id:
        return reviewed_highkin(value)
    source = CATALOG.get(value.get('source_id', JACKSON.id))
    if (source is None or any(type(value.get(k)) is not type(v) or value.get(k) != v
                              for k, v in source.pins().items())
            or (source != JACKSON and value.get('recognition_mode') != 'resumable')):
        raise RuntimeError('fixed_input_mismatch')
    return source
