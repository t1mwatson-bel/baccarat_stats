import os
import sys
import requests
import json
import re
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

print(f"✅ BOT_TOKEN: {BOT_TOKEN[:5]}...", flush=True)
print(f"✅ CHAT_ID: {CHAT_ID}", flush=True)

MOSCOW_TZ = pytz.timezone('Europe/Moscow')
BASE_URL = "https://1xlite-6308.pro"

API = f"https://api.telegram.org/bot{BOT_TOKEN}"
messages = {}
processed_games = set()
game_numbers = {}
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

print("✅ Настройки для Baccarat загружены", flush=True)

# =====================================================================
# ФУНКЦИИ
# =====================================================================
def get_game_number():
    """Номер игры от 1 до 1440 (каждую минуту, старт в 03:00)"""
    now = datetime.now(MOSCOW_TZ)
    start = now.replace(hour=3, minute=0, second=0, microsecond=0)
    if now < start:
        start = start - timedelta(days=1)
    diff_minutes = (now - start).total_seconds() / 60
    game_number = int(diff_minutes) % 1440 + 1
    return int(game_number)

def get_active_games():
    """Получает список активных игр Баккара"""
    try:
        url = f"{BASE_URL}/service-api/main-live-feed/v3/games1x2?cfView=3&count=40&fcountry=1&gr=2336&grMode=4&lng=ru&ref=1&selectedMs=1.236.2050671,10.236"
        response = requests.get(url, headers=HEADERS, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            
            if isinstance(data, list):
                games = data
            elif isinstance(data, dict) and "Value" in data:
                games = data.get("Value", [])
            else:
                return []
            
            active_games = []
            for game in games:
                if game.get("liga", {}).get("id") == 2050671:
                    game_id = game.get("id")
                    if game_id and str(game_id) not in processed_games:
                        active_games.append(game)
            
            return active_games
        else:
            print(f"⚠️ Статус API: {response.status_code}", flush=True)
    except Exception as e:
        print(f"❌ Ошибка: {e}", flush=True)
    
    return []

def parse_cards(value_str):
    """Парсит карты из JSON строки"""
    if not value_str or value_str == "[]":
        return []
    try:
        cards = json.loads(value_str)
        if isinstance(cards, list):
            return cards
        return []
    except:
        return []

def format_cards(cards):
    """Форматирует карты с эмодзи"""
    if not cards:
        return ""
    result = []
    for c in cards:
        if not isinstance(c, dict):
            continue
        s = c.get("S", 0)
        r = c.get("R", 0)
        suit = SUITS_NAMES.get(s, "?")
        rank = RANKS.get(r, str(r))
        result.append(f"{rank}{suit}")
    return "".join(result)

def calculate_score(cards):
    """Подсчет очков в баккаре: A=1, 2-9=номинал, 10/J/Q/K=0, сумма % 10"""
    if not cards:
        return 0
    score = 0
    for c in cards:
        if not isinstance(c, dict):
            continue
        r = c.get("R", 0)
        if r == 1 or r == 14:   # Туз (1 или 14) = 1 очко
            score += 1
        elif 2 <= r <= 9:
            score += r
        # 10, 11, 12, 13 = 0
    return score % 10

def is_game_finished(state, player_cards, dealer_cards, p_score, d_score):
    """Проверяет, завершена ли игра"""
    if not state:
        return False
    
    state_str = str(state).lower().strip()
    
    # Prematch = до игры
    if state_str == "prematch":
        return False
    
    # Игра завершена
    if state_str in ("finished", "gameover", "endgame", "result", "resultgame", "completed"):
        return True
    
    # DealerMove — если у кого-то 8 или 9 (натуральная победа), завершаем
    if state_str == "dealermove":
        if p_score >= 8 or d_score >= 8:
            return True
        return False
    
    # PlayerMove
    if state_str == "playermove":
        if p_score >= 8 or d_score >= 8:
            return True
        return False
    
    return False

def get_arrow(state):
    """Определяет стрелку"""
    if not state:
        return "▶️"
    state_str = str(state).lower().strip()
    if state_str == "prematch":
        return "◀️"
    if state_str in ("finished", "gameover", "endgame", "result", "resultgame", "completed"):
        return ""
    return "▶️"

def build_message(game_num, game_id, player_cards, dealer_cards, p_score, d_score, state):
    p_hand = format_cards(player_cards)
    d_hand = format_cards(dealer_cards)
    total = p_score + d_score
    
    finished = is_game_finished(state, player_cards, dealer_cards, p_score, d_score)
    
    if finished:
        tags = []
        if len(player_cards) == 2 and len(dealer_cards) == 2:
            tags.append("#R")
        
        if p_score == d_score:
            tags.append("#X")
        
        tag_str = " " + " ".join(tags) if tags else ""
        
        if p_score > d_score:
            return f"#N{game_num} ✅{p_score} ({p_hand}) - {d_score} ({d_hand}) #П1 #T{total}{tag_str} (ID: {game_id})"
        elif d_score > p_score:
            return f"#N{game_num} {p_score} ({p_hand}) - ✅{d_score} ({d_hand}) #П2 #T{total}{tag_str} (ID: {game_id})"
        else:
            return f"#N{game_num} {p_score} ({p_hand}) - 🔰{d_score} ({d_hand}) #X #T{total}{tag_str} (ID: {game_id})"
    
    arrow = get_arrow(state)
    return f"#N{game_num}. {p_score}({p_hand}) {arrow} {d_score}({d_hand}) #T{total} (ID: {game_id})"

def send_message(text):
    try:
        r = requests.post(API + "/sendMessage", json={"chat_id": CHAT_ID, "text": text})
        if r.status_code == 200:
            return r.json()["result"]["message_id"]
        else:
            print(f"⚠️ Ошибка sendMessage: {r.status_code}, {r.text[:200]}", flush=True)
    except Exception as e:
        print(f"❌ Ошибка отправки: {e}", flush=True)
    return None

def edit_message(message_id, text):
    try:
        url = f"{API}/editMessageText"
        payload = {"chat_id": CHAT_ID, "message_id": message_id, "text": text}
        r = requests.post(url, json=payload)
        if r.status_code != 200:
            print(f"⚠️ Ошибка editMessage: {r.status_code}, {r.text[:200]}", flush=True)
        return r.status_code == 200
    except Exception as e:
        print(f"❌ Ошибка редактирования: {e}", flush=True)
        return False

# =====================================================================
# ОСНОВНОЙ ЦИКЛ
# =====================================================================
def main():
    global processed_games, game_numbers, player_cards_history, dealer_cards_history, messages, game_state_history
    
    print("🔄 ПАРСЕР БАККАРА ЗАПУЩЕН (ЛАЙВ-РЕЖИМ)", flush=True)
    print("🕐 Игры каждую минуту, старт в 03:00", flush=True)
    print("=" * 60, flush=True)
    
    cycle = 0
    while True:
        try:
            cycle += 1
            print(f"\n{'=' * 60}", flush=True)
            print(f"🔁 ЦИКЛ #{cycle} | {datetime.now(MOSCOW_TZ).strftime('%H:%M:%S')}", flush=True)
            print(f"{'=' * 60}", flush=True)
            
            active_games = get_active_games()
            
            if not active_games:
                print("💤 Нет активных игр, ждём 5 секунд...", flush=True)
                time.sleep(5)
                continue
            
            for game in active_games:
                game_id = str(game.get("id"))
                
                if game_id in processed_games:
                    continue
                
                # ===== БЕРЁМ КАРТЫ ПРЯМО ИЗ СПИСКА ИГР =====
                scores = game.get("scores", {})
                statistic = scores.get("statistic", {})
                main_stat = statistic.get("main", {})
                
                p_raw = main_stat.get("P", "[]")
                b_raw = main_stat.get("B", "[]")
                state = main_stat.get("S", "")
                
                player_cards = parse_cards(p_raw)
                dealer_cards = parse_cards(b_raw)
                
                print(f"🃏 {game_id}: P={len(player_cards)} карт, B={len(dealer_cards)} карт, state={state}", flush=True)
                
                if not player_cards and not dealer_cards:
                    print(f"⏭️ {game_id}: карт пока нет", flush=True)
                    continue
                
                if game_id not in game_numbers:
                    game_numbers[game_id] = get_game_number()
                game_number = game_numbers[game_id]
                
                p1_str = json.dumps(player_cards, sort_keys=True)
                p2_str = json.dumps(dealer_cards, sort_keys=True)
                
                cards_changed = (game_id not in player_cards_history or player_cards_history[game_id] != p1_str or
                                 game_id not in dealer_cards_history or dealer_cards_history[game_id] != p2_str)
                state_changed = (game_id not in game_state_history or game_state_history[game_id] != state)
                
                if not cards_changed and not state_changed:
                    continue
                
                player_cards_history[game_id] = p1_str
                dealer_cards_history[game_id] = p2_str
                game_state_history[game_id] = state
                
                p_score = calculate_score(player_cards)
                d_score = calculate_score(dealer_cards)
                
                msg = build_message(game_number, game_id, player_cards, dealer_cards, p_score, d_score, state)
                
                if game_id in messages:
                    edit_message(messages[game_id], msg)
                    print(f"🔄 Обновлена игра {game_id}: {msg}", flush=True)
                else:
                    msg_id = send_message(msg)
                    if msg_id:
                        messages[game_id] = msg_id
                        print(f"📤 Новая игра {game_id}: {msg}", flush=True)
                
                if is_game_finished(state, player_cards, dealer_cards, p_score, d_score):
                    processed_games.add(game_id)
                    print(f"🏁 Игра {game_id} завершена (state={state}, p_score={p_score}, d_score={d_score})", flush=True)
                
                time.sleep(0.3)
            
            if len(processed_games) > 500:
                processed_games.clear()
                game_numbers.clear()
                player_cards_history.clear()
                dealer_cards_history.clear()
                game_state_history.clear()
                messages.clear()
                print("🗑️ Кэш очищен", flush=True)
            
            time.sleep(2)
            
        except Exception as e:
            print(f"❌ Критическая ошибка: {e}", flush=True)
            import traceback
            traceback.print_exc()
            time.sleep(5)

if __name__ == "__main__":
    main()