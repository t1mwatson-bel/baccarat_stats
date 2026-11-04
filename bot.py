
import os
import sys
import requests
import json
import time
from datetime import datetime
import pytz

# =====================================================================
# НАСТРОЙКИ
# =====================================================================

BOT_TOKEN = os.getenv("BOT_TOKEN") or os.getenv("BOT_TOKEN_PROGNOZ")
CHAT_ID = os.getenv("CHAT_ID_21") or os.getenv("CHAT_ID")

if not BOT_TOKEN or not CHAT_ID:
    print("❌ Ошибка: BOT_TOKEN или CHAT_ID не заданы!", flush=True)
    sys.exit(1)

MOSCOW_TZ = pytz.timezone("Europe/Moscow")

BASE_URL = "https://1xlite-1679.pro"
API = f"https://api.telegram.org/bot{BOT_TOKEN}"

# Файл закрепления номеров за играми
GAME_NUMBERS_FILE = "game_numbers.json"

messages = {}
processed_games = set()

player_cards_history = {}
dealer_cards_history = {}
game_state_history = {}

# Номер каждой игры закрепляется за ее ID
game_numbers = {}

SUITS_NAMES = {
    0: "♠️",
    1: "♣️",
    2: "♦️",
    3: "♥️"
}

RANKS = {
    1: "A", 2: "2", 3: "3", 4: "4",
    5: "5", 6: "6", 7: "7", 8: "8",
    9: "9", 10: "10", 11: "J",
    12: "Q", 13: "K", 14: "A"
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": f"{BASE_URL}/ru/live/2050671-baccara",
    "Cookie": "platform_type=desktop; auid=ua+l6mqq/My6Dm18AzGiAg==; lng=ru; cookies_agree_type=3; tzo=5; is12h=0; fatman_uuid=6130f537-4410-1609-a97d-d8e42c9bd207; che_g=256be28c-6643-4128-98f0-0b48cd8335d1; referral_values=%7B%22type%22%3A%22reflinkid%22%2C%22val%22%3A%22s_50970m_355c_%22%2C%22additional%22%3A%7B%22name_tag%22%3A%22tag%22%7D%7D; reflinkid=s_50970m_355c_; sh.session.id=8fd49537-b74b-421a-937d-c6cd70d37f4f; SESSION=5b56b60163a07a81e5a746330aceeb18; _ga=GA1.1.331026452.1789590750; _ga_7JGWL9SV66=GS2.1.s1789590750$o1$g1$t1789590772$j38$l0$h724394072; window_width=1056"
}

# =====================================================================
# ЗАГРУЗКА И СОХРАНЕНИЕ НОМЕРОВ
# =====================================================================

