import os
import socket
import struct
import threading


HOST, PORT = "", 9090
SERVER_DIRECTORY = os.path.dirname(os.path.abspath(__file__))
FRAME_DATA_SIZE = 512
FRAME_HEADER_FORMAT = "!IIB"

FLAG_DATA = 0
FLAG_END_STREAM = 1
FLAG_ERROR = 2
FLAGS= enumerate(["FLAG_DATA","FLAG_END_STEAM","FLAG_ERROR"])

def receive_request(client_connection):
    """Receive a FILES request ending with a blank line."""
    request = b""

    while b"\n\n" not in request:
        data = client_connection.recv(4096)

        if not data:
            break

        request += data

        if len(request) > 65536:
            raise ValueError("Request is too large")

    return request.decode("utf-8")


def parse_request(request_text):
    """Parse: FILES count, followed by one requested path per line."""
    lines = [line.strip() for line in request_text.splitlines() if line.strip()]

    if not lines or not lines[0].startswith("FILES "):
        raise ValueError("Expected: FILES <number>")

    requested_count = int(lines[0].split()[1])
    requested_paths = lines[1:]

    if requested_count < 1 or requested_count != len(requested_paths):
        raise ValueError("Incorrect number of requested files")

    return requested_paths


def resolve_file_path(requested_path):
    """Map the requested path safely into the server directory."""
    clean_path = requested_path.split("?", 1)[0]

    if clean_path == "/":
        clean_path = "/test.html"

    relative_path = clean_path.lstrip("/")
    file_path = os.path.abspath(os.path.join(SERVER_DIRECTORY, relative_path))
    if os.path.commonpath([SERVER_DIRECTORY, file_path]) != SERVER_DIRECTORY:
        raise PermissionError("Requested path is outside the server directory")

    return clean_path, file_path


def send_frame(client_connection, stream_id, payload=b"", flags=FLAG_DATA):
    """Send one frame: stream ID + payload length + flags + payload."""
    header = struct.pack(
        FRAME_HEADER_FORMAT,
        stream_id,
        len(payload),
        flags,
    )
    client_connection.sendall(header + payload)


def create_streams(requested_paths):
    """Create one independent response stream for every requested file."""
    streams = []
    # For each requested path, create a list of STREAMs
    # each STREAM consists of a dictionary of {id,clean_path,file_path,possible_error}
    # ID is used to match the frame on CLIENT's end
    for stream_id, requested_path in enumerate(requested_paths, start=1):
        try:
            clean_path, file_path = resolve_file_path(requested_path)
            #print(f"{file_path}")
            if not os.path.isfile(file_path):
                streams.append(
                    {
                        "id": stream_id,
                        "path": clean_path,
                        "file": None,
                        "error": b"404 Not Found",
                    }
                )
            else:
                streams.append(
                    {
                        "id": stream_id,
                        "path": clean_path,
                        "file": open(file_path, "rb"),
                        "error": None,
                    }
                )

        except PermissionError:
            streams.append(
                {
                    "id": stream_id,
                    "path": requested_path,
                    "file": None,
                    "error": b"403 Forbidden",
                }
            )

    return streams


def send_streams_round_robin(client_connection, streams):
    """Interleave frames so no single large response occupies the connection."""
    active_streams = list(streams)
    # This while iteratively moves the FILE pointer in each STREAM of each FILE forwards,
    # until both files have reached their ends.
    while active_streams:
        next_round = []

        for stream in active_streams:
            stream_id = stream["id"]

            if stream["error"] is not None:
                send_frame(
                    client_connection,
                    stream_id,
                    stream["error"],
                    FLAG_END_STREAM | FLAG_ERROR,
                )
                print(f"Stream {stream_id} ended with {stream['error'].decode()}")
                continue

            data = stream["file"].read(FRAME_DATA_SIZE)

            if data:
                send_frame(client_connection, stream_id, data, FLAG_DATA)
                print(f"Sent stream {stream_id}: {len(data)} bytes")
                next_round.append(stream)
            else:
                send_frame(client_connection, stream_id, b"", FLAG_END_STREAM)
                stream["file"].close()
                print(f"Stream {stream_id} complete: {stream['path']}")

        active_streams = next_round


def close_open_files(streams):
    for stream in streams:
        file_object = stream.get("file")

        if file_object is not None and not file_object.closed:
            file_object.close()


def handle_client(client_connection, client_address):
    streams = []
    thread_name = threading.current_thread().name
    print(f"{thread_name} handling {client_address}")

    try:
        """
        For example, a request text might look like this:
        req text:   {FILES 2\n
                    big.txt\n
                    small.txt\n}
        """
        request_text = receive_request(client_connection)
        """Parse the request text into PATHs."""
        requested_paths = parse_request(request_text)
        print(f"req paths:{requested_paths}")
        
        streams = create_streams(requested_paths)
        # paths=[lines["path"] for lines in streams]
        # print(paths)
        send_streams_round_robin(client_connection, streams)

    except (ConnectionError, UnicodeError, ValueError) as error:
        print(f"{thread_name} error: {error}")
    finally:
        close_open_files(streams)
        client_connection.close()
        print(f"{thread_name} finished {client_address}")


listen_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
listen_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
listen_socket.bind((HOST, PORT))
listen_socket.listen(10)
print(f"Framed server listening on port {PORT} ...")
print(f"Frame data size: {FRAME_DATA_SIZE} bytes")

try:
    while True:
        client_connection, client_address = listen_socket.accept()
        client_thread = threading.Thread(
            target=handle_client,
            args=(client_connection, client_address),
            daemon=True,
        )
        client_thread.start()

except KeyboardInterrupt:
    print("\nFramed server stopped.")
finally:
    listen_socket.close()


# Start this server:
# python3 frame-server.py
#
# Test it with the matching client:
# python3 frame-client.py server.py test.html
