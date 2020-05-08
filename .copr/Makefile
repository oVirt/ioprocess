# copr build script
#
# The makefile is called as:
# make -f <cloned_repodir>/.copr/Makefile srpm outdir="<outdir>" spec="<spec_path>"
#
# See https://docs.pagure.org/copr.copr/user_documentation.html#make-srpm

srpm:
	dnf -y install $(shell cat automation/build-artifacts.packages.fc30)
	./autogen.sh --system
	./configure
	$(MAKE) srpm OUTDIR=$(outdir)
