import sys
import os

# Ensure src/ is on the path so both mzmlpy and mzx are importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
