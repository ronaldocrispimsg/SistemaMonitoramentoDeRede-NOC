from urllib.parse import urlparse

def normalize_http_url(url: str, port: int | None) -> str:
    if not url:
        return url

    parsed = urlparse(url)

    if parsed.scheme:
        return url

    if port == 443:
        scheme = "https"
    else:
        scheme = "http"

    return f"{scheme}://{url}"

