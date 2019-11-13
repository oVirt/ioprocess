#!/bin/bash -xe

# enable complex globs
shopt -s extglob

# On Fedora 30 and CentOS 8 pip installs scripts to /usr/local/bin which may
# not be in PATH.
export PATH="/usr/local/bin:$PATH"

# First upgrade pip, since older pip versions have issues with installing
# correct version of requirements.
${CI_PYTHON} -m pip install --upgrade pip

# Install development requirements.
${CI_PYTHON} -m pip install --upgrade tox

automation/setup.sh

make check

automation/build-artifacts.sh

dnf install exported-artifacts/!(*.src).rpm
