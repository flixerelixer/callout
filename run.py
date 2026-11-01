"""Start FragSubs from a source checkout (also the PyInstaller entry point)."""

import multiprocessing
import sys

from fragsubs.app import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
