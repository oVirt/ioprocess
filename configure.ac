#                                               -*- Autoconf -*-
# Process this file with autoconf to produce a configure script.

AC_PREREQ([2.6])
AC_INIT([ioprocess], [1.4.1], [nsoffer@redhat.com])
AC_CONFIG_AUX_DIR([build-aux])
AC_CONFIG_SRCDIR([src/])
AC_CONFIG_HEADERS([config.h])

AC_SUBST(RELEASE, 1)
AC_SUBST([RELEASE_SUFFIX], [m4_esyscmd([build-aux/release-suffix])])
AM_INIT_AUTOMAKE([-Wno-portability])

AC_ARG_ENABLE(debug,
              [  --enable-debug          Enable debugging information],
              USE_DEBUG="$enableval", USE_DEBUG="no")

# Checks for programs.
AC_PROG_CC
AC_PROG_CC_C99
IOPROCESS_CFLAGS="--pedantic -Wall -Wextra -Werror -Wno-missing-field-initializers -D__STDC_FORMAT_MACROS -D_GNU_SOURCE"

if test $USE_DEBUG = yes ; then
	DEBUG=1
	IOPROCESS_CFLAGS+=" -g -O0"
else
	DEBUG=0
fi

AC_SUBST([IOPROCESS_CFLAGS])
AM_PATH_PYTHON([3])

# Checks for header files.
AC_CHECK_HEADERS([fcntl.h limits.h stdint.h stdlib.h string.h sys/statvfs.h unistd.h])

# Checks for typedefs, structures, and compiler characteristics.
AC_TYPE_SIZE_T
AC_TYPE_UINT64_T

# Checks for library functions.
AC_FUNC_LSTAT_FOLLOWS_SLASHED_SYMLINK
AC_FUNC_MALLOC
AC_CHECK_FUNCS([getpagesize memset mkdir rmdir])

PKG_CHECK_MODULES(GLIB2, [glib-2.0])
PKG_CHECK_MODULES(GTHREAD2, [gthread-2.0])

AC_CHECK_LIB([yajl], [yajl_alloc], [AC_SUBST(YAJL_CFLAGS, "-DYAJL_VERSION=1")
                                    AC_SUBST(YAJL_LIBS, "-lyajl")],
                                   [AC_MSG_ERROR([yajl library is missing])])
AC_CHECK_LIB([yajl], [yajl_config], [AC_SUBST(YAJL_CFLAGS, "-DYAJL_VERSION=2")], [])
AC_CHECK_HEADERS([yajl/yajl_parse.h], [], [AC_MSG_ERROR([yajl headers missing])])
AC_CHECK_HEADERS([yajl/yajl_gen.h], [], [AC_MSG_ERROR([yajl headers missing])])

AC_SUBST([IOPROCESS_DIR], ['${libexecdir}'])
AC_PATH_PROG([TASKSET_PATH], [taskset], [/usr/bin/taskset])

AC_OUTPUT([Makefile
           ioprocess.spec
           .ycm_extra_conf.py
           bindings/Makefile
           bindings/python/Makefile
           bindings/python/setup.py
           src/Makefile])
