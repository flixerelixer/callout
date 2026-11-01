import os
import sys
import time
import uuid

import pytest

pytest.importorskip("PySide6.QtNetwork")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.mark.skipif(sys.platform == "win32", reason="Windows uses the mutex path; covered by the CI build")
def test_second_launch_finds_the_first_and_shows_it():
    from PySide6.QtCore import QCoreApplication

    from fragsubs.single_instance import SingleInstance

    app = QCoreApplication.instance() or QCoreApplication([])
    name = f"fragsubs-test-{uuid.uuid4().hex[:8]}"
    first = SingleInstance(name)
    assert not first.already_running()
    shown = []
    first.listen(lambda: shown.append(True))

    second = SingleInstance(name)
    assert second.already_running()
    assert second.show_running_instance()
    end = time.time() + 2
    while time.time() < end and len(shown) < 2:
        app.processEvents()
        time.sleep(0.01)
    assert shown  # the running copy was asked to show its window
