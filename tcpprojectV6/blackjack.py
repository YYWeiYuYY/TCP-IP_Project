import random
import threading

lock = threading.RLock()

RANKS = "A23456789TJQK"
SUITS = "CDHS"

MIN_PLAYERS = 2
MAX_PLAYERS = 5
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


def _make_deck():
    deck = [r + s for r in RANKS for s in SUITS] * 2
    random.shuffle(deck)
    return deck


def _card_value(card):
    r = card[0]
    if r in "TJQK":
        return 10
    if r == "A":
        return 11
    return int(r)


def _hand_value(hand):
    total = sum(_card_value(c) for c in hand)
    aces = sum(1 for c in hand if c[0] == "A")
    while total > 21 and aces > 0:
        total -= 10
        aces -= 1
    return total


def _new_room_state(room_id: int):
    return {
        "room_id": room_id,
        "room_players": [],   # 在房間的人（可觀戰）
        "seated": [],         # 參與本局
        "bets": {},
        "hands": {},
        "done": set(),
        "dealer": [],
        "deck": [],
        "in_round": False,
        "turn_idx": 0,
    }


rooms = {i: _new_room_state(i) for i in range(1, MAX_ROOMS + 1)}


def _broadcast(room, msg):
    broadcast_players(room["room_players"], msg)


def pick_room():
    with lock:
        for rid, room in rooms.items():
            if len(room["seated"]) < MAX_PLAYERS and not room["in_round"]:
                return rid
    return 1


# ★server 需要 enter() 回傳 True/False
def enter(player, room_id: int):
    with lock:
        room = rooms.get(room_id)
        if not room:
            send_to_player(player, "【BLACKJACK】房間不存在")
            return False
        if player not in room["room_players"]:
            room["room_players"].append(player)

    send_to_player(player,
                   f"你已進入【BLACKJACK#{room_id}】\n"
                   "在房間內輸入：HELP 查看指令\n")
    return True


def remove_conn(conn, room_id: int):
    with lock:
        room = rooms.get(room_id)
        if not room:
            return

        rm_room = [p for p in room["room_players"] if p.conn is conn]
        for p in rm_room:
            room["room_players"].remove(p)

        rm_seated = [p for p in room["seated"] if p.conn is conn]
        for p in rm_seated:
            _remove_from_round(room, p, reason="disconnect/leave")

        if room["in_round"] and len(room["seated"]) < MIN_PLAYERS:
            _broadcast(room, f"【BLACKJACK#{room_id}】人數不足，本局中止，退回下注")
            _refund_all_and_reset(room)


def handle_command(player, raw, room_id: int):
    parts = raw.strip().split()
    if not parts:
        return
    cmd = parts[0].upper()

    with lock:
        room = rooms.get(room_id)
        if not room:
            send_to_player(player, "【BLACKJACK】房間不存在")
            return
        if player not in room["room_players"]:
            send_to_player(player, f"你不在 BLACKJACK#{room_id}（請 PLAY BLACKJACK {room_id}）")
            return

        if cmd in ("HELP", "?"):
            send_to_player(player,
                           "【BLACKJACK 指令】\n"
                           "JOIN <amt>   加入本局並下注\n"
                           "START        開始發牌（至少2人JOIN）\n"
                           "HIT          要牌（輪到你才可用）\n"
                           "STAND        停牌（輪到你才可用）\n"
                           "STATUS       查看狀態\n"
                           "（回大廳用：LEAVE）\n")
            return

        if cmd == "STATUS":
            _status(room, player)
            return

        if cmd == "JOIN":
            if len(parts) != 2:
                send_to_player(player, "用法：JOIN <amt>")
                return
            if room["in_round"]:
                send_to_player(player, "本局已開始，請等待本局結束後再 JOIN")
                return
            try:
                amt = int(parts[1])
            except:
                send_to_player(player, "JOIN 金額必須是整數")
                return
            _join(room, player, amt)
            return

        if cmd == "START":
            _start(room)
            return

        if cmd in ("HIT", "STAND"):
            if not room["in_round"]:
                send_to_player(player, "目前沒有進行中的牌局，先 JOIN 再 START")
                return
            _action(room, player, cmd)
            return

        send_to_player(player, "未知指令：輸入 HELP 查看")


def _join(room, player, amt):
    if amt <= 0:
        send_to_player(player, "下注必須 > 0")
        return
    if player.balance < amt:
        send_to_player(player, "餘額不足")
        return
    if player in room["seated"]:
        send_to_player(player, "你已在本局座位中")
        return
    if len(room["seated"]) >= MAX_PLAYERS:
        send_to_player(player, "本桌已滿")
        return

    player.balance -= amt
    room["seated"].append(player)
    room["bets"][player] = amt
    room["hands"][player] = []
    room["done"].discard(player)

    _broadcast(room, f"【BLACKJACK#{room['room_id']}】{player.name} JOIN 下注 {amt}（本局 {len(room['seated'])} 人）")


def _start(room):
    if room["in_round"]:
        _broadcast(room, f"【BLACKJACK#{room['room_id']}】本局已開始")
        return
    if len(room["seated"]) < MIN_PLAYERS:
        _broadcast(room, f"【BLACKJACK#{room['room_id']}】至少需要 {MIN_PLAYERS} 人 JOIN 才能 START")
        return

    room["in_round"] = True
    room["turn_idx"] = 0
    room["deck"] = _make_deck()

    room["dealer"] = [room["deck"].pop(), room["deck"].pop()]
    room["done"] = set()

    for p in room["seated"]:
        room["hands"][p] = [room["deck"].pop(), room["deck"].pop()]

    _broadcast(room, f"【BLACKJACK#{room['room_id']}】本局開始！")
    _broadcast(room, f"莊家明牌：{room['dealer'][0]} ?")

    for p in room["seated"]:
        hv = _hand_value(room["hands"][p])
        send_to_player(p, f"你的手牌：{' '.join(room['hands'][p])} (={hv})")
        if hv == 21:
            room["done"].add(p)

    _prompt_turn(room)


