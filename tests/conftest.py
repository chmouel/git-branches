import os
import sys

# Ensure the package root (containing git_branch_list) is on sys.path
PACKAGE_ROOT = os.path.dirname(os.path.dirname(__file__))
if PACKAGE_ROOT not in sys.path:
    sys.path.insert(0, PACKAGE_ROOT)
