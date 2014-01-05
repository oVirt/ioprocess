# Copyright 2012 Red Hat, Inc. and/or its affiliates.
#
# Licensed to you under the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.  See the files README and
# LICENSE_GPL_v2 which accompany this distribution.

libexec_PROGRAMS = ioprocess
ioprocessdir = .

ioprocess_CFLAGS = $(GLIB2_CFLAGS) \
		   $(GTHREAD2_CFLAGS) \
		   $(YAJL_CFLAGS) \
		   $(NULL)
ioprocess_LDFLAGS = $(GLIB2_LIBS) \
		    $(GTHREAD2_LIBS) \
		    $(YAJL_LIBS) \
		    $(NULL)

ioprocess_SOURCES = \
	json-dom.c \
	json-dom-generator.c \
	json-dom-parser.c \
	exported-functions.c \
	ioprocess.c

noinst_HEADERS = \
	exported-functions.h \
	json-dom.h \
	json-dom-generator.h \
	json-dom-parser.h \
        $(NULL)
