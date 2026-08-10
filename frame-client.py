import os
import socket
import struct
import sys
import time


SERVER_HOST, SERVER_PORT = "127.0.0.1", 9090
FRAME_HEADER_FORMAT = "!IIB"
FRAME_HEADER_SIZE = struct.calcsize(FRAME_HEADER_FORMAT)
OUTPUT_DIRECTORY = "received"

FLAG_END_STREAM = 1
FLAG_ERROR = 2


def receive_exact(connection, byte_count):
    """Receive exactly byte_count bytes, or return None if disconnected."""
    data = b""

    while len(data) < byte_count:
        part = connection.recv(byte_count - len(data))

        if not part:
            return None

        data += part

    return data


def build_request(requested_paths):
    lines = [f"FILES {len(requested_paths)}", *requested_paths, "", ""]
    return "\n".join(lines).encode("utf-8")


def safe_output_name(requested_path, stream_id):
    filename = os.path.basename(requested_path.split("?", 1)[0])
    return filename or f"stream-{stream_id}.data"


def receive_frames(connection, requested_paths):
    """Reassemble frames independently using their stream IDs."""
    response_data = {
        stream_id: bytearray()
        for stream_id in range(1, len(requested_paths) + 1)
    }
    unfinished_streams = set(response_data)
    completed_stream_count = 0
    #start_time = time.perf_counter()

    while unfinished_streams:
        header = receive_exact(connection, FRAME_HEADER_SIZE)

        if header is None:
            raise ConnectionError("Server disconnected before all streams finished")

        stream_id, payload_length, flags = struct.unpack(
            FRAME_HEADER_FORMAT,
            header,
        )
        payload = receive_exact(connection, payload_length)

        if payload is None:
            raise ConnectionError("Incomplete frame payload")

        if stream_id not in response_data:
            raise ValueError(f"Unknown stream ID: {stream_id}")

        #elapsed = time.perf_counter() - start_time
        print(
            f"Frame received: stream={stream_id}, "
            f"bytes={payload_length}, flags={flags}"
        )

        if flags & FLAG_ERROR:
            print(f"Stream {stream_id} error: {payload.decode('utf-8')}")
        else:
            response_data[stream_id].extend(payload)

        if flags & FLAG_END_STREAM:
            unfinished_streams.discard(stream_id)
            completed_stream_count += 1

            if not flags & FLAG_ERROR:
                os.makedirs(OUTPUT_DIRECTORY, exist_ok=True)
                filename = safe_output_name(
                    requested_paths[stream_id - 1],
                    stream_id,
                )
                output_path = os.path.join(OUTPUT_DIRECTORY, filename)

                with open(output_path, "wb") as output_file:
                    output_file.write(response_data[stream_id])

                print(
                    f"Stream {stream_id} completed "
                    f"(completion #{completed_stream_count}): "
                    f"{output_path} ({len(response_data[stream_id])} bytes)"
                )


requested_paths = sys.argv[1:]

if not requested_paths:
    requested_paths = ["big.txt", "small.txt"]

print("Requested streams:")

for stream_id, requested_path in enumerate(requested_paths, start=1):
    print(f"  Stream {stream_id}: {requested_path}")

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
    connection.connect((SERVER_HOST, SERVER_PORT))
    connection.sendall(build_request(requested_paths))
    receive_frames(connection, requested_paths)

print("All response streams completed.")
