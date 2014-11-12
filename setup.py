from setuptools import setup

setup(name='Twilight',
      version='1.0',
      description='Python WSGI server to show sun and moon ephemerides',
      author='Erik Sigurd Young',
      author_email='sigurd@lambda-conspiracy.net',
      url='https://github.com/lambda-conspiracy/wsgi-twilight.git',
      install_requires=['Flask>=0.7.2', 'MarkupSafe', 'python-dateutil', 'DateTime', 'ephem', 'geocoder', 'arrow'],
     )
