#!/bin/bash -xe

# enable complex globs
shopt -s extglob

automation/setup.sh

# tox on el7 is too old
pip install "more-itertools<6.0.0" tox

make check

automation/build-artifacts.sh

if grep -q 'Fedora' /etc/redhat-release; then
    DNF=dnf
else
    DNF=yum
fi

"$DNF" install exported-artifacts/!(*.src).rpm
