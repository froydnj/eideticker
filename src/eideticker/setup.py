from setuptools import setup, find_packages
setup(
    name = "eideticker",
    version = "0.1.0",
    packages = find_packages(),
    install_requires = [ 'mozdevice', 'BeautifulSoup', 'gaiatest', 'httplib2' ]
)

# FIXME: Compile decklink-capture script automatically
