"""Finite, source-pinned Yoon schedule candidates. No discovery or arbitrary inputs.

All boundaries remain schedule-provisional. These descriptors do not fill gaps
or change existing sources; source originals are hash-verified before assembly.
"""
from worker.jobs.yoon_highkin_source import Piece, JoinedSource, _exact, _assemble


JOINED_CATALOG = {source.id: source for source in (
    JoinedSource('hank-friday', (
        Piece('260619_0119_3-4.wav', 'e89ad04e8f69ad25c47f2f153862087c203dfd0b8fbe53c1a7f7a3119299c073', 4290463660, 554585976, 715076352, total_frames=715076352),
        Piece('260620_0120_3-4.wav', 'bc52ca6689a9551f70aaa1742d3066da2b3f21f5628815d43c514d8fc0a0dd17', 4290463660, 0, 77649624, total_frames=715076352)), 'Friday 12:00a; provisional schedule projection, not verified performer boundaries. Uses inferred recorder clock alignment.'),
    JoinedSource('honeydu-saturday', (
        Piece('260620_0120_3-4.wav', 'bc52ca6689a9551f70aaa1742d3066da2b3f21f5628815d43c514d8fc0a0dd17', 4290463660, 553929624, 715076352, total_frames=715076352),
        Piece('260620_0121_3-4.wav', 'f7035c693dc4d95546196fa02357ba6ea5fa144e5eaa627af885d026e905a944', 4290463660, 0, 76993272, total_frames=715076352)), 'Saturday 4:30a; provisional schedule projection, not verified performer boundaries. Uses inferred recorder clock alignment.'),
    JoinedSource('hunter-foshee-saturday', (
        Piece('260620_0121_3-4.wav', 'f7035c693dc4d95546196fa02357ba6ea5fa144e5eaa627af885d026e905a944', 4290463660, 553273272, 715076352, total_frames=715076352),
        Piece('260620_0122_3-4.wav', 'cf1842a175f02bd8ea5afe2dd38ddd8778d26dff8482fb2c9abba1ea920f5ff9', 4290463660, 0, 76336920, total_frames=715076352)), 'Saturday 9:00a; provisional schedule projection, not verified performer boundaries. Uses inferred recorder clock alignment.'),
    JoinedSource('doza-lawnchair-generals-saturday', (
        Piece('260620_0125_3-4.wav', '343530f5fa70b004fa05395933f968851fa8b1fb6f646a5bb3b83f4bbd6a7bfd', 4290463660, 458393760, 715076352, total_frames=715076352),
        Piece('260620_0126_3-4.wav', 'f6ea42dab6d80e97c86c08a40a986f53a8538bdb79323b5558f18da67057d010', 4290463660, 0, 60837408, total_frames=715076352)), 'Saturday 7:00p; provisional schedule projection, not verified performer boundaries. Anchored backward from the approximate Jackson start.'),
    JoinedSource('krane-saturday', (
        Piece('260620_0126_3-4.wav', 'f6ea42dab6d80e97c86c08a40a986f53a8538bdb79323b5558f18da67057d010', 4290463660, 616497408, 715076352, total_frames=715076352),
        Piece('260621_0127_3-4.wav', 'f8dd7ca1282c64ae4889fdb06fdb3a5e1a373849fe3062f7f47f8c86cdb95d1c', 4290463660, 0, 139561056, total_frames=715076352)), 'Saturday 2:30a; provisional schedule projection, not verified performer boundaries. Anchored backward from the approximate Jackson start.'),
    JoinedSource('max-coletto-hazy-sunday', (
        Piece('260621_0127_3-4.wav', 'f8dd7ca1282c64ae4889fdb06fdb3a5e1a373849fe3062f7f47f8c86cdb95d1c', 4290463660, 695221056, 715076352, total_frames=715076352),
        Piece('260621_0128_3-4.wav', '2fc487280143ebc13dcac26280c0f74eb778a4b7ae6cbea8d9bd4b719636c3e5', 4290463660, 0, 218284704, total_frames=715076352)), 'Sunday 5:30a; provisional schedule projection, not verified performer boundaries. Anchored backward from the approximate Jackson start.'),
    JoinedSource('4yo4u-jahnsen-local-jerry-sunday', (
        Piece('260621_0128_3-4.wav', '2fc487280143ebc13dcac26280c0f74eb778a4b7ae6cbea8d9bd4b719636c3e5', 4290463660, 615184704, 715076352, total_frames=715076352),
        Piece('260621_0129_3-4.wav', 'a67425f4a8f30a20912ff337b4bf7706cff6e25acfa88a48e4647592f4d31da6', 4290463660, 0, 217628352, total_frames=715076352)), 'Sunday 9:30a; provisional schedule projection, not verified performer boundaries. Anchored backward from the approximate Jackson start.'),
    JoinedSource('mungo-sound-machine-sunday', (
        Piece('260621_0130_3-4.wav', 'aa01c4b637efe4e59bac051ef67ce4014e270a1f41fad8b6cbba95310fa58aae', 4290463660, 693252000, 715076352, total_frames=715076352),
        Piece('260621_0131_3-4.wav', '8e8bc76d49a050424fe01bad5e368033eda4a41466bb20176397e78686d15fac', 4290463660, 0, 216315648, total_frames=715076352)), 'Sunday 7:00p; provisional schedule projection, not verified performer boundaries. Anchored backward from the approximate Jackson start.'),
    JoinedSource('danny-daze-sunday', (
        Piece('260621_0131_3-4.wav', '8e8bc76d49a050424fe01bad5e368033eda4a41466bb20176397e78686d15fac', 4290463660, 533835648, 715076352, total_frames=715076352),
        Piece('260621_0132_3-4.wav', '3f80aaabf7357e6848fccbfa75d9d43e0724388126ae88a8d3cc62b1b93c2cb7', 1856824492, 0, 136279296, total_frames=309469824)), 'Sunday 10:30p; provisional schedule projection, not verified performer boundaries. Anchored backward from the approximate Jackson start.'),
)}

