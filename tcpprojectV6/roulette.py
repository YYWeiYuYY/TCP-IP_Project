import random
import threading

lock = threading.RLock()

RED_NUMS = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}
BLACK_NUMS = {2,4,6,8,10,11,13,15,17,20,22,24,26,28,29,31,33,35}

MAX_ROOMS = 50
MAX_PLAYERS = 20


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


def send_to_player(player, msg: str):
    try:
        send_line(player.conn, msg)
    except:
        pass


def broadcast_players(players, msg: str):
    for p in list(players):
        try:
            send_line(p.conn, msg)
        except:
            pass


def _new_room_state(room_id: int):
    return {
        "room_id": room_id,
        "players": [],
        "bets": {},   # player -> list[bet]
    }


rooms = {i: _new_room_state(i) for i in range(1, MAX_ROOMS + 1)}


def pick_room():
    """挑一個比較空的房間（人數最少的）"""
    with lock:
        best_rid = 1
        best_n = None
        for rid, room in rooms.items():
            n = len(room["players"])
            if best_n is None or n < best_n:
                best_n = n
                best_rid = rid
        return best_rid


# server 需要 enter() 回傳 True/False
def enter(player, room_id: int):
    with lock:
        room = rooms.get(room_id)
        if not room:
            send_to_player(player, "【ROULETTE】房間不存在")
            return False

        if player in room["players"]:
            return True

        if len(room["players"]) >= MAX_PLAYERS:
            send_to_player(player, f"【ROULETTE】房間 {room_id} 已滿（最多 {MAX_PLAYERS} 人）")
            return False

        room["players"].append(player)
        room["bets"].setdefault(player, [])

    send_to_player(player,
                   f"你已進入【輪盤#{room_id}】\n"
                   "在房間內輸入：HELP 查看指令\n")
    return True


def remove_conn(conn, room_id: int):
    with lock:
        room = rooms.get(room_id)
        if not room:
            return
        remove = [p for p in room["players"] if p.conn is conn]
        for p in remove:
            room["players"].remove(p)
            room["bets"].pop(p, None)


def handle_command(player, raw, room_id: int):
    parts = raw.strip().split()
    if not parts:
        return
    cmd = parts[0].upper()

    with lock:
        room = rooms.get(room_id)
        if not room:
            send_to_player(player, "【ROULETTE】房間不存在")
            return
        if player not in room["players"]:
            send_to_player(player, "請先 PLAY ROULETTE 進入房間")
            return

    if cmd in ("HELP", "?"):
        send_to_player(player,
                       "【ROULETTE 指令】\n"
                       "BETR NUM <0~36> <amt>\n"
                       "BETR RED <amt>\n"
                       "BETR BLACK <amt>\n"
                       "BETR ODD <amt>\n"
                       "BETR EVEN <amt>\n"
                       "SPIN    開盤\n"
                       "BETS    看自己下注\n"
                       "RSTATUS 看目前下注統計\n"
                       "（回大廳用：LEAVE）\n")
        return

    if cmd == "BETR":
        if len(parts) == 3:
            bet_type = parts[1]
            amount = parts[2]
            roulette_bet(player, room_id, bet_type, None, amount)
            return
        if len(parts) == 4:
            bet_type = parts[1]
            value_str = parts[2]
            amount = parts[3]
            roulette_bet(player, room_id, bet_type, value_str, amount)
            return
        send_to_player(player, "用法：BETR RED <amt>  或  BETR NUM <0~36> <amt>")
        return

    if cmd == "SPIN":
        roulette_spin(player, room_id)
        return

    if cmd == "BETS":
        roulette_bets(player, room_id)
        return

    if cmd in ("RSTATUS", "RSTAT"):
        roulette_status(player, room_id)
        return

    send_to_player(player, "未知指令：輸入 HELP 查看")


def roulette_bet(player, room_id: int, bet_type, value_str, amount_str):
    with lock:
        room = rooms.get(room_id)
        if not room:
            send_to_player(player, "【ROULETTE】房間不存在")
            return

        try:
            amount = int(amount_str)
        except:
            send_to_player(player, "下注金額必須是整數")
            return
        if amount <= 0:
            send_to_player(player, "下注金額必須 > 0")
            return
        if player.balance < amount:
            send_to_player(player, "餘額不足")
            return

        bet_type = bet_type.upper()
        value = None

        if bet_type == "NUM":
            if value_str is None:
                send_to_player(player, "用法：BETR NUM <0~36> <amt>")
                return
            try:
                value = int(value_str)
            except:
                send_to_player(player, "NUM 下注需要數字 0~36")
                return
            if value < 0 or value > 36:
                send_to_player(player, "NUM 下注範圍 0~36")
                return
        elif bet_type in ("RED", "BLACK", "ODD", "EVEN"):
            value = None
        else:
            send_to_player(player, "下注類型錯誤：NUM/RED/BLACK/ODD/EVEN")
            return

        player.balance -= amount
        room["bets"].setdefault(player, [])
        room["bets"][player].append({"type": bet_type, "value": value, "amount": amount})

    send_to_player(player, f"下注成功：{bet_type} {'' if value is None else value} {amount}")
    with lock:
        broadcast_players(room["players"], f"【輪盤#{room_id}】{player.name} 下了一筆注。")


def roulette_spin(player, room_id: int):
    with lock:
        room = rooms.get(room_id)
        if not room:
            send_to_player(player, "【ROULETTE】房間不存在")
            return
        if not any(room["bets"].values()):
            send_to_player(player, "目前沒有任何下注，無法轉輪")
            return

        result = random.randint(0, 36)

    color = "綠"
    if result in RED_NUMS:
        color = "紅"
    elif result in BLACK_NUMS:
        color = "黑"

    with lock:
        broadcast_players(room["players"], f"【輪盤#{room_id}】開獎：{result} ({color})")

        for p, blist in list(room["bets"].items()):
            win = 0
            for b in blist:
                t = b["type"]
                v = b["value"]
                amt = b["amount"]

                if t == "NUM":
                    if v == result:
                        win += amt * 36
                elif t == "RED":
                    if result in RED_NUMS:
                        win += amt * 2
                elif t == "BLACK":
                    if result in BLACK_NUMS:
                        win += amt * 2
                elif t == "ODD":
                    if result != 0 and result % 2 == 1:
                        win += amt * 2
                elif t == "EVEN":
                    if result != 0 and result % 2 == 0:
                        win += amt * 2

            if win > 0:
                p.balance += win
                send_to_player(p, f"你這輪贏得：{win}，目前餘額：{p.balance}")
            else:
                send_to_player(p, f"你這輪沒中，目前餘額：{p.balance}")

            room["bets"][p] = []


def roulette_bets(player, room_id: int):
    with lock:
        room = rooms.get(room_id)
        if not room:
            send_to_player(player, "【ROULETTE】房間不存在")
            return
        blist = room["bets"].get(player, [])
        if not blist:
            send_to_player(player, "你目前沒有下注")
            return
        lines = ["你目前下注："]
        for b in blist:
            lines.append(f" - {b['type']} {'' if b['value'] is None else b['value']} {b['amount']}")
        send_to_player(player, "\n".join(lines))


def roulette_status(player, room_id: int):
    with lock:
        room = rooms.get(room_id)
        if not room:
            send_to_player(player, "【ROULETTE】房間不存在")
            return
        total = 0
        bettors = 0
        for p, blist in room["bets"].items():
            if blist:
                bettors += 1
                total += sum(b["amount"] for b in blist)
        send_to_player(player, f"【ROULETTE#{room_id}】下注人數：{bettors}，總下注：{total}")
