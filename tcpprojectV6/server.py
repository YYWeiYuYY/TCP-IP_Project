import socket
import threading

import big2
import blackjack
import tictactoe
import roulette

HOST = "0.0.0.0"
PORT = 50001

clients = {}
clients_lock = threading.Lock()

used_names = set()
names_lock = threading.Lock()


def send_line(conn, msg: str):
    if conn is None:
        return
    if msg is None:
        msg = ""
    if not msg.endswith("\n"):
        msg += "\n"
    try:
        conn.sendall(msg.encode())
    except:
        pass


# Player
class Player:
    def __init__(self, conn):
        self.conn = conn
        self.name = None
        self.balance = 1000
        self.current_game = None
        self.current_room = None
        self.buffer = ""


# 離開目前遊戲
def leave_current_game(player: Player):
    game = player.current_game
    room_id = player.current_room
    if not game:
        return

    try:
        if game == "BIG2":
            big2.remove_conn(player.conn, room_id)
        elif game == "BLACKJACK":
            blackjack.remove_conn(player.conn, room_id)
        elif game == "TTT":
            tictactoe.remove_conn(player.conn, room_id)
        elif game == "ROULETTE":
            roulette.remove_conn(player.conn, room_id)
    except Exception as e:
        print("[ERROR] leave_current_game:", e)

    player.current_game = None
    player.current_room = None


# 房號工具
def _parse_room_id(parts, default_room_id: int):
    if len(parts) >= 3:
        try:
            return int(parts[2])
        except:
            return default_room_id
    return default_room_id


def _default_room_for(game: str):
    try:
        if game == "BIG2":
            return big2.pick_room() or 1
        if game == "BLACKJACK":
            return blackjack.pick_room() or 1
        if game == "TTT":
            return tictactoe.pick_room() or 1
        if game == "ROULETTE":
            return roulette.pick_room() or 1
    except:
        pass
    return 1


def _max_room_for(game: str):
    if game == "BIG2":
        return big2.MAX_ROOMS
    if game == "BLACKJACK":
        return blackjack.MAX_ROOMS
    if game == "TTT":
        return tictactoe.MAX_ROOMS
    if game == "ROULETTE":
        return roulette.MAX_ROOMS
    return None


# 指令
def handle_command(player: Player, raw: str):
    conn = player.conn
    parts = raw.strip().split()
    if not parts:
        return
    cmd = parts[0].upper()

    # ===== HELLO =====
    if cmd == "HELLO":
        if len(parts) != 2:
            send_line(conn, "用法：HELLO <name>")
            return

        new_name = parts[1].strip()
        if not new_name:
            send_line(conn, "名字不能空白")
            return

        with names_lock:
            if new_name in used_names:
                send_line(conn, f"名字已被使用：{new_name}")
                return
            if player.name:
                used_names.discard(player.name)
            used_names.add(new_name)
            player.name = new_name

        send_line(conn, f"歡迎 {player.name}！")
        send_line(conn, "輸入 HELP 查看指令")
        return

    if player.name is None:
        send_line(conn, "請先 HELLO <name>")
        return

    # ===== HELP =====
    if cmd in ("HELP", "?"):
        if not player.current_game:
            send_line(
                conn,
                "==================== 大廳指令 ====================\n"
                "HELLO <name>                     設定暱稱\n"
                "PLAY <GAME> [ROOM_ID](ID：1~50)  進入遊戲房間\n"
                "LEAVE                            回到大廳\n"
                "WHERE                            顯示目前位置\n"
                "STATUS                           顯示個人狀態\n"
                "QUIT                             離線\n"
                "\n"
                "GAME代號:BIG2 / BLACKJACK / TTT / ROULETTE(分別是大老二、21點、井字棋、輪盤)\n"
                "==================================================\n"
            )
            return
        # 在遊戲內：不 return，讓下面分流給各遊戲處理 HELP

    # ===== WHERE / STATUS =====
    if cmd in ("WHERE", "ROOM"):
        send_line(conn, f"目前位置：{player.current_game or 'LOBBY'}"
                        f"{'' if not player.current_room else ' #' + str(player.current_room)}")
        return

    if cmd == "STATUS":
        send_line(conn, f"name={player.name} balance={player.balance} room="
                        f"{player.current_game or 'LOBBY'}"
                        f"{'' if not player.current_room else ' #' + str(player.current_room)}")
        return

    # ===== PLAY =====
    if cmd == "PLAY":
        if len(parts) < 2:
            send_line(conn, "用法：PLAY <BIG2|BLACKJACK|TTT|ROULETTE> [ROOM_ID]")
            return

        game = parts[1].upper()
        leave_current_game(player)

        default_room = _default_room_for(game)
        room_id = _parse_room_id(parts, default_room)

        max_room = _max_room_for(game)
        if max_room is None:
            send_line(conn, "未知遊戲")
            return

        if room_id < 1 or room_id > max_room:
            send_line(conn, f"【{game}】房號範圍只能 1~{max_room}")
            return

        # ★重點：enter() 回傳 True/False，失敗時不能顯示「已進入」
        ok = False
        if game == "BIG2":
            ok = big2.enter(player, room_id)
        elif game == "BLACKJACK":
            ok = blackjack.enter(player, room_id)
        elif game == "TTT":
            ok = tictactoe.enter(player, room_id)
        elif game == "ROULETTE":
            ok = roulette.enter(player, room_id)

        if not ok:
            return

        player.current_game = game
        player.current_room = room_id
        send_line(conn, f"已進入 {game} 房間 #{room_id}")
        send_line(conn, "提示：在房間內輸入 HELP 可查看遊戲指令")
        return

    # ===== LEAVE / QUIT =====
    if cmd == "LEAVE":
        leave_current_game(player)
        send_line(conn, "已回到大廳")
        return

    if cmd == "QUIT":
        send_line(conn, "Bye!")
        raise ConnectionResetError

    # ===== IN GAME =====
    game = player.current_game
    room_id = player.current_room
    if not game:
        send_line(conn, "請先 PLAY 進入遊戲")
        return

    if game == "BIG2":
        big2.handle_command(player, raw, room_id)
    elif game == "BLACKJACK":
        blackjack.handle_command(player, raw, room_id)
    elif game == "TTT":
        tictactoe.handle_command(player, raw, room_id)
    elif game == "ROULETTE":
        roulette.handle_command(player, raw, room_id)
    else:
        send_line(conn, "內部錯誤：未知的 current_game")


# Client Thread
def client_thread(conn, addr):
    player = Player(conn)
    with clients_lock:
        clients[conn] = player

    send_line(conn, "歡迎連線到 TCP Casino Server")
    send_line(conn, "請先輸入：HELLO <name>")

    try:
        while True:
            data = conn.recv(1024)
            if not data:
                break

            player.buffer += data.decode(errors="ignore")
            while "\n" in player.buffer:
                line, player.buffer = player.buffer.split("\n", 1)
                if line.strip():
                    handle_command(player, line)

    except Exception as e:
        print("[ERROR] client_thread:", e)

    finally:
        leave_current_game(player)
        if player.name:
            with names_lock:
                used_names.discard(player.name)
        with clients_lock:
            clients.pop(conn, None)
        try:
            conn.close()
        except:
            pass
        print("[DISCONNECT]", addr)


# Main
def main():
    print("[SERVER] Casino Server 啟動")
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((HOST, PORT))
    s.listen()

    while True:
        conn, addr = s.accept()
        threading.Thread(target=client_thread, args=(conn, addr), daemon=True).start()


if __name__ == "__main__":
    main()
