"""Make the project's top-level modules importable from tests/ without a build."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
