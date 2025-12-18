import random
import threading

lock = threading.RLock()

RANK_ORDER = "3456789TJQKA2"
SUIT_ORDER = "CDHS"  # 梅花C < 方塊D < 紅心H < 黑桃S

MAX_PLAYERS = 4
MAX_ROOMS = 20

# ====== 籌碼設定 ======
BUY_IN = 100  # 上牌桌付的錢（每局開打前每人先付，贏家通吃底池）


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


def card_key(card: str):
    r, s = card[0], card[1]
    return (RANK_ORDER.index(r), SUIT_ORDER.index(s))


def make_deck():
    deck = [r + s for r in RANK_ORDER for s in SUIT_ORDER]
    random.shuffle(deck)
    return deck


def _new_room_state(room_id: int):
    return {
        "room_id": room_id,
        "players": [],          # [conn]
        "player_objs": {},      # conn -> Player（由 enter() 塞進來，才能動到 balance）
        "names": {},            # conn -> name
        "hands": {},            # conn -> [cards]
        "turn": 0,
        "started": False,
        "last_play": None,      # {"conn":..., "type":..., "cards":[...], "rank":...}
        "pass_count": 0,

        # ====== 大老二規則/狀態 ======
        "first_round": True,    # 第一手必須包含 3C
        "pot": 0,               # 底池
        "paid": set(),          # 本局已付 BUY_IN 的 conn
    }


rooms = {i: _new_room_state(i) for i in range(1, MAX_ROOMS + 1)}


def _room_broadcast(room, msg):
    for c in list(room["players"]):
        send_line(c, msg)


def pick_room():
    with lock:
        for rid, room in rooms.items():
            if len(room["players"]) < MAX_PLAYERS:
                return rid
    return 1


# ★ server 需要 enter() 回傳 True/False
def enter(player, room_id: int):
    # 這裡拿得到 Player 物件，所以把它存進 room，之後才能扣/加 balance
    return add_player(player, room_id)


def remove_conn(conn, room_id: int):
    remove_player(conn, room_id)


def add_player(player, room_id: int):
    conn = player.conn
    name = player.name

    with lock:
        room = rooms.get(room_id)
        if not room:
            send_line(conn, "【BIG2】房間不存在")
            return False

        if conn in room["players"]:
            send_line(conn, f"你已在 BIG2 房間 {room_id}")
            return True

        if len(room["players"]) >= MAX_PLAYERS:
            send_line(conn, f"【BIG2】房間 {room_id} 已滿（最多 {MAX_PLAYERS} 人）")
            return False

        room["players"].append(conn)
        room["player_objs"][conn] = player
        room["names"][conn] = name
        room["hands"][conn] = []

        _room_broadcast(room, f"【BIG2#{room_id}】{name} 進入房間 ({len(room['players'])}/{MAX_PLAYERS})")
        send_line(conn, "在房間內輸入 HELP 可查看指令")

        if len(room["players"]) == MAX_PLAYERS and not room["started"]:
            start_game(room_id)

        return True


def remove_player(conn, room_id: int):
    with lock:
        room = rooms.get(room_id)
        if not room:
            return

        # ====== 若正在遊戲中且該玩家本局已付進桌費：退回並扣回底池 ======
        if conn in room.get("paid", set()):
            p = room["player_objs"].get(conn)
            if p is not None:
                p.balance += BUY_IN
            room["pot"] = max(0, room.get("pot", 0) - BUY_IN)
            room["paid"].discard(conn)
            n = room["names"].get(conn, "Unknown")
            _room_broadcast(room, f"【BIG2#{room_id}】{n} 離開房間，本局進桌費已退回，底池剩餘：{room['pot']}")

        if conn in room["players"]:
            name = room["names"].get(conn, "Unknown")
            room["players"].remove(conn)
            room["names"].pop(conn, None)
            room["hands"].pop(conn, None)
            room["player_objs"].pop(conn, None)
            _room_broadcast(room, f"【BIG2#{room_id}】{name} 離開房間")

        if len(room["players"]) < MAX_PLAYERS:
            reset(room_id)


def reset(room_id: int):
    room = rooms.get(room_id)
    if not room:
        return
    # players/names/player_objs 保留（玩家仍在房間），只重置本局狀態
    room["hands"] = {c: [] for c in room["players"]}
    room["turn"] = 0
    room["started"] = False
    room["last_play"] = None
    room["pass_count"] = 0
    room["first_round"] = True
    room["pot"] = 0
    room["paid"] = set()


def _choose_first_turn_by_3c(room):
    for i, c in enumerate(room["players"]):
        if "3C" in room["hands"].get(c, []):
            return i
    return 0


