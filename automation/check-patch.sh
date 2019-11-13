#!/bin/bash -xe

# enable complex globs
shopt -s extglob

automation/setup.sh

# tox on el7 is too old
${CI_PYTHON} -m pip install "more-itertools<6.0.0" tox
export PATH="${PATH}:/usr/local/bin"

make check

automation/build-artifacts.sh

dnf install exported-artifacts/!(*.src).rpm