# This tuple is authored fixed input, not loaded from callers or external data.
SINGLE_DEFINITIONS = (
    ('choice-friday', 'e89ad04e8f69ad25c47f2f153862087c203dfd0b8fbe53c1a7f7a3119299c073', 4290463660, 5375.645714285714, 12575.645714285714, 'Friday 10:00p; provisional schedule projection, not verified performer boundaries. Uses inferred recorder clock alignment.', 237065976, 554585976, 44100),
    ('sydka-live-friday', 'bc52ca6689a9551f70aaa1742d3066da2b3f21f5628815d43c514d8fc0a0dd17', 4290463660, 1760.762448979592, 7160.762448979592, 'Friday 1:30a; provisional schedule projection, not verified performer boundaries. Uses inferred recorder clock alignment.', 77649624, 315789624, 44100),
    ('jake-mora-friday', 'bc52ca6689a9551f70aaa1742d3066da2b3f21f5628815d43c514d8fc0a0dd17', 4290463660, 7160.762448979592, 12560.762448979593, 'Friday 3:00a; provisional schedule projection, not verified performer boundaries. Uses inferred recorder clock alignment.', 315789624, 553929624, 44100),
    ('artur-saturday', 'f7035c693dc4d95546196fa02357ba6ea5fa144e5eaa627af885d026e905a944', 4290463660, 1745.8791836734695, 7145.879183673469, 'Saturday 6:00a; provisional schedule projection, not verified performer boundaries. Uses inferred recorder clock alignment.', 76993272, 315133272, 44100),
    ('airgordon-saturday', 'f7035c693dc4d95546196fa02357ba6ea5fa144e5eaa627af885d026e905a944', 4290463660, 7145.879183673469, 12545.879183673469, 'Saturday 7:30a; provisional schedule projection, not verified performer boundaries. Uses inferred recorder clock alignment.', 315133272, 553273272, 44100),
    ('barbie-fish-santiago-gammelli-saturday', 'cf1842a175f02bd8ea5afe2dd38ddd8778d26dff8482fb2c9abba1ea920f5ff9', 4290463660, 1730.995918367347, 8930.995918367347, 'Saturday 10:30a; provisional schedule projection, not verified performer boundaries. Uses inferred recorder clock alignment.', 76336920, 393856920, 44100),
    ('pily-saturday', 'cf1842a175f02bd8ea5afe2dd38ddd8778d26dff8482fb2c9abba1ea920f5ff9', 4290463660, 8930.995918367347, 14330.995918367347, 'Saturday 12:30p; provisional schedule projection, not verified performer boundaries. Uses inferred recorder clock alignment.', 393856920, 631996920, 44100),
    ('jay-dee-saturday', '343530f5fa70b004fa05395933f968851fa8b1fb6f646a5bb3b83f4bbd6a7bfd', 4290463660, 4994.416326530612, 10394.416326530612, 'Saturday 5:30p; provisional schedule projection, not verified performer boundaries. Anchored backward from the approximate Jackson start.', 220253760, 458393760, 44100),
    ('adam-rose-miro-saturday', 'f6ea42dab6d80e97c86c08a40a986f53a8538bdb79323b5558f18da67057d010', 4290463660, 1379.5330612244898, 8579.53306122449, 'Saturday 9:00p; provisional schedule projection, not verified performer boundaries. Anchored backward from the approximate Jackson start.', 60837408, 378357408, 44100),
    ('sinead-saturday', 'f6ea42dab6d80e97c86c08a40a986f53a8538bdb79323b5558f18da67057d010', 4290463660, 8579.53306122449, 13979.53306122449, 'Saturday 11:00p; provisional schedule projection, not verified performer boundaries. Anchored backward from the approximate Jackson start.', 378357408, 616497408, 44100),
)


def build_remaining_sources(source_class):
    return {**{spec[0]: source_class(*spec) for spec in SINGLE_DEFINITIONS}, **JOINED_CATALOG}


def reviewed_remaining_joined(value):
    source = JOINED_CATALOG.get(value.get('source_id')) if isinstance(value, dict) else None
    if (source is None or value.get('recognition_mode') != 'resumable'
            or not all(_exact(value.get(k), v) for k, v in source.pins().items())
            or set(value) - (set(source.pins()) | {'source_id', 'recognition_mode', 'source_urls'})):
        raise RuntimeError('fixed_input_mismatch')
    return source


def assemble_remaining(descriptor, originals, destination):
    return _assemble(reviewed_remaining_joined(descriptor), originals, destination)
