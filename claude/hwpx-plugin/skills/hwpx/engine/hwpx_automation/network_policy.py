# SPDX-License-Identifier: Apache-2.0
"""Default-deny SSRF policy for outbound HWPX HTTP clients."""

from __future__ import annotations

import ipaddress
import socket
import ssl
from dataclasses import dataclass
from http.client import HTTPConnection, HTTPSConnection
from urllib.parse import urljoin, urlsplit
from urllib.request import (
    HTTPHandler,
    HTTPRedirectHandler,
    HTTPSHandler,
    OpenerDirector,
    Request,
    build_opener,
)

from .configuration import canonical_env_name, env_value, legacy_env_name


ALLOW_PRIVATE_NETWORK_ENV = canonical_env_name("ALLOW_PRIVATE_NETWORK")
LEGACY_ALLOW_PRIVATE_NETWORK_ENV = legacy_env_name("ALLOW_PRIVATE_NETWORK")


class NetworkPolicyError(ValueError):
    code = "NETWORK_DESTINATION_DENIED"

    def __init__(self, message: str, *, reason: str) -> None:
        super().__init__(message)
        self.reason = reason

    def safe_details(self) -> dict[str, str]:
        return {"reason": self.reason}


def _private_network_enabled() -> bool:
    return (env_value("ALLOW_PRIVATE_NETWORK", "") or "").strip().casefold() in {
        "1",
        "true",
        "yes",
        "on",
    }


@dataclass(frozen=True, slots=True)
class NetworkPolicy:
    allow_private_network: bool = False
    allow_http: bool = False

    @classmethod
    def from_environment(cls, *, allow_http: bool = False) -> "NetworkPolicy":
        return cls(
            allow_private_network=_private_network_enabled(),
            allow_http=allow_http,
        )

    def _addresses(self, host: str, port: int) -> set[ipaddress.IPv4Address | ipaddress.IPv6Address]:
        try:
            return {ipaddress.ip_address(host)}
        except ValueError:
            pass
        try:
            answers = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise NetworkPolicyError(
                "network destination could not be resolved",
                reason="dns_resolution_failed",
            ) from exc
        addresses = {ipaddress.ip_address(answer[4][0]) for answer in answers}
        if not addresses:
            raise NetworkPolicyError(
                "network destination resolved to no addresses",
                reason="dns_resolution_empty",
            )
        return addresses

    def _address_allowed(self, address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
        if address.is_global:
            return True
        if not self.allow_private_network:
            return False
        if address.is_link_local or address.is_multicast or address.is_unspecified:
            return False
        if address.is_loopback:
            return True
        if address.is_reserved:
            return False
        return address.is_private

    def validate_connected_address(self, value: str) -> None:
        try:
            address = ipaddress.ip_address(value)
        except ValueError as exc:
            raise NetworkPolicyError(
                "connected network peer did not expose a valid IP address",
                reason="peer_address_invalid",
            ) from exc
        if not self._address_allowed(address):
            raise NetworkPolicyError(
                "connected network peer is not allowed by the outbound network policy",
                reason="peer_address_denied",
            )

    def validate_url(self, url: str) -> str:
        parsed = urlsplit(url)
        scheme = parsed.scheme.casefold()
        allowed_schemes = {"https"} | ({"http"} if self.allow_http else set())
        if scheme not in allowed_schemes:
            raise NetworkPolicyError(
                "network URL must use https:// unless an explicit test-only HTTP policy is active",
                reason="scheme_denied",
            )
        if not parsed.hostname or parsed.username is not None or parsed.password is not None:
            raise NetworkPolicyError(
                "network URL must contain a host and no embedded credentials",
                reason="authority_invalid",
            )
        try:
            port = parsed.port or (443 if scheme == "https" else 80)
        except ValueError as exc:
            raise NetworkPolicyError(
                "network URL contains an invalid port",
                reason="authority_invalid",
            ) from exc
        addresses = self._addresses(parsed.hostname, port)
        if not all(self._address_allowed(address) for address in addresses):
            raise NetworkPolicyError(
                "network destination is private, loopback, link-local, reserved, or otherwise non-public",
                reason="address_class_denied",
            )
        return url


class PolicyRedirectHandler(HTTPRedirectHandler):
    def __init__(self, policy: NetworkPolicy) -> None:
        super().__init__()
        self.policy = policy

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urljoin(req.full_url, newurl)
        self.policy.validate_url(target)
        return super().redirect_request(req, fp, code, msg, headers, target)


class _PolicyHTTPConnection(HTTPConnection):
    def __init__(self, host: str, *, policy: NetworkPolicy, **kwargs) -> None:
        self._network_policy = policy
        super().__init__(host, **kwargs)

    def connect(self) -> None:
        super().connect()
        assert self.sock is not None
        try:
            self._network_policy.validate_connected_address(self.sock.getpeername()[0])
        except Exception:
            self.close()
            raise


class _PolicyHTTPSConnection(HTTPSConnection):
    def __init__(self, host: str, *, policy: NetworkPolicy, **kwargs) -> None:
        self._network_policy = policy
        super().__init__(host, **kwargs)

    def connect(self) -> None:
        super().connect()
        assert self.sock is not None
        try:
            self._network_policy.validate_connected_address(self.sock.getpeername()[0])
        except Exception:
            self.close()
            raise


class PolicyHTTPHandler(HTTPHandler):
    def __init__(self, policy: NetworkPolicy) -> None:
        super().__init__()
        self.policy = policy

    def http_open(self, req):
        def connection(host: str, **kwargs):
            return _PolicyHTTPConnection(host, policy=self.policy, **kwargs)

        return self.do_open(connection, req)


class PolicyHTTPSHandler(HTTPSHandler):
    def __init__(
        self,
        policy: NetworkPolicy,
        *,
        context: ssl.SSLContext | None = None,
    ) -> None:
        super().__init__(context=context)
        self.policy = policy

    def https_open(self, req):
        def connection(host: str, **kwargs):
            return _PolicyHTTPSConnection(host, policy=self.policy, **kwargs)

        return self.do_open(
            connection,
            req,
            context=self._context,
        )


def build_policy_opener(
    policy: NetworkPolicy,
    *,
    context: ssl.SSLContext | None = None,
) -> OpenerDirector:
    handlers: list[object] = [
        PolicyRedirectHandler(policy),
        PolicyHTTPHandler(policy),
        PolicyHTTPSHandler(policy, context=context),
    ]
    return build_opener(*handlers)


def open_url(
    request: Request,
    *,
    policy: NetworkPolicy,
    timeout: float | None,
    context: ssl.SSLContext | None = None,
):
    policy.validate_url(request.full_url)
    return build_policy_opener(policy, context=context).open(request, timeout=timeout)
