import socket
import threading
import sys

SERVER_HOST = "127.0.0.1"
SERVER_PORT = 50001


def recv_loop(sock: socket.socket, state: dict):
    buffer = b""
    try:
        while True:
            data = sock.recv(4096)
            if not data:
                print("\n【系統】伺服器已斷線。")
                state["alive"] = False
                break

            buffer += data
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                if not line:
                    continue
                msg = line.decode(errors="ignore")
                if msg:
                    print(msg)
    except Exception as e:
        print("\n【系統】接收執行緒結束：", e)
        state["alive"] = False


def send_line(sock: socket.socket, msg: str):
    if not msg.endswith("\n"):
        msg += "\n"
    sock.sendall(msg.encode())


def main():
    host = SERVER_HOST
    port = SERVER_PORT

    if len(sys.argv) >= 2:
        host = sys.argv[1]
    if len(sys.argv) >= 3:
        port = int(sys.argv[2])

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.connect((host, port))
    except Exception as e:
        print("【系統】連線失敗：", e)
        return

    state = {"alive": True}

    print(f"【系統】已連線到 {host}:{port}")

    threading.Thread(target=recv_loop, args=(s, state), daemon=True).start()

    try:
        while state["alive"]:
            msg = input()
            if not msg.strip():
                continue
            send_line(s, msg.strip())
            if msg.strip().upper() == "QUIT":
                break
    except KeyboardInterrupt:
        try:
            send_line(s, "QUIT")
        except:
            pass
    finally:
        state["alive"] = False
        try:
            s.close()
        except:
            pass
        print("【系統】已離線。")


if __name__ == "__main__":
    main()