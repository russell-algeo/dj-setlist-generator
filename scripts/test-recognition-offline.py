"""Run repository Python regressions without provider, DNS or live DB access."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
with patch('socket.socket.connect', side_effect=AssertionError('network forbidden in offline tests')), \
     patch('socket.getaddrinfo', side_effect=AssertionError('DNS forbidden in offline tests')), \
     patch('psycopg.connect', side_effect=AssertionError('live DB forbidden in offline tests')):
    suite = unittest.defaultTestLoader.discover('tests')
    result = unittest.TextTestRunner(verbosity=1).run(suite)
raise SystemExit(not result.wasSuccessful())
