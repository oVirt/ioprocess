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

TMPREPOS = tmp.repos
RPMBUILD_ARGS := --define="_topdir `pwd`/$(TMPREPOS)"
RPMBUILD_ARGS += $(if $(RELEASE_SUFFIX),--define="release_suffix $(RELEASE_SUFFIX)")

srpm: dist
	rm -rf "$(TMPREPOS)"
	mkdir -vp $(TMPREPOS)/{SPECS,RPMS,SRPMS,SOURCES}
	rpmbuild $(RPMBUILD_ARGS) -ts $(distdir).tar.gz

rpm: srpm
	rpmbuild $(RPMBUILD_ARGS) --rebuild "$(TMPREPOS)"/SRPMS/*.src.rpm
	@echo
	@echo "rpm available at '$(TMPREPOS)'"
	@echo

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
	-rm -rf build tmp.repos
