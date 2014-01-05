from distutils.core import setup

setup(name='ioprocess',
      version=open('VERSION').read().strip(),
      description='Creates a subprocess in simpler safer manner',
      license="GNU GPLv2+",
      author='Saggi Mizrahi',
      author_email='ficoos@gmail.com',
      url='github.com/ficoos/ioprocess',
      packages=['ioprocess'])
