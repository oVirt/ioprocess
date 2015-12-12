import os

from distutils.core import setup

os.chdir(os.path.dirname(os.path.abspath(__file__)))

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
