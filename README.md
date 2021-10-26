# IOProcess
[![Copr build status](https://copr.fedorainfracloud.org/coprs/ovirt/ovirt-master-snapshot/package/ioprocess/status_image/last_build.png)](https://copr.fedorainfracloud.org/coprs/ovirt/ovirt-master-snapshot/package/ioprocess/)

## Why?

When performing IO over network storage (specifically NFS) the process might get stuck in D state.
To prevent you main process from becoming unkillable you might prefer to have a slave process do all the risky IO.
This is what ioprocess is for.


## Goals
- Small memory footprint per call.
- Extensible
- Easy integration with python and other languages.


## Hacking

To install required packages on rpm based system:

    dnf builddep ioprocess

For python binding tests you will need tox; python-tox is too old on
some systems, but you can get a recent version using pip:

    pip install tox
