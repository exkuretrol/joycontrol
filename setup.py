
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
          'crc8',
          'prompt-toolkit',
          # NOTE: dbus-python is intentionally NOT listed here. It links
          # against system libraries and pip-building it from source needs
          # a C toolchain plus dbus-devel/glib-devel headers, which is
          # painful to set up in a venv. Use the distro package
          # (`python3-dbus` on apt, `python3-dbus` on dnf) and create the
          # project venv with `--system-site-packages` so it's visible.
      ]
      )
