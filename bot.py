import os
import sys
import requests
import json
import time
from datetime import datetime, timedelta
import pytz

# =====================================================================
# НАСТРОЙКИ
# =====================================================================
BOT_TOKEN = os.getenv('BOT_TOKEN')
if not BOT_TOKEN:
    BOT_TOKEN = os.getenv('BOT_TOKEN_PROGNOZ')

CHAT_ID = os.getenv('CHAT_ID_21')
if not CHAT_ID:
    CHAT_ID = os.getenv('CHAT_ID')

if not BOT_TOKEN or not CHAT_ID:
    print("❌ Ошибка: BOT_TOKEN или CHAT_ID не заданы!", flush=True)
    sys.exit(1)

MOSCOW_TZ = pytz.timezone('Europe/Moscow')
BASE_URL = "https://1xlite-1679.pro"
API = f"https://api.telegram.org/bot{BOT_TOKEN}"

messages = {}
processed_games = set()
player_cards_history = {}
dealer_cards_history = {}
game_state_history = {}

SUITS_NAMES = {0: "♠️", 1: "♣️", 2: "♦️", 3: "♥️"}
RANKS = {1: "A", 2: "2", 3: "3", 4: "4", 5: "5", 6: "6", 7: "7", 8: "8", 9: "9", 10: "10", 11: "J", 12: "Q", 13: "K", 14: "A"}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": f"{BASE_URL}/ru/live/2050671-baccara",
    "Cookie": "platform_type=desktop; auid=ua+l6mqq/My6Dm18AzGiAg==; lng=ru; cookies_agree_type=3; tzo=5; is12h=0; fatman_uuid=6130f537-4410-1609-a97d-d8e42c9bd207; che_g=256be28c-6643-4128-98f0-0b48cd8335d1; referral_values=%7B%22type%22%3A%22reflinkid%22%2C%22val%22%3A%22s_50970m_355c_%22%2C%22additional%22%3A%7B%22name_tag%22%3A%22tag%22%7D%7D; reflinkid=s_50970m_355c_; sh.session.id=8fd49537-b74b-421a-937d-c6cd70d37f4f; SESSION=5b56b60163a07a81e5a746330aceeb18; _ga=GA1.1.331026452.1789590750; _ga_7JGWL9SV66=GS2.1.s1789590750$o1$g1$t1789590772$j38$l0$h724394072; window_width=1056"
}

