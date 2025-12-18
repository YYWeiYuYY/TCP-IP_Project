import threading

lock = threading.RLock()

WINS = [
    (0,1,2),(3,4,5),(6,7,8),
    (0,3,6),(1,4,7),(2,5,8),
    (0,4,8),(2,4,6)
]

MAX_PLAYERS = 2
MAX_ROOMS = 50


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


def _broadcast(room, msg):
    for c in list(room["players"]):
        send_line(c, msg)


def _new_room_state(room_id: int):
    return {
        "room_id": room_id,
        "board": [" "] * 9,
        "players": [],   # conn
        "names": {},
        "turn": 0,
        "active": False,
        "waiting_rematch": set()
    }


rooms = {i: _new_room_state(i) for i in range(1, MAX_ROOMS + 1)}


def pick_room():
    with lock:
        for rid, room in rooms.items():
            if len(room["players"]) < MAX_PLAYERS:
                return rid
    return 1


def _hard_reset(room_id: int):
    room = rooms.get(room_id)
    if not room:
        return
    keep_players = list(room["players"])
    keep_names = dict(room["names"])
    rooms[room_id] = _new_room_state(room_id)
    rooms[room_id]["players"] = keep_players
    rooms[room_id]["names"] = keep_names


def _show_board(room_id: int):
    room = rooms.get(room_id)
    if not room:
        return
    b = room["board"]
    view = (
        f"{b[0]}|{b[1]}|{b[2]}\n"
        f"-+-+-\n"
        f"{b[3]}|{b[4]}|{b[5]}\n"
        f"-+-+-\n"
        f"{b[6]}|{b[7]}|{b[8]}\n"
    )
    _broadcast(room, view)


def _broadcast_turn(room_id: int):
    room = rooms.get(room_id)
    if not room or not room["players"]:
        return
    cur = room["players"][room["turn"]]
    name = room["names"].get(cur, "?")
    mark = "X" if room["turn"] == 0 else "O"
    _broadcast(room, f"【TTT#{room_id}】輪到 {name} ({mark})：MOVE <0-8>（輸入 HELP 看指令）")


def _check_win(room):
    b = room["board"]
    for a, b1, c in WINS:
        if b[a] != " " and b[a] == b[b1] == b[c]:
            return True
    return False


def _check_draw(room):
    return all(x != " " for x in room["board"])


def _start_match(room_id: int):
    room = rooms.get(room_id)
    if not room:
        return
    room["board"] = [" "] * 9
    room["turn"] = 0
    room["active"] = True
    room["waiting_rematch"] = set()
    _broadcast(room, f"【TTT#{room_id}】遊戲開始！")
    _show_board(room_id)
    _broadcast_turn(room_id)


# ★server 需要 enter() 回傳 True/False
def enter(player, room_id: int):
    return add_player(player.conn, player.name, room_id)


def remove_conn(conn, room_id: int):
    remove_player(conn, room_id)


def add_player(conn, name, room_id: int):
    with lock:
        room = rooms.get(room_id)
        if not room:
            send_line(conn, "【TTT】房間不存在")
            return False

        if conn in room["players"]:
            send_line(conn, f"你已在井字棋房間 {room_id}")
            return True

        if len(room["players"]) >= MAX_PLAYERS:
            send_line(conn, f"井字棋房間 {room_id} 已滿（最多 {MAX_PLAYERS} 人）")
            return False

        room["players"].append(conn)
        room["names"][conn] = name
        _broadcast(room, f"【TTT#{room_id}】{name} 進入房間 ({len(room['players'])}/{MAX_PLAYERS})")

        if len(room["players"]) == MAX_PLAYERS:
            _start_match(room_id)
        else:
            send_line(conn, "等待另一位玩家加入...（可先輸入 HELP 看指令）")

        return True


def remove_player(conn, room_id: int):
    with lock:
        room = rooms.get(room_id)
        if not room:
            return
        if conn in room["players"]:
            name = room["names"].get(conn, "?")
            room["players"].remove(conn)
            room["names"].pop(conn, None)
            room["waiting_rematch"].discard(conn)
            _broadcast(room, f"【TTT#{room_id}】{name} 離開房間")

        _hard_reset(room_id)


def handle_command(player, raw, room_id: int):
    conn = player.conn
    name = player.name

    parts = raw.strip().split()
    if not parts:
        return

    with lock:
        room = rooms.get(room_id)
        if not room:
            send_line(conn, "【TTT】房間不存在")
            return
        if conn not in room["players"]:
            send_line(conn, f"你不在井字棋房間 {room_id}")
            return

        op = parts[0].upper()

        if op in ("HELP", "?"):
            send_line(conn,
                      "【TTT 指令】\n"
                      "MOVE <0-8>   下棋（0~8 對應棋盤格）\n"
                      "REMATCH      重賽\n"
                      "（回大廳用：LEAVE）\n")
            return

        if op == "REMATCH":
            if len(room["players"]) != 2:
                send_line(conn, "目前人數不足，無法重賽")
                return
            room["waiting_rematch"].add(conn)
            send_line(conn, "你已同意重賽，等待對手...")
            if len(room["waiting_rematch"]) == 2:
                _broadcast(room, f"【TTT#{room_id}】雙方同意重賽！")
                _start_match(room_id)
            return

        if op != "MOVE":
            send_line(conn, "未知指令：輸入 HELP 查看")
            return

        if not room["active"]:
            send_line(conn, "遊戲尚未開始或已結束（可輸入 REMATCH 重賽）")
            return

        cur = room["players"][room["turn"]]
        if conn != cur:
            send_line(conn, "不是你的回合")
            return

        if len(parts) != 2:
            send_line(conn, "用法：MOVE <0-8>")
            return

        try:
            pos = int(parts[1])
        except:
            send_line(conn, "MOVE 位置必須是 0~8 的整數")
            return

        if pos < 0 or pos > 8:
            send_line(conn, "MOVE 位置必須在 0~8")
            return

        if room["board"][pos] != " ":
            send_line(conn, "該位置已被下過")
            return

        mark = "X" if room["turn"] == 0 else "O"
        room["board"][pos] = mark

        _show_board(room_id)

        if _check_win(room):
            _broadcast(room, f"【TTT#{room_id}】{name} ({mark}) 獲勝！")
            room["active"] = False
            _broadcast(room, "輸入 REMATCH 可重賽")
            return

        if _check_draw(room):
            _broadcast(room, f"【TTT#{room_id}】平手！")
            room["active"] = False
            _broadcast(room, "輸入 REMATCH 可重賽")
            return

        room["turn"] = 1 - room["turn"]
        _broadcast_turn(room_id)
