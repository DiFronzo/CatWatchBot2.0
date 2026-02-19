#!/bin/sh
cd "$(dirname "$0")"
. pyvenv/bin/activate
python plotter.py
# python uploadplot.py