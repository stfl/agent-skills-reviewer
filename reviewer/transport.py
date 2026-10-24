"""The one HTTP transport, over urllib. Tests replace it with a fake."""

import http.client
import urllib.error
import urllib.request


class NoAnswer(Exception):
    """The request got no HTTP response."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason  # "timeout", "connection" or "request"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    # A redirect would resend the request headers, credentials included, to
    # another URL; a 3xx answer is returned as it is instead.
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def send(method, url, headers, data, timeout):
    """Send one request; return (status, body bytes) or raise NoAnswer."""
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        try:
            with _OPENER.open(request, timeout=timeout) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            with error:
                return error.code, error.read()
    except TimeoutError:
        raise NoAnswer("timeout") from None
    except (urllib.error.URLError, OSError, http.client.HTTPException) as error:
        if isinstance(getattr(error, "reason", None), TimeoutError):
            raise NoAnswer("timeout") from None
        raise NoAnswer("connection") from None
    except ValueError:
        # http.client refuses a header value with a line break, such as a
        # secret stored with a trailing newline.
        raise NoAnswer("request") from None
