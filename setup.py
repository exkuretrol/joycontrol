
from setuptools import setup, find_packages

setup(name='joycontrol',
      version='0.16',
      author='Robert Martin',
      author_email='martinro@informatik.hu-berlin.de',
      description='Emulate Nintendo Switch Controllers over Bluetooth',
      packages=find_packages(),
      package_data={'joycontrol': ['profile/sdp_record_hid.xml']},
      zip_safe=False,
      python_requires='>=3.9',
      install_requires=[
          'hid',
          'aioconsole',
          'crc8',
          'prompt-toolkit',
          # dbus-python must come from the distro package (python3-dbus) on most
          # systems because it links against system libraries — pip-installing it
          # often fails. We list it here for completeness; install with apt if pip fails.
          'dbus-python',
      ]
      )
