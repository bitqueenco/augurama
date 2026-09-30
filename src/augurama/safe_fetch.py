"""Bounded HTTPS downloads with DNS pinning, redirect revalidation and no ambient credentials."""
from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
from urllib.parse import urljoin, urlsplit

from .errors import DirectorError


class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host: str, ip: str):
        super().__init__(host, 443, timeout=30, context=ssl.create_default_context())
        self.pinned_ip = ip

    def connect(self):
        sock = socket.create_connection((self.pinned_ip, 443), timeout=self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def public_destination(url: str) -> tuple[str, str, str]:
    try:
        u = urlsplit(url)
        if u.scheme != "https" or not u.hostname or u.username or u.password or u.fragment or u.port not in (None, 443) or "\\" in url or any(ord(c) < 32 for c in url):
            raise ValueError()
        host = u.hostname.encode("idna").decode("ascii").lower()
        if host.endswith(".") or host in ("localhost", "metadata.google.internal"):
            raise ValueError()
        addresses = {r[4][0] for r in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
        if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
            raise ValueError()
        path = (u.path or "/") + ("?" + u.query if u.query else "")
        return host, sorted(addresses)[0], path
    except (ValueError, UnicodeError, OSError):
        raise DirectorError("UNSAFE_MEDIA_URL", "Media must use a public HTTPS URL on port 443, without credentials or local/private addresses.") from None


class SafeFetcher:
    def download(self, url: str, limit: int) -> tuple[bytes, str]:
        current = url
        for _ in range(4):
            host, ip, path = public_destination(current)
            connection = PinnedHTTPS(host, ip)
            try:
                connection.request("GET", path, headers={"User-Agent": "CorgiVerse-Director/0.1", "Accept-Encoding": "identity", "Accept": "image/*,video/*,audio/*,application/octet-stream"})
                response = connection.getresponse()
                if response.status in (301, 302, 303, 307, 308):
                    location = response.getheader("Location")
                    if not location:
                        raise DirectorError("MEDIA_DOWNLOAD_FAILED", "Media redirect had no destination.", 502)
                    current = urljoin(current, location)
                    continue
                if response.status != 200:
                    raise DirectorError("MEDIA_DOWNLOAD_FAILED", f"Media source returned HTTP {response.status}. Reattach the file if its URL expired.", 502)
                if response.getheader("Content-Encoding", "identity").lower() != "identity":
                    raise DirectorError("MEDIA_ENCODING_REJECTED", "Compressed HTTP media responses are not accepted.")
                size = response.getheader("Content-Length")
                if size and (not size.isdigit() or int(size) > limit):
                    raise DirectorError("MEDIA_TOO_LARGE", "The media exceeds the upload limit.", 413)
                result = bytearray()
                while True:
                    chunk = response.read(min(65536, limit + 1 - len(result)))
                    if not chunk:
                        break
                    result.extend(chunk)
                    if len(result) > limit:
                        raise DirectorError("MEDIA_TOO_LARGE", "The media exceeds the upload limit.", 413)
                return bytes(result), response.getheader("Content-Type", "application/octet-stream").split(";")[0]
            except DirectorError:
                raise
            except (OSError, http.client.HTTPException):
                raise DirectorError("MEDIA_DOWNLOAD_FAILED", "The media download failed. Reattach the file or retry the import; no generation was submitted.", 502) from None
            finally:
                connection.close()
        raise DirectorError("MEDIA_REDIRECT_LIMIT", "Too many media redirects.", 502)
