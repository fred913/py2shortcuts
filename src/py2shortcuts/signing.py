"""Optional remote packaging for an XML workflow plist.

The compiler itself is offline. This module reproduces the explicit signing
step used for the earlier test shortcut and only contacts the service when its
function is called by the user.
"""

from __future__ import annotations

from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

SIGNING_URL = "https://py2scsign.pb.sheng.fan:8443/v1/sign"
SIGNING_TOKEN = "e2a97115b95dd75b1f0b7bb7fb95e1b2e8dd1af635bc2ae2295ab3502df5d027"


class SigningError(RuntimeError):
    """The remote signing service did not return a signed shortcut."""


def sign_xml_plist(xml_plist: bytes, *, timeout_seconds: float = 45.0) -> bytes:
    """Return an AEA1 signed `.shortcut` archive for an XML workflow plist.

    Calling this function uploads the supplied plist to the configured signing
    service. The current deployment token is intentionally embedded for local
    development and should be rotated before this package is distributed.
    """
    request = Request(
        SIGNING_URL,
        data=xml_plist,
        headers={
            "Authorization": f"Bearer {SIGNING_TOKEN}",
            "Content-Type": "application/x-plist",
            "User-Agent": "py2shortcuts/0.1",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            shortcut = response.read()
    except HTTPError as error:
        raise SigningError(
            f"Remote signing returned HTTP {error.code}, message: {error.msg}"
        ) from error
    except URLError as error:
        raise SigningError("Remote signing request failed") from error

    if not shortcut.startswith(b"AEA1"):
        raise SigningError("Remote signing response was not an AEA1 shortcut archive")
    return shortcut
