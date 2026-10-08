"""Wi-Fi based attendance verification.

How the check actually works
----------------------------
A browser cannot read the SSID of the network a phone is joined to — no web
API exposes it, for privacy reasons. What the server *can* see is the IP
address the request arrived from, and that address is handed out by the
campus network itself. So verification is done on the server:

  * If the student is on the venue's Wi-Fi, the request arrives from a private
    address inside that access point's subnet (for example 10.10.4.0/22).
  * If the student is at home on mobile data, the address is a public one that
    does not fall inside any permitted range, and attendance is refused.

Each event therefore stores one or more permitted CIDR ranges. For the case
where the whole campus leaves through a single NAT gateway, an event may also
store the gateway's public IP, which proves the student is on campus but not
which room they are in — so it is treated as a weaker fallback and recorded as
such in the attendance row.

The SSID typed on the attendance page is collected only as a label for the
organiser's report. It is never trusted as proof.
"""

import ipaddress
from datetime import timedelta


def get_client_ip(request, trusted_proxy_count=0):
    """Work out the real client IP.

    X-Forwarded-For is only read when the app is actually deployed behind a
    known number of proxies; otherwise a student could set the header by hand
    and fake being on campus.
    """
    if trusted_proxy_count > 0:
        forwarded = request.headers.get("X-Forwarded-For", "")
        chain = [part.strip() for part in forwarded.split(",") if part.strip()]
        if len(chain) >= trusted_proxy_count:
            return chain[-trusted_proxy_count]
    return request.remote_addr or ""


def parse_networks(cidr_text):
    """Turn '10.10.0.0/16, 192.168.20.0/24' into a list of network objects."""
    networks = []
    for chunk in (cidr_text or "").replace(";", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            networks.append(ipaddress.ip_network(chunk, strict=False))
        except ValueError:
            continue  # a malformed range is ignored rather than crashing
    return networks


def validate_cidr_text(cidr_text):
    """Return a list of the entries an organiser typed that are not valid."""
    invalid = []
    for chunk in (cidr_text or "").replace(";", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            ipaddress.ip_network(chunk, strict=False)
        except ValueError:
            invalid.append(chunk)
    return invalid


def verify_network(event, client_ip):
    """Check a request against an event's permitted network.

    Returns (verified, method, message) where method is 'wifi_subnet' for a
    match inside the venue subnet, 'campus_gateway' for the weaker public-IP
    match, and None when the check fails.
    """
    try:
        address = ipaddress.ip_address(client_ip)
    except ValueError:
        return False, None, "Your network address could not be read. Reconnect to the campus Wi-Fi and try again."

    networks = parse_networks(event.get("wifi_cidr"))
    gateway = (event.get("wifi_public_ip") or "").strip()

    if not networks and not gateway:
        return False, None, "The organiser has not set the permitted network for this event yet."

    for network in networks:
        if address in network:
            return True, "wifi_subnet", "Connected to the event network."

    if gateway and client_ip == gateway:
        return True, "campus_gateway", "Verified through the campus gateway."

    ssid = event.get("wifi_ssid") or "the event Wi-Fi"
    return (
        False,
        None,
        f"This device is not on {ssid}. Your address is {client_ip}, which is outside the "
        f"network allowed for this event. Join the venue Wi-Fi and reload this page.",
    )


def attendance_window(event, opens_before_min, closes_after_min):
    """The period during which the attendance page accepts submissions."""
    opens_at = event["start_datetime"] - timedelta(minutes=opens_before_min)
    closes_at = event["end_datetime"] + timedelta(minutes=closes_after_min)
    return opens_at, closes_at