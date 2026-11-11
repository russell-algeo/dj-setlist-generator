"""Finite sample-pinned siblings for the reviewed four-gap mean model.

Catalog recognition does not approve execution or release. The database version
registry and shared admission fence must separately approve these exact runs.
All predecessor sources and results remain immutable identities.
"""
from worker.jobs.yoon_highkin_source import Piece, JoinedSource, _exact, _assemble


def build_version_sources(source_class):
    return {s.id: s for s in (
    source_class('airgordon-saturday-mean-gaps-v2', 'f7035c693dc4d95546196fa02357ba6ea5fa144e5eaa627af885d026e905a944', 4290463660, 7085.016099773243, 12485.016099773242, 'User-selected four-gap mean timing model v2; performer boundaries remain schedule-provisional. Nearest-sample half-up conversion; exact rational endpoints retained in provenance. No acoustic verification.', start_frame=312449210, end_frame=550589210, sample_rate=44100),
    source_class('artur-saturday-mean-gaps-v2', 'f7035c693dc4d95546196fa02357ba6ea5fa144e5eaa627af885d026e905a944', 4290463660, 1685.0160997732426, 7085.016099773243, 'User-selected four-gap mean timing model v2; performer boundaries remain schedule-provisional. Nearest-sample half-up conversion; exact rational endpoints retained in provenance. No acoustic verification.', start_frame=74309210, end_frame=312449210, sample_rate=44100),
    source_class('barbie-fish-santiago-gammelli-saturday-mean-gaps-v2', 'cf1842a175f02bd8ea5afe2dd38ddd8778d26dff8482fb2c9abba1ea920f5ff9', 4290463660, 1670.1328344671201, 8870.13283446712, 'User-selected four-gap mean timing model v2; performer boundaries remain schedule-provisional. Nearest-sample half-up conversion; exact rational endpoints retained in provenance. No acoustic verification.', start_frame=73652858, end_frame=391172858, sample_rate=44100),
    source_class('choice-friday-mean-gaps-v2', 'e89ad04e8f69ad25c47f2f153862087c203dfd0b8fbe53c1a7f7a3119299c073', 4290463660, 5314.782630385487, 12514.782630385487, 'User-selected four-gap mean timing model v2; performer boundaries remain schedule-provisional. Nearest-sample half-up conversion; exact rational endpoints retained in provenance. No acoustic verification.', start_frame=234381914, end_frame=551901914, sample_rate=44100),
    JoinedSource('hank-friday-mean-gaps-v2', (Piece('260619_0119_3-4.wav', 'e89ad04e8f69ad25c47f2f153862087c203dfd0b8fbe53c1a7f7a3119299c073', 4290463660, 551901914, 715076352, total_frames=715076352),Piece('260620_0120_3-4.wav', 'bc52ca6689a9551f70aaa1742d3066da2b3f21f5628815d43c514d8fc0a0dd17', 4290463660, 0, 74965562, total_frames=715076352)), 'User-selected four-gap mean timing model v2; performer boundaries remain schedule-provisional. Nearest-sample half-up conversion; exact rational endpoints retained in provenance. No acoustic verification.'),
    JoinedSource('honeydu-saturday-mean-gaps-v2', (Piece('260620_0120_3-4.wav', 'bc52ca6689a9551f70aaa1742d3066da2b3f21f5628815d43c514d8fc0a0dd17', 4290463660, 551245562, 715076352, total_frames=715076352),Piece('260620_0121_3-4.wav', 'f7035c693dc4d95546196fa02357ba6ea5fa144e5eaa627af885d026e905a944', 4290463660, 0, 74309210, total_frames=715076352)), 'User-selected four-gap mean timing model v2; performer boundaries remain schedule-provisional. Nearest-sample half-up conversion; exact rational endpoints retained in provenance. No acoustic verification.'),
    JoinedSource('hunter-foshee-saturday-mean-gaps-v2', (Piece('260620_0121_3-4.wav', 'f7035c693dc4d95546196fa02357ba6ea5fa144e5eaa627af885d026e905a944', 4290463660, 550589210, 715076352, total_frames=715076352),Piece('260620_0122_3-4.wav', 'cf1842a175f02bd8ea5afe2dd38ddd8778d26dff8482fb2c9abba1ea920f5ff9', 4290463660, 0, 73652858, total_frames=715076352)), 'User-selected four-gap mean timing model v2; performer boundaries remain schedule-provisional. Nearest-sample half-up conversion; exact rational endpoints retained in provenance. No acoustic verification.'),
    source_class('jake-mora-friday-mean-gaps-v2', 'bc52ca6689a9551f70aaa1742d3066da2b3f21f5628815d43c514d8fc0a0dd17', 4290463660, 7099.899365079365, 12499.899365079365, 'User-selected four-gap mean timing model v2; performer boundaries remain schedule-provisional. Nearest-sample half-up conversion; exact rational endpoints retained in provenance. No acoustic verification.', start_frame=313105562, end_frame=551245562, sample_rate=44100),
    source_class('pily-saturday-mean-gaps-v2', 'cf1842a175f02bd8ea5afe2dd38ddd8778d26dff8482fb2c9abba1ea920f5ff9', 4290463660, 8870.13283446712, 14270.13283446712, 'User-selected four-gap mean timing model v2; performer boundaries remain schedule-provisional. Nearest-sample half-up conversion; exact rational endpoints retained in provenance. No acoustic verification.', start_frame=391172858, end_frame=629312858, sample_rate=44100),
    source_class('sydka-live-friday-mean-gaps-v2', 'bc52ca6689a9551f70aaa1742d3066da2b3f21f5628815d43c514d8fc0a0dd17', 4290463660, 1699.899365079365, 7099.899365079365, 'User-selected four-gap mean timing model v2; performer boundaries remain schedule-provisional. Nearest-sample half-up conversion; exact rational endpoints retained in provenance. No acoustic verification.', start_frame=74965562, end_frame=313105562, sample_rate=44100),
    )}


