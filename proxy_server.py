import socket
import os
import threading

HOST = "127.0.0.1"
PORT = 9091
os.makedirs("cache", exist_ok=True)

def handlingrequest(client):
    request = client.recv(4096).decode()

    if not request:
        client.close()
        return

    fl = request.split("\r\n")[0]
    method, url, version = fl.split()

    if method != "GET":
        client.sendall(b"HTTP/1.1 501 Not Implemented\r\n\r\n")
        client.close()
        return

    url = url.replace("http://", "")

    if "/" in url:
        phost, path = url.split("/", 1)
        path = "/" + path
    else:
        phost = url
        path = "/"

    cachepath = (
        "cache/"
        + phost.replace(".", "_")
        + path.replace("/", "_")
    )

    if os.path.exists(cachepath):
        print("cache is a hit")
        with open(cachepath, "rb") as file:
            response = file.read()

    else:
        print("cache is a miss")
        origin = socket.socket(
            socket.AF_INET,
            socket.SOCK_STREAM
        )

        origin.connect((phost, 80))
        originr = (
            f"GET {path} HTTP/1.0\r\n"
            f"Host: {phost}\r\n\r\n"
        )

        origin.sendall(originr.encode())
        response = b""

        while True:
            data = origin.recv(4096)
            if not data:
                break
            response += data
        
        origin.close()
        with open(cachepath, "wb") as file:
            file.write(response)

    client.sendall(response)
    client.close()

server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.bind((HOST, PORT))
server.listen(5)

print("Proxy server is still running on port", PORT)

while True:
    client, address = server.accept()
    thread = threading.Thread(
        target=handlingrequest,
        args=(client,)
    )
    thread.start()