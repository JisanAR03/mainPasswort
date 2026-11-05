"""Reference implementation of the vault format, used only by the tests.

The product is the browser extension in extension/. This package is the Python
code the extension is checked against: it reads and writes the same KDBX vaults
with pykeepass, and holds the original sync decision table and URL matching
rules. Nothing here ships or runs outside the test suite.
"""

__version__ = "0.1.0"