def _prompt_turn(room):
    if not room["in_round"]:
        return

    if room["seated"] and all(p in room["done"] for p in room["seated"]):
        _dealer_play_and_settle(room)
        return

    n = len(room["seated"])
    if n == 0:
        return

    if room["turn_idx"] >= n:
        room["turn_idx"] = 0

    for _ in range(n):
        cur = room["seated"][room["turn_idx"]]
        if cur not in room["done"]:
            _broadcast(room, f"【BLACKJACK#{room['room_id']}】輪到 {cur.name}：HIT 或 STAND（輸入 HELP 可看指令）")
            return
        room["turn_idx"] = (room["turn_idx"] + 1) % n


def _action(room, player, cmd):
    if player not in room["seated"]:
        send_to_player(player, "你沒有 JOIN 本局")
        return

    if room["turn_idx"] >= len(room["seated"]):
        room["turn_idx"] = 0

    cur = room["seated"][room["turn_idx"]]
    if player != cur:
        send_to_player(player, f"不是你的回合（目前輪到 {cur.name}）")
        return
    if player in room["done"]:
        send_to_player(player, "你已結束行動")
        return

    if cmd == "HIT":
        if not room["deck"]:
            room["deck"] = _make_deck()
        room["hands"][player].append(room["deck"].pop())
        hv = _hand_value(room["hands"][player])

        _broadcast(room, f"【BLACKJACK#{room['room_id']}】{player.name} HIT 抽到 {room['hands'][player][-1]} (={hv})")
        if hv > 21:
            _broadcast(room, f"【BLACKJACK#{room['room_id']}】{player.name} 爆牌！")
            room["done"].add(player)

        room["turn_idx"] = (room["turn_idx"] + 1) % len(room["seated"])
        _prompt_turn(room)
        return

    if cmd == "STAND":
        hv = _hand_value(room["hands"][player])
        _broadcast(room, f"【BLACKJACK#{room['room_id']}】{player.name} STAND (={hv})")
        room["done"].add(player)

        room["turn_idx"] = (room["turn_idx"] + 1) % len(room["seated"])
        _prompt_turn(room)
        return


def _dealer_play_and_settle(room):
    while _hand_value(room["dealer"]) < 17:
        if not room["deck"]:
            room["deck"] = _make_deck()
        room["dealer"].append(room["deck"].pop())

    dv = _hand_value(room["dealer"])
    _broadcast(room, f"【BLACKJACK#{room['room_id']}】莊家攤牌：{' '.join(room['dealer'])} (={dv})")

    for p in list(room["seated"]):
        bet = room["bets"].get(p, 0)
        pv = _hand_value(room["hands"].get(p, []))

        if pv > 21:
            send_to_player(p, f"你爆牌，輸 {bet}（balance={p.balance})")
            continue

        if dv > 21 or pv > dv:
            gain = bet * 2
            p.balance += gain
            send_to_player(p, f"你贏了！+{gain}（balance={p.balance})")
        elif pv == dv:
            p.balance += bet
            send_to_player(p, f"平手，退回 {bet}（balance={p.balance})")
        else:
            send_to_player(p, f"你輸了 {bet}（balance={p.balance})")

    _broadcast(room, f"【BLACKJACK#{room['room_id']}】本局結束。可再次 JOIN 下一局。")
    _reset_round_keep_room(room)


def _status(room, player):
    lines = []
    lines.append(f"【BLACKJACK#{room['room_id']}】in_round={room['in_round']}")
    lines.append(f"房間人數={len(room['room_players'])}  本局座位={len(room['seated'])}")

    if room["seated"]:
        lines.append("本局玩家：")
        for p in room["seated"]:
            bet = room["bets"].get(p, 0)
            hv = _hand_value(room["hands"].get(p, [])) if room["hands"].get(p) else 0
            done = "DONE" if p in room["done"] else "PLAY"
            lines.append(f" - {p.name}: bet={bet} handValue={hv} {done}")

    if room["in_round"] and room["dealer"]:
        lines.append(f"莊家明牌：{room['dealer'][0]} ?")
        cur = room["seated"][room["turn_idx"]] if room["seated"] else None
        lines.append(f"輪到：{cur.name if cur else '(none)'}")

    send_to_player(player, "\n".join(lines))


def _remove_from_round(room, player, reason="leave"):
    bet = room["bets"].get(player, 0)
    if bet > 0:
        player.balance += bet

    room["bets"].pop(player, None)
    room["hands"].pop(player, None)
    room["done"].discard(player)

    if player in room["seated"]:
        room["seated"].remove(player)

    if room["seated"]:
        room["turn_idx"] %= len(room["seated"])
    else:
        room["turn_idx"] = 0

    _broadcast(room, f"【BLACKJACK#{room['room_id']}】{player.name} 離開本局（{reason}）")


def _refund_all_and_reset(room):
    for p in list(room["seated"]):
        bet = room["bets"].get(p, 0)
        if bet > 0:
            p.balance += bet
    _reset_round_keep_room(room)


def _reset_round_keep_room(room):
    room["seated"] = []
    room["bets"] = {}
    room["hands"] = {}
    room["done"] = set()
    room["dealer"] = []
    room["deck"] = []
    room["in_round"] = False
    room["turn_idx"] = 0