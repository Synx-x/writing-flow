"""Keep tests and hook subprocesses inside a private temporary sandbox."""
import os
import shutil
import tempfile
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

_REAL_TMP = Path(tempfile.gettempdir())
_SANDBOX = Path(tempfile.mkdtemp(prefix="writing-flow-tests-"))
for _var in ("TMPDIR", "TEMP", "TMP"):
    os.environ[_var] = str(_SANDBOX)
tempfile.tempdir = str(_SANDBOX)
for _var in [name for name in os.environ if name.startswith(("WRITING_FLOW_", "HARNESS_KIT_"))]:
    os.environ.pop(_var, None)
os.environ["WRITING_FLOW_STATE_DIR"] = str(_SANDBOX / "state")
os.environ["WRITING_FLOW_CONFIG"] = str(_SANDBOX / "config.json")
os.environ["WRITING_FLOW_LOCAL_DIR"] = str(_SANDBOX / "writing-flow-local")

import pytest

@pytest.fixture(autouse=True)
def _restore_environ():
    saved = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(saved)


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_SANDBOX, ignore_errors=True)
