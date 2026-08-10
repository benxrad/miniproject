import os
import socket
import threading
from datetime import timezone
from email.utils import parsedate_to_datetime

# multi-threaded version of the Origin server server.py
HOST, PORT = "", 9090
SERVER_DIRECTORY = os.path.dirname(os.path.abspath(__file__))
SUPPORTED_VERSION = "HTTP/1.1"


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
    headers = {}

    for line in request_lines[1:]:
        if ":" in line:
            name, value = line.split(":", 1)
            headers[name.strip().lower()] = value.strip()

    return headers


def was_not_modified(file_path, if_modified_since):
    if not if_modified_since:
        return False

    try:
        request_date = parsedate_to_datetime(if_modified_since)

        if request_date.tzinfo is None:
            request_date = request_date.replace(tzinfo=timezone.utc)

        return os.path.getmtime(file_path) <= request_date.timestamp()
    except (TypeError, ValueError, OverflowError):
        return False


def handle_client(client_connection, client_address):
    """Process one client in its own thread."""
    thread_name = threading.current_thread().name
    print(f"{thread_name} handling {client_address}")

    try:
        request = client_connection.recv(4096)

        if not request:
            return

        request_text = request.decode("iso-8859-1")
        request_lines = request_text.split("\r\n")
        request_parts = request_lines[0].split()

        if len(request_parts) != 3:
            send_response(client_connection, "400 Bad Request", b"400 Bad Request\n")
            return

        method, requested_path, http_version = request_parts

        # 505: this minimal server supports HTTP/1.1 only.
        if http_version != SUPPORTED_VERSION:
            send_response(
                client_connection,
                "505 HTTP Version Not Supported",
                b"505 HTTP Version Not Supported\n",
            )
            return

        requested_path = requested_path.split("?", 1)[0]

        # 403: this route is intentionally protected.
        if requested_path == "/forbidden.html":
            send_response(client_connection, "403 Forbidden", b"403 Forbidden\n")
            return

        if method != "GET":
            send_response(client_connection, "400 Bad Request", b"Only GET is supported\n")
            return

        if requested_path == "/":
            requested_path = "/test.html"

        relative_path = requested_path.lstrip("/")
        file_path = os.path.abspath(os.path.join(SERVER_DIRECTORY, relative_path))

        # Prevent a request from leaving the server directory.
        if os.path.commonpath([SERVER_DIRECTORY, file_path]) != SERVER_DIRECTORY:
            send_response(client_connection, "403 Forbidden", b"403 Forbidden\n")
            return

        if not os.path.isfile(file_path):
            send_response(client_connection, "404 Not Found", b"404 Not Found\n")
            return

        headers = get_headers(request_lines)

        if was_not_modified(file_path, headers.get("if-modified-since")):
            send_response(client_connection, "304 Not Modified")
            return

        with open(file_path, "rb") as file:
            response_body = file.read()

        content_type = (
            "text/html; charset=utf-8"
            if file_path.lower().endswith(".html")
            else "application/octet-stream"
        )
        send_response(client_connection, "200 OK", response_body, content_type)

    except (ConnectionError, UnicodeError) as error:
        print(f"{thread_name} error: {error}")
    finally:
        client_connection.close()
        print(f"{thread_name} finished {client_address}")


listen_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
listen_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
listen_socket.bind((HOST, PORT))
listen_socket.listen(10) 
# create a back log of 10 clients ready to be processed
# Then assign a thread to each one of clients
print(f"Multi-threaded HTTP server listening on port {PORT} ...")

try:
    while True:
        client_connection, client_address = listen_socket.accept()

        # Every accepted client runs independently in a new thread.
        client_thread = threading.Thread(
            target=handle_client,
            args=(client_connection, client_address),
            daemon=True,
        )
        client_thread.start()

except KeyboardInterrupt:
    print("\nServer stopped.")
finally:
    listen_socket.close()


# PARALLEL TEST (to test thread-server.py), command below sends 10 concurrent client requests to the server.
# seq 1 10 | xargs -P10 -I{} curl -s -o /dev/null -w "Request {}: %{http_code}\n" http://localhost:9090/test.html

# Performance test:
# /usr/bin/time -p sh -c 'seq 1 100 | xargs -P10 -I{} curl -sS --fail -o /dev/null http://localhost:9090/test.html'