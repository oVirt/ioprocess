#!/bin/bash -xe

outdir=$PWD/exported-artifacts

automation/setup.sh
make rpm OUTDIR=$outdir
mv ioprocess-*.tar.gz $outdir