# =====================================================================
# ЖЕСТКИЙ РАСЧЕТ НОМЕРА ИГРЫ ПО ВРЕМЕНИ МСК
# =====================================================================
def get_current_game_number():
    dt = datetime.now(MOSCOW_TZ)
    # Цикл стартует в 03:00 МСК
    if dt.hour < 3:
        base_date = dt - timedelta(days=1)
    else:
        base_date = dt
        
    base = base_date.replace(hour=3, minute=0, second=0, microsecond=0)
    diff = dt - base
    total_minutes = int(diff.total_seconds() // 60)
    game_number = total_minutes + 1
    
    if game_number > 1440:
        game_number = (game_number - 1) % 1440 + 1
        
    return game_number

# =====================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# =====================================================================
def get_active_games():
    try:
        url = f"{BASE_URL}/service-api/main-live-feed/v3/games1x2?cfView=3&count=40&fcountry=1&gr=2336&grMode=4&lng=ru&ref=1&selectedMs=1.236.2050671,10.236"
        response = requests.get(url, headers=HEADERS, timeout=10)
        if response.status_code == 200:
            data = response.json()
            games = data if isinstance(data, list) else data.get("Value", [])
            return [g for g in games if g.get("liga", {}).get("id") == 2050671 and str(g.get("id")) not in processed_games]
    except Exception as e:
        print(f"❌ Ошибка API: {e}", flush=True)
    return []

def parse_cards(value_str):
    if not value_str or value_str == "[]": return []
    try: return json.loads(value_str) if isinstance(json.loads(value_str), list) else []
    except: return []

def format_cards(cards):
    res = []
    for c in cards:
        if not isinstance(c, dict): continue
        suit = SUITS_NAMES.get(c.get("S", 0), "?")
        rank = RANKS.get(c.get("R", 0), str(c.get("R", 0)))
        res.append(f"{rank}{suit}")
    return "".join(res)

def calculate_score(cards):
    score = 0
    for c in cards:
        if not isinstance(c, dict): continue
        r = c.get("R", 0)
        if r in (1, 14): score += 1
        elif 2 <= r <= 9: score += r
    return score % 10

def is_game_finished(state):
    return str(state).lower().strip() in ("win1", "win2", "draw", "finished", "gameover", "endgame", "result", "resultgame", "completed")

def get_arrow(state):
    s = str(state).lower().strip()
    if s == "prematch": return "◀️"
    if s in ("win1", "win2", "draw", "finished", "gameover", "endgame", "result", "resultgame", "completed"): return ""
    return "▶️"

def build_message(game_num, game_id, p_cards, d_cards, p_score, d_score, state):
    p_hand = format_cards(p_cards)
    d_hand = format_cards(d_cards)
    total = p_score + d_score
    if is_game_finished(state):
        tags = " #R" if len(p_cards) == 2 and len(d_cards) == 2 else ""
        if p_score == d_score: return f"#N{game_num} {p_score} ({p_hand}) - 🔰{d_score} ({d_hand}) #X #T{total}{tags} (ID: {game_id})"
        if p_score > d_score: return f"#N{game_num} ✅{p_score} ({p_hand}) - {d_score} ({d_hand}) #П1 #T{total}{tags} (ID: {game_id})"
        return f"#N{game_num} {p_score} ({p_hand}) - ✅{d_score} ({d_hand}) #П2 #T{total}{tags} (ID: {game_id})"
    return f"#N{game_num}. {p_score}({p_hand}) {get_arrow(state)} {d_score}({d_hand}) #T{total} (ID: {game_id})"

def send_message(text):
    try:
        r = requests.post(API + "/sendMessage", json={"chat_id": CHAT_ID, "text": text})
        return r.json()["result"]["message_id"] if r.status_code == 200 else None
    except: return None

def edit_message(message_id, text):
    try:
        r = requests.post(API + "/editMessageText", json={"chat_id": CHAT_ID, "message_id": message_id, "text": text})
        return r.status_code == 200
    except: return False

# =====================================================================
# ОСНОВНОЙ ЦИКЛ
# =====================================================================
def main():
    print("🔄 ПАРСЕР БАККАРА ЗАПУЩЕН", flush=True)
    while True:
        try:
            active_games = get_active_games()
            if not active_games:
                time.sleep(3)
                continue
            
            for game in active_games:
                game_id = str(game.get("id"))
                
                main_stat = game.get("scores", {}).get("statistic", {}).get("main", {})
                p_cards = parse_cards(main_stat.get("P", "[]"))
                d_cards = parse_cards(main_stat.get("B", "[]"))
                state = main_stat.get("S", "")
                
                if not p_cards and not d_cards:
                    continue
                
                # ⚠️ БЕРЕМ НОМЕР ПО ТЕКУЩЕМУ ВРЕМЕНИ МСК
                game_number = get_current_game_number()
                
                p1_str = json.dumps(p_cards, sort_keys=True)
                p2_str = json.dumps(d_cards, sort_keys=True)
                
                if (player_cards_history.get(game_id) == p1_str and 
                    dealer_cards_history.get(game_id) == p2_str and 
                    game_state_history.get(game_id) == state):
                    continue
                
                player_cards_history[game_id] = p1_str
                dealer_cards_history[game_id] = p2_str
                game_state_history[game_id] = state
                
                p_score = calculate_score(p_cards)
                d_score = calculate_score(d_cards)
                msg = build_message(game_number, game_id, p_cards, d_cards, p_score, d_score, state)
                
                if game_id in messages:
                    edit_message(messages[game_id], msg)
                else:
                    msg_id = send_message(msg)
                    if msg_id: messages[game_id] = msg_id
                
                if is_game_finished(state):
                    processed_games.add(game_id)
                
                time.sleep(0.2)
            
            if len(processed_games) > 500:
                processed_games.clear()
                player_cards_history.clear()
                dealer_cards_history.clear()
                game_state_history.clear()
                messages.clear()
            
            time.sleep(2)
        except Exception as e:
            print(f"❌ Ошибка: {e}", flush=True)
            time.sleep(5)

if __name__ == "__main__":
    main()