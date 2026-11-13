from __future__ import annotations

import json
import os
import sqlite3
from datetime import date, datetime
from html import escape
from pathlib import Path

import streamlit as st
from openai import OpenAI

# ------------------------------------------------------------
# 가족 건강기록 & 우리집 꾸미기
# 실행: streamlit run app.py
# 기본 저장소: 실행 폴더의 family_wellness.db (SQLite)
# ------------------------------------------------------------

st.set_page_config(page_title="우리집 건강기록", page_icon="🏡", layout="wide")
DB_PATH = os.getenv("APP_DB_PATH", str(Path(__file__).with_name("family_wellness.db")))

DECOR_ITEMS = {
    "flowerbed": {"name": "알록달록 꽃밭", "price": 40, "emoji": "🌷", "desc": "집 앞 정원에 꽃을 심어요."},
    "balcony": {"name": "포근한 발코니", "price": 60, "emoji": "🪴", "desc": "발코니를 초록 식물로 꾸며요."},
    "tree": {"name": "그늘 나무", "price": 70, "emoji": "🌳", "desc": "마당에 작은 나무를 놓아요."},
    "car": {"name": "분홍 자동차", "price": 90, "emoji": "🚗", "desc": "우리집 앞에 귀여운 차를 세워요."},
    "lamp": {"name": "정원 가로등", "price": 50, "emoji": "🏮", "desc": "저녁에도 따뜻하게 밝혀줘요."},
}
COUPON_PRICE = 120


def get_ai_api_key():
    """환경 변수 또는 Streamlit secrets에서 AI API 키를 읽습니다."""
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if key:
        return key
    try:
        return str(st.secrets.get("OPENAI_API_KEY", "")).strip()
    except Exception:
        return ""


def estimate_food_calories(food_name):
    """메뉴명 기준 1인분 열량을 AI로 추정합니다. 결과는 참고용입니다."""
    api_key = get_ai_api_key()
    if not api_key:
        raise RuntimeError("AI 연결 키가 설정되지 않았어요. Streamlit secrets 또는 OPENAI_API_KEY 환경 변수에 키를 설정해 주세요.")
    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0.2,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "당신은 음식의 영양정보를 대략 추정하는 도우미입니다. "
                    "메뉴명만 주어지면 한국에서 일반적으로 먹는 1인분을 가정해 총 열량을 추정하세요. "
                    "정확한 영양 분석이 아니라는 점을 전제로, 과장 없이 합리적인 대표값을 제시하세요. "
                    "응답은 JSON 객체 하나로만 작성하세요. 키는 calories(정수 kcal), basis(짧은 한국어 설명)입니다."
                ),
            },
            {"role": "user", "content": f"음식 메뉴: {food_name.strip()}"},
        ],
    )
    data = json.loads(response.choices[0].message.content or "{}")
    calories = int(data.get("calories", 0))
    if calories < 0 or calories > 10000:
        raise ValueError("AI가 반환한 칼로리 값이 올바른 범위를 벗어났어요.")
    return calories, str(data.get("basis", "일반적인 1인분 기준 추정"))


