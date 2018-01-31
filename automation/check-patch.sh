#!/bin/bash -xe

# enable complex globs
shopt -s extglob

automation/setup.sh

# tox on el7 is too old
pip install tox

make check

automation/build-artifacts.sh

yum install exported-artifacts/!(*.src).rpm
