# How to build ioprocess

This document is for ioprocess maintainers building iprocess for Fedora
and RHEL.

See this url to find the maintainers:
https://admin.fedoraproject.org/pkgdb/package/rpms/ioprocess/


## Versioning

This project uses the form:

    MAJOR.MINOR.PATCH-RELEASE

- Bump the MAJOR version when you make incompatible API changes
- Bump the MINOR version when you add functionality in a
  backwards-compatible manner
- Bump the PATCH version when you make backwards-compatible bug fixes
- Bump the RELEASE version for each build from the same tarball. The
  tarball must not change between builds.
  See https://bugzilla.redhat.com/1287946


## Creating a release

1. Create a release branch

    git checkout -b ioprocess-0.16

2. Create a tag for this release

    git tag -a v0.16.1

3. Bump the MINOR version on the master branch

    # configure.ac
    AC_INIT([ioprocess], [0.17.0], [nsoffer@redhat.com])

Notes:
- Note that the development PATCH version is always 0. The first release
  will have PATCH version 1, the second 2, and so on.
- Once a release branch is created, only bug fixes should be added to
  the release branch.
- Any change must be added to the master version *before* adding it to
  the release branch.
- The master branch version must always be greater than the release
  version: for example: 0.17.0 > 0.16.1


## Build source rpm from ioprocess repository

    git checkout v0.15.1
    git clean -dxf
    ./autogen.sh --system
    ./configure
    make
    make rpm


## Building for Fedora

### Installing dependencies

    dnf install fedpkg

### Cloning the build repository

    fedpkg clone ioprocess

### Initializing Kerberos authentication

To use fedpkg, you must use kinit:

    kinit fedora-username@FEDORAPROJECT.ORG

Enter your password for Fedora acount when asked.

### Creating scratch build

This must be done for each dist you want to build this version for.

    fedpkg --dist f24 scratch-build --srpm ~/rpmbuild/SRPMS/ioprocess-0.15.1-1.fc22.src.rpm

### Creating build

    fedpkg switch-branch f22
    fedpkg import ~/rpmbuild/SRPMS/ioprocess-0.15.1-1.fc22.src.rpm
    fedpkg commit
    (Write commit message, e.g. Import v0.15.1)
    fedpkg push
    fedpkg build
    fedpkg update (except master branch)

This must be repeated for all the distribution branches that should have
this version.

Koji master branch should keep master branch (e.g. 0.17), other branches
(e.g. f24) should have the release branches (e.g. 0.16).

### Testing new packages

Builds for stable branches will added first to Fedora update-testing
repository. After users test the new packages and give karma, or after
some time, the package will move into the stable branch.

When creating a new build, send mail to devel@ovirt.org and
users@ovirt.org, and ask people to test the packages and give karma.

Users can use this url for adding karma to packages:
https://bodhi.fedoraproject.org/updates/?packages=ioprocess


## Building for RHEL

### Installing dependencies

    dnf install rhpkg

This seems to be internal Red Hat tool, so you need to add the RCM
repository to get it. Ask release-eng for the details.

### Creating a release branch

Ask release-eng to create the release branch.

### Initializing Kerberos authentication

To use rhpkg, you must use kinit:

    kinit redhat-username@REDHAT.COM

Enter your password for Red Hat acount when asked.

### Creating scratch build

This must be done for each dist you want to build this version for.

    rhpkg --dist rhevm-4.0-rhel-7 scratch-build --srpm ~/rpmbuild/SRPMS/ioprocess-0.15.1-1.fc22.src.rpm

### Creating build

    rhpkg switch-branch rhevm-4.0-rhel-7
    rhpkg import ~/rpmbuild/SRPMS/ioprocess-0.15.1-1.fc22.src.rpm
    rhpkg commit
    (Write commit message, e.g. Import 0.15.1)
    rhpkg push
    rhpkg build

This must be repeated for all the distribution branches that should have
this version.

Brew master branch is not used.

### Errata

New builds should be added to the errata.


## Reference

Please check these documents for more info
- [Packaing guidelines](https://fedoraproject.org/wiki/Packaging:Guidelines)
- [Using the Koji build system](https://fedoraproject.org/wiki/Using_the_Koji_build_system)
