import os
import socket
from email.utils import formatdate


PROXY_HOST, PROXY_PORT = "", 8888
ORIGIN_HOST, ORIGIN_PORT = "127.0.0.1", 9090
PROXY_DIRECTORY = os.path.dirname(os.path.abspath(__file__))
CACHE_DIRECTORY = os.path.join(PROXY_DIRECTORY, "cache")
MAX_REQUEST_SIZE = 65536


def send_response(client_connection, status, body=b"", content_type="text/plain; charset=utf-8"):
    """Send a complete HTTP response to the client."""
    response = (
        f"HTTP/1.1 {status}\r\n"
        f"Content-Length: {len(body)}\r\n"
        f"Content-Type: {content_type}\r\n"
        "Connection: close\r\n"
        "\r\n"
    ).encode("utf-8") + body
    client_connection.sendall(response)


def receive_client_request(client_connection):
    """Receive the client's HTTP request headers."""
    request = b""

    while b"\r\n\r\n" not in request:
        data = client_connection.recv(4096)

        if not data:
            break

        request += data

        if len(request) > MAX_REQUEST_SIZE:
            raise ValueError("Request headers are too large")

    return request


def extract_path(request_target):
    """Extract /path from a normal request or an absolute URL."""
    if request_target.startswith("http://"):
        address_and_path = request_target[len("http://"):]
        slash_position = address_and_path.find("/")
        request_target = "/" if slash_position == -1 else address_and_path[slash_position:]

    return request_target.split("?", 1)[0]


def get_cache_path(requested_path):
    """Return a safe filename inside the cache directory."""
    relative_path = requested_path.lstrip("/")
    cache_path = os.path.abspath(os.path.join(CACHE_DIRECTORY, relative_path))

    if os.path.commonpath([CACHE_DIRECTORY, cache_path]) != CACHE_DIRECTORY:
        raise PermissionError("The requested path is outside the cache directory")

    return cache_path


def get_content_type(requested_path):
    if requested_path.lower().endswith(".html"):
        return "text/html; charset=utf-8"

    return "application/octet-stream"


def build_origin_request(requested_path, modified_date=None):
    """Build a GET request for the predefined origin server."""
    request_lines = [
        f"GET {requested_path} HTTP/1.1",
        f"Host: {ORIGIN_HOST}:{ORIGIN_PORT}",
        "Connection: close",
    ]

    if modified_date is not None:
        request_lines.append(f"If-Modified-Since: {modified_date}")

    request_lines.extend(["", ""])
    return "\r\n".join(request_lines).encode("iso-8859-1")


def contact_origin(origin_request):
    """Send a request to server.py and receive its complete response."""
    response = b""
    #print("\nContacting Origin Server to fetch (", origin_request.decode(),")\n")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as origin_socket:
        origin_socket.settimeout(5)
        origin_socket.connect((ORIGIN_HOST, ORIGIN_PORT))
        origin_socket.sendall(origin_request)

        while True:
            data = origin_socket.recv(4096)

            if not data:
                break

            response += data

    return response


def separate_origin_response(origin_response):
    """Separate the origin's status code, headers, and body."""
    if b"\r\n\r\n" not in origin_response:
        raise ValueError("Invalid response from origin server")
    #"ewr/wer/wer".split()
    header_data, body = origin_response.split(b"\r\n\r\n", 1)
    header_lines = header_data.decode("iso-8859-1").split("\r\n")
    status_parts = header_lines[0].split()

    if len(status_parts) < 2:
        raise ValueError("Invalid origin status line")

    return int(status_parts[1]), body


def save_to_cache(cache_path, body):
    """Store the newest origin response body in the cache directory."""
    parent_directory = os.path.dirname(cache_path)
    os.makedirs(parent_directory, exist_ok=True)

    with open(cache_path, "wb") as cache_file:
        cache_file.write(body)


def send_cached_file(client_connection, cache_path, requested_path):
    with open(cache_path, "rb") as cache_file:
        cached_body = cache_file.read()

    send_response(
        client_connection,
        "200 OK",
        cached_body,
        get_content_type(requested_path),
    )


