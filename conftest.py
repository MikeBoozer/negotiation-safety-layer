"""Make the project root importable so `import nsl` / `import counterparties`
work under pytest without an editable install."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