def reviewed_version_source(value, catalog):
    source = catalog.get(value.get('source_id')) if isinstance(value, dict) else None
    locator = 'source_urls' if isinstance(source, JoinedSource) else 'source_url'
    if (source is None or value.get('recognition_mode') != 'resumable'
            or not all(_exact(value.get(k), v) for k, v in source.pins().items())
            or set(value) - (set(source.pins()) | {'source_id', 'recognition_mode', locator})):
        raise RuntimeError('fixed_version_input_mismatch')
    return source


def assemble_version(descriptor, originals, destination, catalog):
    source = reviewed_version_source(descriptor, catalog)
    if not isinstance(source, JoinedSource):
        raise RuntimeError('fixed_version_input_mismatch')
    return _assemble(source, originals, destination)

VERSION_ENRICHMENT_RUNS = {'31d068aa-1d30-5018-9b93-c01ddfaf3fd7': {'source_id': 'artur-saturday-mean-gaps-v2',
                                          'submission_id': '813d36ae-a097-51ff-ac83-3fd7575bfaaf',
                                          'target_set_id': '8a3804db-90e9-5afa-b65e-02c22526826e'},
 '42022ca4-f217-53b9-b31b-88046e4fe106': {'source_id': 'jake-mora-friday-mean-gaps-v2',
                                          'submission_id': '0a6b1720-9bd6-513f-9f19-b3b21f7eb571',
                                          'target_set_id': 'fac7dd34-e762-5696-a056-94a195055f25'},
 '54a97b8c-157a-5ea7-b64a-d0351e737d4e': {'source_id': 'airgordon-saturday-mean-gaps-v2',
                                          'submission_id': '7aa4c603-c82b-5cf3-a811-f1ee2aa5979b',
                                          'target_set_id': 'ef5f147f-f403-56bb-a5ac-9b585906c02e'},
 '802964dd-5976-5d0d-85cc-71dbaca129ab': {'source_id': 'hank-friday-mean-gaps-v2',
                                          'submission_id': 'ec02a2f5-2526-58b9-8c76-8078251a788c',
                                          'target_set_id': 'dc8a5ee0-2f1b-5022-991b-31f5aac16ba1'},
 '827423fa-6a5a-5567-a5ca-6859b0a44310': {'source_id': 'pily-saturday-mean-gaps-v2',
                                          'submission_id': 'd7bfe57d-ceae-54e1-a91e-473f27f33317',
                                          'target_set_id': 'ad408430-388c-512f-a4f8-277ad83dd0f7'},
 'a8102221-e559-53df-a680-7f0299aaec47': {'source_id': 'barbie-fish-santiago-gammelli-saturday-mean-gaps-v2',
                                          'submission_id': 'ab1715a9-e5ef-584f-bc66-487455d0bc73',
                                          'target_set_id': '4311c755-7012-5a00-b0c7-729fe982223b'},
 'b38d2fb4-21a2-5570-b0d5-50dac12c9099': {'source_id': 'honeydu-saturday-mean-gaps-v2',
                                          'submission_id': '53b9cb68-add5-56d1-bcbe-ec38ae69794c',
                                          'target_set_id': '32d52955-0b61-5d55-afae-c40ba65305d8'},
 'd9f58e84-7d4e-599d-92c8-b894cc867e50': {'source_id': 'choice-friday-mean-gaps-v2',
                                          'submission_id': '11968f9e-56c6-5108-ae46-a27c29b9272a',
                                          'target_set_id': '4c38a89c-288a-59b5-a4f0-ef0fd3362116'},
 'defa8bf1-5443-51bf-bfda-8b20969e9f9a': {'source_id': 'sydka-live-friday-mean-gaps-v2',
                                          'submission_id': '005f65c6-ebed-5cbf-b6bd-8083b469902c',
                                          'target_set_id': '2caf5a88-a4c2-582f-89ae-1c7fbb21ebaa'},
 'f7ceea97-b612-5dbd-9e7f-44776b6dedd9': {'source_id': 'hunter-foshee-saturday-mean-gaps-v2',
                                          'submission_id': 'c85047cc-eb0c-561f-a7ad-9610c807716e',
                                          'target_set_id': 'e788dc31-017d-5660-88ea-c559c0f3727a'}}
