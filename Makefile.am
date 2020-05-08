#
# Copyright 2013 Saggi Mizrahi.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA
#
# Refer to the README and COPYING files for full details of the license
#

SUBDIRS = src bindings

.PHONY: srpm rpm

OUTDIR = $(PWD)/build/out
RPMDIR = $(PWD)/build/rpm

srpm: dist
	rpmbuild --define="_topdir $(RPMDIR)" \
		--define="_srcrpmdir $(OUTDIR)" \
		-ts $(DIST_ARCHIVES)

rpm: srpm
	rpmbuild --define="_topdir $(RPMDIR)" \
		-rb "$(OUTDIR)"/ioprocess-*.src.rpm
	mv "$(RPMDIR)"/RPMS/*/* "$(OUTDIR)"

EXTRA_DIST = ioprocess.spec.in \
	     ioprocess.spec \
	     README.md \
	     BUILD.md \
	     $(NULL)

CLEANFILES = ioprocess.spec \
	     $(NULL)

all-local: ioprocess.spec \
	   $(NULL)

clean-local:
	-rm -rf build
