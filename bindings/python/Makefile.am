EXTRA_DIST = \
    $(NULL)

check-local:
	nosetests $(srcdir)/test/test.py

dist-hook:
	mkdir -p $(distdir)/tmp
	cp -R $(srcdir)/* $(distdir)/tmp
	chmod -R a+rw $(distdir)/tmp
	LIBEXECDIR="$(libexecdir)" VERSION=$(VERSION) $(PYTHON) $(distdir)/tmp/setup.py --verbose sdist --dist-dir "`readlink -f $(distdir)`" --manifest "`readlink -f $(distdir)`/MANIFEST"
	rm -rf $(distdir)/tmp
	tar -xvf $(distdir)/ioprocess-$(VERSION).tar* -C "$(distdir)" --strip-components=1
	rm $(distdir)/ioprocess-$(VERSION).tar*

install-data-local:
	LIBEXECDIR="$(libexecdir)" VERSION="$(VERSION)" "$(PYTHON)" "$(srcdir)/setup.py" build -b "`readlink -f $(builddir)`" install --root "$(DESTDIR)/" --prefix "$(prefix)" clean -a

uninstall-local:
	rm -r `python -c 'from distutils import sysconfig; print sysconfig.get_python_lib(0,0,"$(DESTDIR)${prefix}")'`/ioprocess*
