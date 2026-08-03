import os
import socket
from datetime import timezone
from email.utils import parsedate_to_datetime


HOST, PORT = "", 9090
SERVER_DIRECTORY = os.path.dirname(os.path.abspath(__file__))
SUPPORTED_VERSION = "HTTP/1.1"

# Sends a response http message back to the client
def send_response(client_connection, status, body=b"", content_type="text/plain; charset=utf-8"):
    """Send one complete HTTP response to the client."""
    response = (
        f"HTTP/1.1 {status}\r\n"
        f"Content-Length: {len(body)}\r\n"
        f"Content-Type: {content_type}\r\n"
        "Connection: close\r\n"
        "\r\n"
    ).encode("utf-8") + body

    client_connection.sendall(response)


def get_headers(request_lines):
    """Convert the HTTP header lines into a dictionary."""
    headers = {}

    for line in request_lines[1:]:
        if ":" in line:
            name, value = line.split(":", 1)
            headers[name.strip().lower()] = value.strip()

    return headers

# Returns true if the file has not been changed since {if-modified-since} 
# object in the header and false if it has been changed.
# If true: send file to client
# If false: send FILE NOT MODIFIED 304
def was_not_modified(file_path, if_modified_since):
    """Return True when the file has not changed since the supplied date."""
    if not if_modified_since:
        return False

    try:
        request_date = parsedate_to_datetime(if_modified_since)

        if request_date.tzinfo is None:
            request_date = request_date.replace(tzinfo=timezone.utc)

        file_modified_time = os.path.getmtime(file_path)

        # Returns true if the file on system has an older {last-modified} timestamp than {if-modified-since} header
        # True means the last time file was changed on system was before the {if-modified-since} header value.
        return file_modified_time <= request_date.timestamp()
    except (TypeError, ValueError, OverflowError):
        # Ignore an invalid If-Modified-Since header.
        return False


listen_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
listen_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
listen_socket.bind((HOST, PORT))
listen_socket.listen(1)
print(f"Serving HTTP on port {PORT} ...")

try:
    while True:
        client_connection, client_address = listen_socket.accept()

        try:
            request = client_connection.recv(4096)

            if not request:
                continue

            request_text = request.decode("iso-8859-1")
            print(request_text)
            request_lines = request_text.split("\r\n")
            request_parts = request_lines[0].split()

            if len(request_parts) != 3:
                send_response(client_connection, "400 Bad Request", b"400 Bad Request\n")
                continue

            method, requested_path, http_version = request_parts

            # 505: this minimal server supports HTTP/1.1 only.
            if http_version != SUPPORTED_VERSION:
                print("UNSUPPORTED HTTP VERSION - SEND 505")
                send_response(
                    client_connection,
                    "505 HTTP Version Not Supported",
                    b"505 HTTP Version Not Supported\n",
                )
                continue

            requested_path = requested_path.split("?", 1)[0]

            # 403: this route is intentionally protected.
            if requested_path == "/forbidden.html":
                print("ACCESS DENIED - SEND 403")
                send_response(client_connection, "403 Forbidden", b"403 Forbidden\n")
                continue

            if method != "GET":
                send_response(client_connection, "400 Bad Request", b"Only GET is supported\n")
                continue

            if requested_path == "/":
                requested_path = "/test.html"

            relative_path = requested_path.lstrip("/")
            file_path = os.path.abspath(os.path.join(SERVER_DIRECTORY, relative_path))

            # Prevent requests such as /../secret.txt from leaving this directory.
            if os.path.commonpath([SERVER_DIRECTORY, file_path]) != SERVER_DIRECTORY:
                print("PATH OUTSIDE SERVER DIRECTORY - SEND 403")
                send_response(client_connection, "403 Forbidden", b"403 Forbidden\n")
                continue

            # 404: the requested file does not exist.
            if not os.path.isfile(file_path):
                print("FILE DOES NOT EXIST - SEND 404")
                send_response(client_connection, "404 Not Found", b"404 Not Found\n")
                continue

            headers = get_headers(request_lines)

            # 304: the existing file has not changed since the client's date.
            if was_not_modified(file_path, headers.get("if-modified-since")):
                print("FILE NOT MODIFIED - SEND 304")
                send_response(client_connection, "304 Not Modified")
                continue

            # 200: the requested file exists and can be returned.
            print("FILE EXISTS - SEND 200")
            with open(file_path, "rb") as file:
                response_body = file.read()

            content_type = (
                "text/html; charset=utf-8"
                if file_path.lower().endswith(".html")
                else "application/octet-stream"
            )
            send_response(client_connection, "200 OK", response_body, content_type)

        except (ConnectionError, UnicodeError) as error:
            print("Request error:", error)
        finally:
            client_connection.close()

except KeyboardInterrupt:
    print("\nServer stopped.")
finally:
    listen_socket.close()


# TEST COMMANDS (run these in a second terminal):
#
# 200 OK:
# curl -i http://localhost:9090/test.html
#
# 304 Not Modified:
# curl -i -H "If-Modified-Since: Wed, 30 Aug 2026 12:00:00 GMT" http://localhost:9090/test.html
#
# 403 Forbidden:
# curl -i http://localhost:9090/forbidden.html
#
# 404 Not Found:
# curl -i http://localhost:9090/missing.html
#
# 505 HTTP Version Not Supported:
# curl -i --http1.0 http://localhost:9090/test.html