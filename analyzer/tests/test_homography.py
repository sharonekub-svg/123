"""Homography correctness: corner reprojection + propagation. Run directly."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import homography as hg  # noqa: E402


if __name__ == "__main__":
    hg._selftest()
    print("homography tests OK")
