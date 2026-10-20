from starlette.requests import Request

from app.config import Settings
from app.web.client import client_ip


def request(headers: dict[str, str], host: str = "10.0.0.7") -> Request:
    return Request(
        {
            "type": "http",
            "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
            "client": (host, 50000),
        }
    )


def settings(header: str | None) -> Settings:
    return Settings(_env_file=None, client_ip_header=header)


def test_without_the_setting_a_header_sent_by_the_visitor_is_ignored() -> None:
    sent = request({"X-Real-IP": "198.51.100.9", "X-Forwarded-For": "198.51.100.9"})

    assert client_ip(sent, settings(None)) == "10.0.0.7"


def test_with_the_setting_the_proxy_header_is_used() -> None:
    sent = request({"X-Real-IP": "203.0.113.4"})

    assert client_ip(sent, settings("x-real-ip")) == "203.0.113.4"


def test_from_a_list_the_entry_added_by_the_nearest_proxy_is_used() -> None:
    # The first entry can be anything the visitor sent.
    sent = request({"X-Forwarded-For": "198.51.100.9, 203.0.113.4"})

    assert client_ip(sent, settings("x-forwarded-for")) == "203.0.113.4"


def test_a_missing_header_falls_back_to_the_connection() -> None:
    assert client_ip(request({}), settings("x-real-ip")) == "10.0.0.7"
