"""Optional remote packaging for an XML workflow plist.

The compiler itself is offline. This module reproduces the explicit signing
step used for the earlier test shortcut and only contacts the service when its
function is called by the user.
"""

from __future__ import annotations

import gzip
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

SIGNING_URL = "https://shortcuts.gluebyte.workers.dev/"


class SigningError(RuntimeError):
    """The remote signing service did not return a signed shortcut."""


def sign_xml_plist(xml_plist: bytes, *, timeout_seconds: float = 45.0) -> bytes:
    """Return an AEA1 signed `.shortcut` archive for an XML workflow plist.

    Calling this function uploads only the supplied plist to the third-party
    signing service. Do not pass credentials or private health data into it.
    """
    request = Request(
        SIGNING_URL,
        data=gzip.compress(xml_plist),
        headers={
            "Content-Type": "application/gzip",
            # The signing service rejects urllib's default User-Agent with 403.
            "User-Agent": "py2shortcuts/0.1",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            compressed_shortcut = response.read()
    except HTTPError as error:
        raise SigningError(f"Remote signing returned HTTP {error.code}") from error
    except URLError as error:
        raise SigningError("Remote signing request failed") from error

    try:
        shortcut = gzip.decompress(compressed_shortcut)
    except gzip.BadGzipFile as error:
        raise SigningError("Remote signing response was not a gzip archive") from error
    if not shortcut.startswith(b"AEA1"):
        raise SigningError("Remote signing response was not an AEA1 shortcut archive")
    return shortcut