def _collect_buy_in(room, room_id: int) -> bool:
    room["pot"] = 0
    room["paid"] = set()

    # 先檢查付不付得起，付不起直接踢出避免卡死
    for c in list(room["players"]):
        p = room["player_objs"].get(c)
        if p is None:
            continue
        if p.balance < BUY_IN:
            send_line(c, f"【BIG2#{room_id}】籌碼不足，進桌費 {BUY_IN}，你目前 {p.balance}，已被請出房間")
            name = room["names"].get(c, "Unknown")
            room["players"].remove(c)
            room["names"].pop(c, None)
            room["hands"].pop(c, None)
            room["player_objs"].pop(c, None)
            _room_broadcast(room, f"【BIG2#{room_id}】{name} 籌碼不足，無法入局")

    if len(room["players"]) < MAX_PLAYERS:
        _room_broadcast(room, f"【BIG2#{room_id}】人數不足（需 {MAX_PLAYERS} 人），暫不開局")
        return False

    for c in room["players"]:
        p = room["player_objs"].get(c)
        if p is None:
            continue
        p.balance -= BUY_IN
        room["pot"] += BUY_IN
        room["paid"].add(c)

    _room_broadcast(room, f"【BIG2#{room_id}】本局進桌費每人 {BUY_IN}，底池：{room['pot']}（贏家通吃）")
    return True


def start_game(room_id: int):
    room = rooms.get(room_id)
    if not room:
        return

    if not _collect_buy_in(room, room_id):
        return

    deck = make_deck()
    for i, c in enumerate(room["players"]):
        room["hands"][c] = sorted(deck[i*13:(i+1)*13], key=card_key)

    room["turn"] = _choose_first_turn_by_3c(room)
    room["started"] = True
    room["last_play"] = None
    room["pass_count"] = 0
    room["first_round"] = True

    _room_broadcast(room, f"【BIG2#{room_id}】遊戲開始！")
    for c in room["players"]:
        send_line(c, "你的手牌：" + " ".join(room["hands"][c]))
        p = room["player_objs"].get(c)
        if p is not None:
            send_line(c, f"你的籌碼：{p.balance}（底池：{room['pot']}）")

    first_conn = room["players"][room["turn"]]
    first_name = room["names"].get(first_conn, "?")
    _room_broadcast(room, f"【BIG2#{room_id}】第一手由持有 3C 的玩家 {first_name} 先出（第一手必須包含 3C）")

    broadcast_turn(room_id)


def broadcast_turn(room_id: int):
    room = rooms.get(room_id)
    if not room or not room["players"]:
        return

    cur = room["players"][room["turn"]]
    name = room["names"].get(cur, "?")
    _room_broadcast(room, f"【BIG2#{room_id}】輪到 {name}：MOVE <cards...> 或 PASS / HAND（輸入 HELP 看指令）")

    last = room["last_play"]
    if last:
        lname = room["names"].get(last["conn"], "?")
        _room_broadcast(room, f"【BIG2#{room_id}】上一手：{lname} 出 {last['type']} -> {' '.join(last['cards'])}")
    else:
        _room_broadcast(room, f"【BIG2#{room_id}】目前無上一手（自由出牌）")


def parse_cards(tokens):
    cards = [t.strip().upper() for t in tokens if t.strip()]
    for c in cards:
        if len(c) != 2 or c[0] not in RANK_ORDER or c[1] not in SUIT_ORDER:
            return None
    return cards


def classify(cards):
    cards = sorted(cards, key=card_key)
    ranks = [c[0] for c in cards]

    if len(cards) == 1:
        return ("SINGLE", card_key(cards[0]))

    if len(cards) == 2 and ranks[0] == ranks[1]:
        return ("PAIR", (RANK_ORDER.index(ranks[0]), max(card_key(cards[0])[1], card_key(cards[1])[1])))

    if len(cards) == 3 and len(set(ranks)) == 1:
        return ("TRIPLE", (RANK_ORDER.index(ranks[0]),))

    if len(cards) == 5:
        rank_vals = sorted([RANK_ORDER.index(r) for r in ranks])
        counts = {}
        for r in ranks:
            counts[r] = counts.get(r, 0) + 1
        count_vals = sorted(counts.values(), reverse=True)

        if count_vals == [4, 1]:
            four_rank = max(r for r, v in counts.items() if v == 4)
            kicker = max(r for r, v in counts.items() if v == 1)
            return ("FOUR", (RANK_ORDER.index(four_rank), RANK_ORDER.index(kicker)))

        if count_vals == [3, 2]:
            three_rank = max(r for r, v in counts.items() if v == 3)
            pair_rank = max(r for r, v in counts.items() if v == 2)
            return ("FULLHOUSE", (RANK_ORDER.index(three_rank), RANK_ORDER.index(pair_rank)))

        if len(set(rank_vals)) == 5 and max(rank_vals) - min(rank_vals) == 4:
            return ("STRAIGHT", (max(rank_vals),))

    return (None, None)


