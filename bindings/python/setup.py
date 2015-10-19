import os

from distutils.core import setup
import distutils.file_util

os.chdir(os.path.dirname(os.path.abspath(__file__)))


orig_copy_file = distutils.file_util.copy_file


def copy_file(
    src,
    dst,
    preserve_mode=1,
    preserve_times=1,
    update=0,
    link=None,
    verbose=1,
    dry_run=0,
):
    libexecdir = os.environ['LIBEXECDIR']
    bindir = os.environ['BINDIR']
    orig_copy_file(
        src,
        dst,
        preserve_mode,
        preserve_times,
        update,
        link,
        verbose,
        dry_run,
    )

    with open(dst, "rb") as target:
        data = target.read()

    data = data.replace("@LIBEXECDIR@", libexecdir)
    data = data.replace("@BINDIR@", bindir)

    with open(dst, "wb") as target:
        target.write(data)

distutils.file_util.copy_file = copy_file

setup(
    name='ioprocess',
    version=os.getenv('VERSION').strip(),
    description='Creates a subprocess in simpler safer manner',
    license="GNU GPLv2+",
    author='Saggi Mizrahi',
    author_email='ficoos@gmail.com',
    url='github.com/ficoos/ioprocess',
    packages=['ioprocess'],
)
