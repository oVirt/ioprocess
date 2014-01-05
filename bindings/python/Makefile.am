SUBDIRS = ioprocess

check-local:
	nosetests test/test.py

dist-hook:
	$(PYTHON) setup.py sdist
	tar -xvf dist/ioprocess-*.tar* -C $(distdir) --strip-components=1

install-data-local:
	$(PYTHON) ./setup.py install --prefix $(prefix)
