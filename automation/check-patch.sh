#!/bin/bash -xe

automation/setup.sh

# tox on el7 is too old
pip install tox

make check