def better_play(new_type, new_key, last_type, last_key):
    if last_type is None:
        return True
    if new_type != last_type:
        return False
    return new_key > last_key


def handle_command(player, raw, room_id: int):
    conn = player.conn
    name = player.name

    parts = raw.strip().split()
    if not parts:
        return

    with lock:
        room = rooms.get(room_id)
        if not room:
            send_line(conn, "【BIG2】房間不存在")
            return

        if conn not in room["players"]:
            send_line(conn, f"你不在 BIG2 房間 {room_id}")
            return

        op = parts[0].upper()

        if op in ("HELP", "?"):
            send_line(conn,
                      "【BIG2 指令】\n"
                      "MOVE <cards...>   例如：MOVE 3C TD AS\n"
                      "PASS              放棄此回合（需有上一手才可 PASS）\n"
                      "HAND              查看自己的手牌\n"
                      "CHIPS             查看自己的籌碼（balance）\n"
                      "POT               查看本局底池\n"
                      "（回大廳用：LEAVE）\n"
                      "※本版本為簡化規則：只允許相同牌型互壓\n"
                      f"※每局進桌費 {BUY_IN}，贏家通吃底池\n"
                      "※第一手必須包含梅花三（3C）\n"
                      )
            return

        # ===== 任何時候都可以查 =====
        if op in ("HAND", "SHOW"):
            send_line(conn, "你的手牌：" + " ".join(room["hands"].get(conn, [])))
            return

        if op == "CHIPS":
            send_line(conn, f"你的籌碼：{player.balance}")
            return

        if op == "POT":
            send_line(conn, f"本局底池：{room.get('pot', 0)}（進桌費 {BUY_IN}/人）")
            return

        if not room["started"]:
            send_line(conn, f"BIG2#{room_id} 尚未開始（需 {MAX_PLAYERS} 人）")
            return

        cur = room["players"][room["turn"]]
        if conn != cur:
            send_line(conn, "不是你的回合")
            return

        if op == "PASS":
            if room["last_play"] is None:
                send_line(conn, "目前無上一手，不能 PASS，請出牌")
                return

            room["pass_count"] += 1
            _room_broadcast(room, f"【BIG2#{room_id}】{name} PASS")

            if room["pass_count"] >= 3:
                _room_broadcast(room, f"【BIG2#{room_id}】三人 PASS，重新自由出牌")
                room["last_play"] = None
                room["pass_count"] = 0

            room["turn"] = (room["turn"] + 1) % len(room["players"])
            broadcast_turn(room_id)
            return

        if op == "MOVE":
            if len(parts) < 2:
                send_line(conn, "用法：MOVE <cards...>")
                return
            cards = parse_cards(parts[1:])
            if not cards:
                send_line(conn, "牌格式錯誤，例如：3C TD AS")
                return

            hand = room["hands"][conn]
            for c in cards:
                if c not in hand:
                    send_line(conn, f"你手上沒有 {c}")
                    return

            # ★ 第一手必須包含 3C
            if room.get("first_round", False) and "3C" not in cards:
                send_line(conn, "第一手必須包含梅花三（3C）")
                return

            ctype, ckey = classify(cards)
            if ctype is None:
                send_line(conn, "不支援的牌型（僅：單/對/三/順/葫蘆/鐵支）")
                return

            last = room["last_play"]
            last_type = last["type"] if last else None
            last_key = last["rank"] if last else None

            if not better_play(ctype, ckey, last_type, last_key):
                send_line(conn, "這手不能壓過上一手（不同牌型或大小不足）")
                return

            for c in cards:
                hand.remove(c)

            room["last_play"] = {"conn": conn, "type": ctype, "cards": cards, "rank": ckey}
            room["pass_count"] = 0
            room["first_round"] = False

            _room_broadcast(room, f"【BIG2#{room_id}】{name} 出 {ctype}：{' '.join(cards)}")

            # ★ 出完牌後只回給自己剩餘手牌
            send_line(conn, "你剩下的手牌：" + " ".join(hand))

            if len(hand) == 0:
                # ===== 贏家通吃底池 =====
                pot = room.get("pot", 0)
                _room_broadcast(room, f"【BIG2#{room_id}】{name} 勝利！遊戲結束（獲得底池 {pot}）")

                winner = room["player_objs"].get(conn)
                if winner is not None:
                    winner.balance += pot

                room["pot"] = 0
                room["paid"] = set()

                for c in room["players"]:
                    p = room["player_objs"].get(c)
                    pname = room["names"].get(c, "?")
                    if p is not None:
                        send_line(c, f"【結算】{pname} 籌碼：{p.balance}")

                reset(room_id)
                return

            room["turn"] = (room["turn"] + 1) % len(room["players"])
            broadcast_turn(room_id)
            return

        send_line(conn, "未知指令：輸入 HELP 查看")