def db_connect():
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with db_connect() as con:
        con.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                points INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS meals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                eaten_on TEXT NOT NULL,
                meal_type TEXT NOT NULL,
                food_name TEXT NOT NULL,
                calories INTEGER NOT NULL,
                note TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS exercises (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                done_on TEXT NOT NULL,
                exercise_name TEXT NOT NULL,
                duration_min INTEGER NOT NULL,
                note TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS body_stats (
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                measured_on TEXT NOT NULL,
                height_cm REAL NOT NULL,
                weight_kg REAL NOT NULL,
                activity_min INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(user_id, measured_on)
            );
            CREATE TABLE IF NOT EXISTS daily_bonus (
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                bonus_on TEXT NOT NULL,
                points INTEGER NOT NULL DEFAULT 10,
                PRIMARY KEY(user_id, bonus_on)
            );
            CREATE TABLE IF NOT EXISTS inventory (
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                item_key TEXT NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(user_id, item_key)
            );
            CREATE TABLE IF NOT EXISTS coupon_uses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                used_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                description TEXT NOT NULL DEFAULT '설거지 면제 쿠폰 사용'
            );
        """)


def get_users():
    with db_connect() as con:
        return con.execute("SELECT id, name, points FROM users ORDER BY name COLLATE NOCASE").fetchall()


def add_user(name):
    name = name.strip()
    if not name:
        return False, "이름을 입력해 주세요."
    try:
        with db_connect() as con:
            con.execute("INSERT INTO users(name) VALUES (?)", (name,))
        return True, f"{name} 프로필을 만들었어요."
    except sqlite3.IntegrityError:
        return False, "이미 등록된 이름이에요. 다른 이름을 입력해 주세요."


def get_user(user_id):
    with db_connect() as con:
        return con.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()


def get_inventory(user_id):
    with db_connect() as con:
        rows = con.execute("SELECT item_key, quantity FROM inventory WHERE user_id=?", (user_id,)).fetchall()
    return {r["item_key"]: r["quantity"] for r in rows}


def record_meal(user_id, day, meal_type, food, calories, note):
    with db_connect() as con:
        con.execute("INSERT INTO meals(user_id,eaten_on,meal_type,food_name,calories,note) VALUES(?,?,?,?,?,?)",
                    (user_id, str(day), meal_type, food.strip(), int(calories), note.strip()))


def record_exercise(user_id, day, name, duration, note):
    with db_connect() as con:
        con.execute("INSERT INTO exercises(user_id,done_on,exercise_name,duration_min,note) VALUES(?,?,?,?,?)",
                    (user_id, str(day), name.strip(), int(duration), note.strip()))


def try_daily_bonus(user_id, day):
    """기록 습관 보너스: 서로 다른 식사 유형 2개 이상 기록 + 운동 20분 이상."""
    with db_connect() as con:
        meals = con.execute("SELECT COUNT(DISTINCT meal_type) FROM meals WHERE user_id=? AND eaten_on=?", (user_id, str(day))).fetchone()[0]
        minutes = con.execute("SELECT COALESCE(SUM(duration_min),0) FROM exercises WHERE user_id=? AND done_on=?", (user_id, str(day))).fetchone()[0]
        if meals < 2 or minutes < 20:
            return False
        cur = con.execute("INSERT OR IGNORE INTO daily_bonus(user_id,bonus_on,points) VALUES(?,?,10)", (user_id, str(day)))
        if cur.rowcount:
            con.execute("UPDATE users SET points=points+10 WHERE id=?", (user_id,))
            return True
    return False


def save_body_stats(user_id, day, height, weight, activity):
    with db_connect() as con:
        con.execute("""INSERT INTO body_stats(user_id,measured_on,height_cm,weight_kg,activity_min)
            VALUES(?,?,?,?,?) ON CONFLICT(user_id,measured_on) DO UPDATE SET
            height_cm=excluded.height_cm, weight_kg=excluded.weight_kg, activity_min=excluded.activity_min""",
            (user_id, str(day), float(height), float(weight), int(activity)))


def purchase(user_id, item_key, price, is_coupon=False):
    with db_connect() as con:
        user = con.execute("SELECT points FROM users WHERE id=?", (user_id,)).fetchone()
        if not user or user["points"] < price:
            return False, "포인트가 부족해요. 기록 보너스를 모아 다시 와 주세요."
        con.execute("UPDATE users SET points=points-? WHERE id=?", (price, user_id))
        con.execute("INSERT INTO inventory(user_id,item_key,quantity) VALUES(?,?,1) ON CONFLICT(user_id,item_key) DO UPDATE SET quantity=quantity+1", (user_id, item_key))
        return True, "쿠폰을 구매했어요." if is_coupon else "우리집 꾸미기 아이템을 구매했어요!"


def use_coupon(user_id):
    with db_connect() as con:
        row = con.execute("SELECT quantity FROM inventory WHERE user_id=? AND item_key='dish_coupon'", (user_id,)).fetchone()
        if not row or row["quantity"] < 1:
            return False
        con.execute("UPDATE inventory SET quantity=quantity-1 WHERE user_id=? AND item_key='dish_coupon'", (user_id,))
        con.execute("INSERT INTO coupon_uses(user_id) VALUES(?)", (user_id,))
        return True


def day_summary(user_id, day):
    with db_connect() as con:
        meals = con.execute("SELECT * FROM meals WHERE user_id=? AND eaten_on=? ORDER BY created_at DESC,id DESC", (user_id, str(day))).fetchall()
        exercises = con.execute("SELECT * FROM exercises WHERE user_id=? AND done_on=? ORDER BY created_at DESC,id DESC", (user_id, str(day))).fetchall()
        stats = con.execute("SELECT * FROM body_stats WHERE user_id=? AND measured_on=?", (user_id, str(day))).fetchone()
        bonus = con.execute("SELECT points FROM daily_bonus WHERE user_id=? AND bonus_on=?", (user_id, str(day))).fetchone()
    return meals, exercises, stats, bonus


def delete_record(table, record_id, user_id):
    allowed = {"meals": "user_id", "exercises": "user_id"}
    if table not in allowed:
        return
    with db_connect() as con:
        con.execute(f"DELETE FROM {table} WHERE id=? AND user_id=?", (record_id, user_id))


def history(user_id):
    with db_connect() as con:
        meals = con.execute("SELECT eaten_on, COUNT(*) AS n, SUM(calories) AS kcal FROM meals WHERE user_id=? GROUP BY eaten_on ORDER BY eaten_on DESC LIMIT 14", (user_id,)).fetchall()
        exercises = con.execute("SELECT done_on, SUM(duration_min) AS mins FROM exercises WHERE user_id=? GROUP BY done_on ORDER BY done_on DESC LIMIT 14", (user_id,)).fetchall()
        stats = con.execute("SELECT * FROM body_stats WHERE user_id=? ORDER BY measured_on DESC LIMIT 14", (user_id,)).fetchall()
        coupons = con.execute("SELECT used_at,description FROM coupon_uses WHERE user_id=? ORDER BY id DESC LIMIT 10", (user_id,)).fetchall()
    return meals, exercises, stats, coupons


def render_house(inventory):
    flower = inventory.get("flowerbed", 0) > 0
    balcony = inventory.get("balcony", 0) > 0
    tree = inventory.get("tree", 0) > 0
    car = inventory.get("car", 0) > 0
    lamp = inventory.get("lamp", 0) > 0
    flower_markup = '<circle cx="122" cy="314" r="6" fill="#ed6b9b"/><circle cx="143" cy="319" r="5" fill="#f5c653"/><circle cx="161" cy="311" r="6" fill="#c174d2"/><circle cx="178" cy="318" r="5" fill="#ee7b91"/>' if flower else ''
    balcony_markup = '<rect x="365" y="193" width="83" height="8" rx="3" fill="#476d58"/><path d="M371 195v15m16-15v15m16-15v15m16-15v15m16-15v15" stroke="#476d58" stroke-width="3"/><circle cx="386" cy="188" r="6" fill="#65a96b"/><circle cx="427" cy="188" r="7" fill="#78b66b"/>' if balcony else ''
    tree_markup = '<rect x="87" y="255" width="10" height="54" fill="#8b5c38"/><circle cx="92" cy="244" r="30" fill="#659a66"/><circle cx="74" cy="256" r="20" fill="#77ad6f"/><circle cx="110" cy="257" r="19" fill="#5e9362"/>' if tree else ''
    car_markup = '<rect x="470" y="301" width="100" height="34" rx="12" fill="#d94d72"/><path d="M487 302l13-18h39l16 18z" fill="#e36f87"/><rect x="501" y="288" width="16" height="12" rx="2" fill="#bce3e4"/><rect x="521" y="288" width="15" height="12" rx="2" fill="#bce3e4"/><circle cx="492" cy="336" r="9" fill="#333842"/><circle cx="549" cy="336" r="9" fill="#333842"/>' if car else ''
    lamp_markup = '<path d="M210 270v56m-8-56h16l-4-15h-8z" stroke="#47505b" stroke-width="4" fill="#f5d785"/><circle cx="210" cy="264" r="11" fill="#fff2be" opacity=".62"/>' if lamp else ''
    svg = f'''<svg viewBox="0 0 700 390" role="img" aria-label="바닷가 우리집 일러스트" xmlns="http://www.w3.org/2000/svg">
    <defs><linearGradient id="sky" x1="0" y1="0" x2="0" y2="1"><stop stop-color="#c7b4ed"/><stop offset="1" stop-color="#f4d8c4"/></linearGradient><linearGradient id="sea" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#7bcbd0"/><stop offset="1" stop-color="#4faeb8"/></linearGradient></defs>
    <rect width="700" height="390" rx="20" fill="url(#sky)"/><circle cx="587" cy="62" r="28" fill="#fff1b6" opacity=".85"/><path d="M0 230h700v160H0z" fill="#e8d2a9"/><path d="M0 255q150-20 275 8t425-8v135H0z" fill="#7bcbd0"/><path d="M0 280q80-12 160 0t160 0t160 0t220 0" fill="none" stroke="#d4f4e8" stroke-width="4" opacity=".8"/><path d="M0 322q90-9 180 1t180 0t180 0t160 0" fill="none" stroke="#d4f4e8" stroke-width="3" opacity=".7"/>
    {tree_markup}<ellipse cx="349" cy="328" rx="190" ry="22" fill="#887567" opacity=".18"/>
    <path d="M230 190l74-66 82 66v137H230z" fill="#d98b69"/><path d="M214 194l89-81 97 81-12 12-85-69-79 68z" fill="#9d4e3d"/><path d="M362 200l59-54 65 54v126H362z" fill="#dfaa79"/><path d="M350 203l70-68 76 68-12 11-64-53-57 53z" fill="#9a513f"/>
    <rect x="266" y="216" width="31" height="37" rx="3" fill="#a9ded8" stroke="#f6ead1" stroke-width="5"/><path d="M281 217v36m-14-18h30" stroke="#f7f0dc" stroke-width="3"/><rect x="323" y="216" width="31" height="37" rx="3" fill="#a9ded8" stroke="#f6ead1" stroke-width="5"/><path d="M338 217v36m-14-18h30" stroke="#f7f0dc" stroke-width="3"/><rect x="391" y="216" width="28" height="35" rx="3" fill="#a9ded8" stroke="#f6ead1" stroke-width="5"/><path d="M405 217v34m-13-17h27" stroke="#f7f0dc" stroke-width="3"/><rect x="441" y="216" width="27" height="35" rx="3" fill="#a9ded8" stroke="#f6ead1" stroke-width="5"/><path d="M454 217v34m-12-17h26" stroke="#f7f0dc" stroke-width="3"/>
    <rect x="310" y="268" width="38" height="59" rx="5" fill="#f5dfbc"/><circle cx="339" cy="297" r="2.5" fill="#86664e"/><rect x="371" y="268" width="27" height="58" rx="4" fill="#f5dfbc"/><path d="M362 206h87" stroke="#735344" stroke-width="7"/><path d="M370 207v20m18-20v20m18-20v20m18-20v20m18-20v20" stroke="#735344" stroke-width="3"/>{balcony_markup}
    <rect x="241" y="318" width="50" height="10" rx="5" fill="#b7755a"/><path d="M250 318q15-32 31 0" fill="#63a66d"/>
    {flower_markup}{lamp_markup}{car_markup}
    <path d="M30 352h640" stroke="#c6a982" stroke-width="2" opacity=".6"/><text x="350" y="374" text-anchor="middle" fill="#5c6b65" font-family="sans-serif" font-size="14">우리 가족의 작은 바닷가 집</text>
    </svg>'''
    return svg


init_db()
st.markdown("""
<style>
  .stApp {background:#f7f6f2; color:#29353a}
  [data-testid="stSidebar"] {background:#f0eee8}
  .block-container {padding-top:1.7rem; max-width:1120px}
  .app-title {font-size:2rem;font-weight:750;letter-spacing:-.04em;margin-bottom:.1rem;color:#26383a}
  .app-subtitle {color:#718080;margin-bottom:1.2rem}
  .soft-card {background:#fff;border:1px solid #e9e7e1;border-radius:14px;padding:16px 18px;margin-bottom:10px}
  .small-note {font-size:.88rem;color:#697879}
  div[data-testid="stMetric"] {background:white;border:1px solid #e9e7e1;padding:12px 14px;border-radius:12px}
  .house-frame {background:#fff;border:1px solid #e8e5df;border-radius:18px;padding:10px;overflow:hidden}
  .house-frame svg {display:block;width:100%;height:auto}
  h1,h2,h3 {letter-spacing:-.025em}
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="app-title">우리집 건강기록</div><div class="app-subtitle">가족의 식사와 운동을 기록하고, 포인트로 우리집을 꾸며 보세요.</div>', unsafe_allow_html=True)

# 프로필 선택/추가
with st.sidebar:
    st.subheader("가족 프로필")
    all_users = get_users()
    with st.form("new_user_form", clear_on_submit=True):
        new_name = st.text_input("새 가족 이름", placeholder="예: 민지")
        create_clicked = st.form_submit_button("프로필 추가", use_container_width=True)
    if create_clicked:
        ok, message = add_user(new_name)
        (st.success if ok else st.warning)(message)
        all_users = get_users()
    if not all_users:
        st.info("먼저 가족 프로필을 추가해 주세요.")
        st.stop()
    labels = {u["id"]: f"{u['name']} · {u['points']}P" for u in all_users}
    ids = [u["id"] for u in all_users]
    selected = st.selectbox("사용자", ids, format_func=lambda uid: labels[uid], key="active_user")
    st.caption("기록은 이 기기/앱의 SQLite 데이터베이스에 저장됩니다.")

user = get_user(selected)
if user is None:
    st.error("프로필을 불러오지 못했어요. 페이지를 새로고침해 주세요.")
    st.stop()

home_tab, log_tab, shop_tab, history_tab = st.tabs(["🏡 우리집", "📝 오늘 기록", "🎁 꾸미기·쿠폰", "📅 기록 보기"])

with home_tab:
    left, right = st.columns([1.45, 1], gap="large")
    inv = get_inventory(selected)
    with left:
        st.markdown('<div class="house-frame">' + render_house(inv) + '</div>', unsafe_allow_html=True)
        owned = [f"{DECOR_ITEMS[k]['emoji']} {DECOR_ITEMS[k]['name']}" for k, n in inv.items() if k in DECOR_ITEMS and n > 0]
        st.caption("보유 아이템: " + (" · ".join(owned) if owned else "아직 없어요. 꾸미기에서 첫 아이템을 골라 보세요."))
    with right:
        st.subheader(f"안녕하세요, {escape(user['name'])}님")
        st.metric("모은 포인트", f"{user['points']} P")
        chosen_day = st.date_input("확인할 날짜", value=date.today(), key="home_date")
        meals, exercises, stats, bonus = day_summary(selected, chosen_day)
        kcal = sum(m["calories"] for m in meals)
        mins = sum(e["duration_min"] for e in exercises)
        m1, m2 = st.columns(2)
        m1.metric("기록한 음식 열량", f"{kcal:,} kcal")
        m2.metric("운동 시간", f"{mins // 60}시간 {mins % 60}분")
        if bonus:
            st.success("오늘의 기록 습관 보너스 +10P를 받았어요! ✨")
        else:
            types = {m["meal_type"] for m in meals}
            missing = []
            if len(types) < 2: missing.append("서로 다른 식사 2가지 기록")
            if mins < 20: missing.append(f"운동 {20-mins}분 더 기록")
            st.info("기록 보너스 조건: 음식 종류가 아닌 **식사 유형 2가지**와 운동 20분을 기록하면 +10P예요. " + (" · ".join(missing) if missing else "조건을 채웠어요. 기록을 추가하면 보너스가 반영됩니다."))
        st.markdown('<div class="small-note">칼로리와 BMI는 참고용 기록이며, 건강 상태를 진단하거나 식습관을 판정하지 않습니다. 성장기·질환·임신 등 특별한 상황은 전문가의 안내를 따르세요.</div>', unsafe_allow_html=True)
        if stats:
            bmi = stats["weight_kg"] / ((stats["height_cm"] / 100) ** 2)
            st.write(f"**최근 신체 기록 ({chosen_day})** · 키 {stats['height_cm']:g}cm · 몸무게 {stats['weight_kg']:g}kg · BMI 참고값 {bmi:.1f}")
        else:
            st.caption("오늘 키·몸무게를 입력하면 신체 기록을 볼 수 있어요.")

with log_tab:
    st.subheader("오늘의 기록")
    log_day = st.date_input("기록 날짜", value=date.today(), key="log_date")
    food_col, exercise_col = st.columns(2, gap="large")
    with food_col:
        st.markdown("#### 🍽️ 먹은 음식")
        st.caption("메뉴를 입력하고 AI 칼로리 추정 버튼을 누르세요. 일반적인 1인분 기준이며 양에 따라 달라질 수 있어요.")
        meal_version = st.session_state.get("meal_form_version", 0)
        food_key = f"meal_food_input_{meal_version}"
        note_key = f"meal_note_input_{meal_version}"
        calorie_key = f"meal_calories_input_{meal_version}"
        meal_type = st.selectbox("식사 유형", ["아침", "점심", "저녁", "간식"], key="meal_type_input")
        food = st.text_input("음식 메뉴", placeholder="예: 김치볶음밥, 된장찌개와 밥", key=food_key)
        if st.button("✨ AI로 칼로리 추정", key="estimate_food_button", use_container_width=True):
            if not food.strip():
                st.warning("먼저 음식 메뉴를 입력해 주세요.")
            else:
                try:
                    with st.spinner("메뉴의 일반적인 1인분 열량을 추정하고 있어요..."):
                        estimated, basis = estimate_food_calories(food)
                    st.session_state["meal_estimated_calories"] = estimated
                    st.session_state[calorie_key] = estimated
                    st.session_state["meal_estimated_for"] = food.strip()
                    st.session_state["meal_estimate_basis"] = basis
                    st.success(f"AI 추정: 약 {estimated:,} kcal · {basis}")
                except Exception as exc:
                    st.error(f"칼로리 추정에 실패했어요: {exc}")
        default_kcal = st.session_state.get("meal_estimated_calories", 300)
        calories = st.number_input("열량 (kcal) — 추정값 수정 가능", min_value=0, max_value=10000, value=int(default_kcal), step=10, key=calorie_key)
        food_note = st.text_input("메모 (선택)", placeholder="양이나 함께 먹은 음식 등", key=note_key)
        if st.button("음식 기록 저장", key="save_meal_button", use_container_width=True):
            if not food.strip():
                st.warning("음식 메뉴를 입력해 주세요.")
            else:
                record_meal(selected, log_day, meal_type, food, calories, food_note)
                got_bonus = try_daily_bonus(selected, log_day)
                st.session_state["meal_form_version"] = meal_version + 1
                st.session_state["meal_estimated_calories"] = 300
                st.session_state.pop("meal_estimated_for", None)
                st.session_state.pop("meal_estimate_basis", None)
                st.success("음식 기록을 저장했어요." + (" 기록 보너스 +10P도 받았어요!" if got_bonus else ""))
                st.rerun()
    with exercise_col:
        st.markdown("#### 🏃 운동")
        with st.form("exercise_form", clear_on_submit=True):
            exercise_name = st.selectbox("운동 종목", ["걷기", "달리기", "자전거", "수영", "근력 운동", "요가·스트레칭", "춤", "기타"])
            duration_hours = st.number_input("시간", min_value=0, max_value=24, value=0, step=1)
            duration_minutes = st.number_input("분", min_value=0, max_value=59, value=30, step=5)
            exercise_note = st.text_input("메모 (선택)", placeholder="강도나 함께한 사람 등")
            exercise_submit = st.form_submit_button("운동 기록 저장", use_container_width=True)
        if exercise_submit:
            total = int(duration_hours) * 60 + int(duration_minutes)
            if total <= 0:
                st.warning("운동 시간을 1분 이상 입력해 주세요.")
            else:
                record_exercise(selected, log_day, exercise_name, total, exercise_note)
                got_bonus = try_daily_bonus(selected, log_day)
                st.success("운동 기록을 저장했어요." + (" 기록 보너스 +10P도 받았어요!" if got_bonus else ""))
                st.rerun()

    st.divider()
    st.markdown("#### 📏 키·몸무게·하루 활동량")
    with st.form("body_form"):
        existing = day_summary(selected, log_day)[2]
        a, b, c = st.columns(3)
        height_value = a.number_input("키 (cm)", min_value=50.0, max_value=250.0, value=float(existing["height_cm"]) if existing else 160.0, step=0.5)
        weight_value = b.number_input("몸무게 (kg)", min_value=10.0, max_value=400.0, value=float(existing["weight_kg"]) if existing else 55.0, step=0.1)
        activity_value = c.number_input("하루 활동량 (분)", min_value=0, max_value=1440, value=int(existing["activity_min"]) if existing else 0, step=10, help="걷기 등 일상 활동을 입력하세요. 위 운동 기록 시간과 별도로 저장됩니다.")
        stats_submit = st.form_submit_button("신체 기록 저장", use_container_width=True)
    if stats_submit:
        save_body_stats(selected, log_day, height_value, weight_value, activity_value)
        st.success("신체 기록을 저장했어요.")
        st.rerun()

    meals, exercises, _, _ = day_summary(selected, log_day)
    if meals or exercises:
        st.divider()
        st.markdown("#### 저장된 기록")
        for m in meals:
            cols = st.columns([4, 1])
            cols[0].write(f"🍽️ **{m['meal_type']} · {escape(m['food_name'])}** — {m['calories']:,} kcal" + (f" · {escape(m['note'])}" if m["note"] else ""))
            if cols[1].button("삭제", key=f"del_meal_{m['id']}"):
                delete_record("meals", m["id"], selected)
                st.rerun()
        for e in exercises:
            cols = st.columns([4, 1])
            cols[0].write(f"🏃 **{escape(e['exercise_name'])}** — {e['duration_min']//60}시간 {e['duration_min']%60}분" + (f" · {escape(e['note'])}" if e["note"] else ""))
            if cols[1].button("삭제", key=f"del_ex_{e['id']}"):
                delete_record("exercises", e["id"], selected)
                st.rerun()

with shop_tab:
    st.subheader("포인트로 우리집 꾸미기")
    st.write(f"현재 **{user['points']}P**가 있어요. 꾸미기 아이템은 여러 개 모을 수 있습니다.")
    cols = st.columns(3)
    for i, (key, item) in enumerate(DECOR_ITEMS.items()):
        with cols[i % 3]:
            st.markdown(f"<div class='soft-card'><div style='font-size:1.7rem'>{item['emoji']}</div><b>{item['name']}</b><br><span class='small-note'>{item['desc']}</span><br><br><b>{item['price']}P</b></div>", unsafe_allow_html=True)
            count = inv.get(key, 0)
            if count:
                st.caption(f"보유 {count}개")
            if st.button(f"{item['price']}P로 구매", key=f"buy_{key}", use_container_width=True):
                ok, msg = purchase(selected, key, item["price"])
                (st.success if ok else st.warning)(msg)
                if ok: st.rerun()
    st.divider()
    st.markdown("#### 🍽️ 설거지 면제 쿠폰")
    st.write(f"쿠폰 1장: **{COUPON_PRICE}P** · 가족끼리 사용할 날짜를 정한 뒤, 실제로 설거지 역할을 바꿔 주세요.")
    coupon_count = inv.get("dish_coupon", 0)
    st.info(f"보유 쿠폰: {coupon_count}장")
    ca, cb = st.columns(2)
    if ca.button(f"쿠폰 구매 · {COUPON_PRICE}P", key="buy_coupon", use_container_width=True):
        ok, msg = purchase(selected, "dish_coupon", COUPON_PRICE, is_coupon=True)
        (st.success if ok else st.warning)(msg)
        if ok: st.rerun()
    if cb.button("쿠폰 1장 사용 기록", key="use_coupon", disabled=coupon_count < 1, use_container_width=True):
        if use_coupon(selected):
            st.success("쿠폰 사용을 기록했어요. 가족끼리 약속한 설거지 면제를 적용해 주세요!")
            st.rerun()
    st.caption("꾸미기와 쿠폰 가격은 가족이 자유롭게 조정할 수 있는 예시 값입니다.")

with history_tab:
    st.subheader("기록 보기")
    meal_rows, exercise_rows, stats_rows, coupon_rows = history(selected)
    if meal_rows:
        st.markdown("#### 음식 기록 요약 (최근 14일)")
        st.dataframe([{"날짜": r["eaten_on"], "기록한 음식 수": r["n"], "기록 열량 합계 (kcal)": r["kcal"] or 0} for r in meal_rows], hide_index=True, use_container_width=True)
    else:
        st.caption("아직 음식 기록이 없어요.")
    if exercise_rows:
        st.markdown("#### 운동 시간 (최근 기록일 14일)")
        st.dataframe([{"날짜": r["done_on"], "운동 시간 (분)": r["mins"] or 0} for r in exercise_rows], hide_index=True, use_container_width=True)
    if stats_rows:
        st.markdown("#### 신체 기록 (최근 14회)")
        st.dataframe([{"날짜": r["measured_on"], "키 (cm)": r["height_cm"], "몸무게 (kg)": r["weight_kg"], "일상 활동량 (분)": r["activity_min"]} for r in stats_rows], hide_index=True, use_container_width=True)
    if coupon_rows:
        st.markdown("#### 쿠폰 사용 기록")
        st.dataframe([{"사용 시각": r["used_at"], "내용": r["description"]} for r in coupon_rows], hide_index=True, use_container_width=True)

st.divider()
st.caption("가족끼리 편하게 기록하는 생활 습관 앱입니다. 칼로리는 입력한 값의 합계일 뿐, 음식의 정확한 영양 분석이나 의료 조언을 대신하지 않아요.")