def handle_client(client_connection, client_address):
    try:
        print("\n----------")
        print("\n[+] Client :",client_address," connected to proxy server...")
        request = receive_client_request(client_connection)

        if not request:
            return

        request_text = request.decode("iso-8859-1")
        print("\n----------")
        print("\n[+] client request:(",request_text.strip("\n"),")")
        print("\n----------")
        request_line = request_text.split("\r\n", 1)[0]
        request_parts = request_line.split()

        if len(request_parts) != 3:
            send_response(client_connection, "400 Bad Request", b"400 Bad Request\n")
            return

        method, request_target, http_version = request_parts

        if method != "GET":
            send_response(client_connection, "501 Not Implemented", b"Only GET is supported\n")
            return

        if http_version not in {"HTTP/1.0", "HTTP/1.1"}:
            send_response(
                client_connection,
                "505 HTTP Version Not Supported",
                b"505 HTTP Version Not Supported\n",
            )
            return

        requested_path = extract_path(request_target)

        if requested_path == "/":
            requested_path = "/test.html"

        try:
            cache_path = get_cache_path(requested_path)
        except PermissionError:
            send_response(client_connection, "403 Forbidden", b"403 Forbidden\n")
            return

        if os.path.isfile(cache_path):
            # Convert the cached file's modification time to an HTTP date.
            cached_modified_time = os.path.getmtime(cache_path)
            modified_date = formatdate(cached_modified_time, usegmt=True)
            print(f"CACHE HIT: {cache_path}")
            print(f"If-Modified-Since: {modified_date}")

            origin_request = build_origin_request(requested_path, modified_date)
        else:
            print(f"CACHE MISS: {cache_path}")
            origin_request = build_origin_request(requested_path)

        try:
            print("\n----------")
            print("Contacting ORIGIN server @:",ORIGIN_HOST,":",ORIGIN_PORT)
            print("\n----------")
            print("ORIGIN request header:")
            print(origin_request.decode())
            origin_response = contact_origin(origin_request)
            print("\n----------")
            print("ORIGIN Server response:")
            print(origin_response)
            print("\n----------")
            origin_status, origin_body = separate_origin_response(origin_response)
        except (ConnectionError, socket.timeout, OSError, ValueError) as error:
            print(f"Origin server error: {error}")
            send_response(
                client_connection,
                "502 Bad Gateway",
                b"The proxy could not get a valid response from the origin server\n",
            )
            return

        if origin_status == 304 and os.path.isfile(cache_path):
            print("ORIGIN RESPONSE: 304 Not Modified - sending cached file")
            send_cached_file(client_connection, cache_path, requested_path)

        elif origin_status == 200:
            print("ORIGIN RESPONSE: 200 OK - downloading and updating cache")
            save_to_cache(cache_path, origin_body)
            send_response(
                client_connection,
                "200 OK",
                origin_body,
                get_content_type(requested_path),
            )

        else:
            # Forward responses such as 403 or 404 without caching them.
            print(f"ORIGIN RESPONSE: {origin_status} - forwarding to client")
            client_connection.sendall(origin_response)

    except (ConnectionError, UnicodeError, ValueError) as error:
        print(f"Client {client_address} error: {error}")
    finally:
        client_connection.close()


os.makedirs(CACHE_DIRECTORY, exist_ok=True)

listen_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
listen_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
listen_socket.bind((PROXY_HOST, PROXY_PORT))
listen_socket.listen(10)
print(f"Proxy server listening on port {PROXY_PORT} ...")
print(f"Predefined origin server: {ORIGIN_HOST}:{ORIGIN_PORT}")
print(f"Cache directory: {CACHE_DIRECTORY}")
print("\n----------")

try:
    while True:
        client_connection, client_address = listen_socket.accept()
        handle_client(client_connection, client_address)

except KeyboardInterrupt:
    print("\nProxy server stopped.")
finally:
    listen_socket.close()


# TEST PROCEDURE:
#
# Terminal 1 - start the predefined origin server:
# python3 server.py
#
# Terminal 2 - start this proxy server:
# python3 proxy_server2.py
#
# Terminal 3 - send the request only to the proxy:
# curl -i http://localhost:8888/test.html
#
#

