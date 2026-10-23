# -*- coding: utf-8 -*-
"""Lanzador sin consola para Windows."""
import sys

from rolmerbet.ui import run

if __name__ == "__main__":
    run(auto="--auto" in sys.argv)