def load_game_numbers():
    global game_numbers

    try:
        if os.path.exists(GAME_NUMBERS_FILE):
            with open(GAME_NUMBERS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

            if isinstance(data, dict):
                game_numbers = data

            print(
                f"💾 Загружено закрепленных номеров: {len(game_numbers)}",
                flush=True
            )

    except Exception as e:
        print(f"⚠️ Ошибка загрузки номеров: {e}", flush=True)
        game_numbers = {}


def save_game_numbers():
    try:
        temp_file = GAME_NUMBERS_FILE + ".tmp"

        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(
                game_numbers,
                f,
                ensure_ascii=False,
                indent=2
            )

        os.replace(temp_file, GAME_NUMBERS_FILE)

    except Exception as e:
        print(f"❌ Ошибка сохранения номеров: {e}", flush=True)


# =====================================================================
# НУМЕРАЦИЯ ПО ВРЕМЕНИ ПЕРВОГО ПОЯВЛЕНИЯ КАРТ
# =====================================================================

def get_current_game_number():
    dt = datetime.now(MOSCOW_TZ)

    # 03:00 = #N1
    # 03:01 = #N2
    # 02:59 = #N1440

    minutes = (dt.hour * 60 + dt.minute - 180) % 1440

    return minutes + 1


def get_game_number(game_id):
    game_id = str(game_id)

    # Если номер уже присвоен, не меняем его
    if game_id in game_numbers:
        return int(game_numbers[game_id])

    # Новая игра получает номер текущей минуты
    number = get_current_game_number()

    game_numbers[game_id] = number

    save_game_numbers()

    print(
        f"🕒 Первые карты игры ID {game_id}. "
        f"Присвоен номер #N{number}",
        flush=True
    )

    return number


# =====================================================================
# ПОЛУЧЕНИЕ ИГР
# =====================================================================

def get_active_games():
    try:
        url = (
            f"{BASE_URL}/service-api/main-live-feed/v3/games1x2"
            "?cfView=3&count=40&fcountry=1&gr=2336&grMode=4"
            "&lng=ru&ref=1&selectedMs=1.236.2050671,10.236"
        )

        response = requests.get(
            url,
            headers=HEADERS,
            timeout=10
        )

        if response.status_code == 200:
            data = response.json()

            games = (
                data if isinstance(data, list)
                else data.get("Value", [])
            )

            return [
                g for g in games
                if g.get("liga", {}).get("id") == 2050671
                and str(g.get("id")) not in processed_games
            ]

    except Exception as e:
        print(f"❌ Ошибка API: {e}", flush=True)

    return []


# =====================================================================
# ОБРАБОТКА КАРТ
# =====================================================================

def parse_cards(value_str):
    if not value_str or value_str == "[]":
        return []

    try:
        data = (
            json.loads(value_str)
            if isinstance(value_str, str)
            else value_str
        )

        return data if isinstance(data, list) else []

    except Exception:
        return []


def format_cards(cards):
    res = []

    for c in cards:
        if not isinstance(c, dict):
            continue

        suit = SUITS_NAMES.get(c.get("S", 0), "?")
        rank = RANKS.get(c.get("R", 0), str(c.get("R", 0)))

        res.append(f"{rank}{suit}")

    return "".join(res)


def calculate_score(cards):
    score = 0

    for c in cards:
        if not isinstance(c, dict):
            continue

        r = c.get("R", 0)

        if r in (1, 14):
            score += 1
        elif 2 <= r <= 9:
            score += r

    return score % 10


# =====================================================================
# СОСТОЯНИЕ ИГРЫ
# =====================================================================

def is_game_finished(state):
    return str(state).lower().strip() in (
        "win1",
        "win2",
        "draw",
        "finished",
        "gameover",
        "endgame",
        "result",
        "resultgame",
        "completed"
    )


def get_arrow(state):
    s = str(state).lower().strip()

    if s == "prematch":
        return "◀️"

    if is_game_finished(s):
        return ""

    return "▶️"


# =====================================================================
# ФОРМИРОВАНИЕ СООБЩЕНИЯ
# =====================================================================

def build_message(
    game_num,
    game_id,
    p_cards,
    d_cards,
    p_score,
    d_score,
    state
):
    p_hand = format_cards(p_cards)
    d_hand = format_cards(d_cards)

    total = p_score + d_score

    if is_game_finished(state):

        tags = (
            " #R"
            if len(p_cards) == 2 and len(d_cards) == 2
            else ""
        )

        if p_score == d_score:
            return (
                f"#N{game_num} {p_score} ({p_hand}) - "
                f"🔰{d_score} ({d_hand}) #X #T{total}"
                f"{tags} (ID: {game_id})"
            )

        if p_score > d_score:
            return (
                f"#N{game_num} ✅{p_score} ({p_hand}) - "
                f"{d_score} ({d_hand}) #П1 #T{total}"
                f"{tags} (ID: {game_id})"
            )

        return (
            f"#N{game_num} {p_score} ({p_hand}) - "
            f"✅{d_score} ({d_hand}) #П2 #T{total}"
            f"{tags} (ID: {game_id})"
        )

    return (
        f"#N{game_num}. {p_score}({p_hand}) "
        f"{get_arrow(state)} {d_score}({d_hand}) "
        f"#T{total} (ID: {game_id})"
    )


# =====================================================================
# TELEGRAM
# =====================================================================

def send_message(text):
    try:
        r = requests.post(
            API + "/sendMessage",
            json={
                "chat_id": CHAT_ID,
                "text": text
            },
            timeout=10
        )

        data = r.json()

        if r.status_code == 200 and data.get("ok"):
            return data["result"]["message_id"]

        print(f"❌ Telegram send error: {data}", flush=True)

    except Exception as e:
        print(f"❌ Ошибка отправки: {e}", flush=True)

    return None


def edit_message(message_id, text):
    try:
        r = requests.post(
            API + "/editMessageText",
            json={
                "chat_id": CHAT_ID,
                "message_id": message_id,
                "text": text
            },
            timeout=10
        )

        data = r.json()

        if data.get("ok"):
            return True

        if "message is not modified" in str(data).lower():
            return True

        print(f"❌ Telegram edit error: {data}", flush=True)

    except Exception as e:
        print(f"❌ Ошибка редактирования: {e}", flush=True)

    return False


# =====================================================================
# ОСНОВНОЙ ЦИКЛ
# =====================================================================

def main():
    load_game_numbers()

    print("🔄 ПАРСЕР БАККАРА ЗАПУЩЕН", flush=True)
    print("🕒 03:00 МСК — #N1", flush=True)
    print("🔁 Цикл #N1 — #N1440", flush=True)
    print("🃏 Номер присваивается при первом появлении карт", flush=True)

    while True:
        try:
            active_games = get_active_games()

            if not active_games:
                time.sleep(3)
                continue

            for game in active_games:

                game_id = str(game.get("id"))

                main_stat = (
                    game.get("scores", {})
                    .get("statistic", {})
                    .get("main", {})
                )

                p_cards = parse_cards(main_stat.get("P", "[]"))
                d_cards = parse_cards(main_stat.get("B", "[]"))

                state = main_stat.get("S", "")

                # -------------------------------------------------
                # НОМЕР НЕ ПРИСВАИВАЕМ, ПОКА НЕТ КАРТ
                # -------------------------------------------------

                if not p_cards and not d_cards:
                    continue

                # -------------------------------------------------
                # ПЕРВОЕ ПОЯВЛЕНИЕ КАРТ — ПРИСВОЕНИЕ НОМЕРА
                # -------------------------------------------------

                game_number = get_game_number(game_id)

                p1_str = json.dumps(
                    p_cards,
                    sort_keys=True
                )

                p2_str = json.dumps(
                    d_cards,
                    sort_keys=True
                )

                # -------------------------------------------------
                # ПРОВЕРКА ИЗМЕНЕНИЙ
                # -------------------------------------------------

                if (
                    player_cards_history.get(game_id) == p1_str
                    and dealer_cards_history.get(game_id) == p2_str
                    and game_state_history.get(game_id) == state
                ):
                    continue

                player_cards_history[game_id] = p1_str
                dealer_cards_history[game_id] = p2_str
                game_state_history[game_id] = state

                # -------------------------------------------------
                # ПОДСЧЕТ РЕЗУЛЬТАТА
                # -------------------------------------------------

                p_score = calculate_score(p_cards)
                d_score = calculate_score(d_cards)

                msg = build_message(
                    game_number,
                    game_id,
                    p_cards,
                    d_cards,
                    p_score,
                    d_score,
                    state
                )

                # -------------------------------------------------
                # ОТПРАВКА И ОБНОВЛЕНИЕ
                # -------------------------------------------------

                if game_id in messages:
                    edit_message(
                        messages[game_id],
                        msg
                    )

                else:
                    msg_id = send_message(msg)

                    if msg_id:
                        messages[game_id] = msg_id

                # -------------------------------------------------
                # ЗАВЕРШЕННАЯ ИГРА
                # -------------------------------------------------

                if is_game_finished(state):
                    processed_games.add(game_id)

                time.sleep(0.2)

            time.sleep(2)

        except Exception as e:
            print(
                f"❌ Ошибка основного цикла: {e}",
                flush=True
            )

            time.sleep(5)


if __name__ == "__main__":
    main()
