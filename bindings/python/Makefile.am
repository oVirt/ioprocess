EXTRA_DIST = $(srcdir)/ioprocess/config.py.in \
			 $(srcdir)/setup.py.in \
			 $(srcdir)/test/*.py \
			 $(srcdir)/tox.ini \
			 $(NULL)

all-local: $(srcdir)/ioprocess/config.py

check-local:
	tox

dist-hook:
	mkdir -p $(distdir)/tmp
	cp -R $(srcdir)/* $(distdir)/tmp
	rm -f $(distdir)/tmp/ioprocess/config.py  # Must be regenerated
	chmod -R a+rw $(distdir)/tmp
	$(PYTHON) $(distdir)/tmp/setup.py --verbose sdist --dist-dir "`readlink -f $(distdir)`"
	rm -rf $(distdir)/tmp
	tar -xvf $(distdir)/ioprocess-$(VERSION).tar* -C "$(distdir)" --strip-components=1
	rm $(distdir)/ioprocess-$(VERSION).tar*

install-data-local:
	$(PYTHON) "$(srcdir)/setup.py" build -b "`readlink -f $(builddir)`" install --root "$(DESTDIR)/" --prefix "$(prefix)" clean -a

uninstall-local:
	rm -r `$(PYTHON) -c 'from distutils import sysconfig; print(sysconfig.get_python_lib(0,0,"$(DESTDIR)${prefix}"))'`/ioprocess*

$(srcdir)/ioprocess/config.py: $(srcdir)/ioprocess/config.py.in
	sed -e "s,[@]IOPROCESS_DIR[@],$(IOPROCESS_DIR),g" \
		-e "s,[@]TASKSET_PATH[@],$(TASKSET_PATH),g" \
		$< > $@
