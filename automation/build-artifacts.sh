#!/bin/bash -xe

automation/setup.sh
make rpm

# Keep exisiting directory so we can easily test this localy with all
# environments.
mkdir -p exported-artifacts

mv rpmbuild/SRPMS/*.rpm exported-artifacts
mv rpmbuild/RPMS/*/*.rpm exported-artifacts
mv *.tar.gz exported-artifacts
