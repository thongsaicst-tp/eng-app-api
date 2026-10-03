import pymysql
from urllib.parse import urlparse
import os
from datetime import datetime

def get_connection():
    import os
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise Exception("DATABASE_URL is missing. Format: mysql://user:pass@host:3306/dbname")
    
    if db_url.startswith("mysql+pymysql://"):
        db_url = db_url.replace("mysql+pymysql://", "mysql://")
        
    parsed = urlparse(db_url)
    return pymysql.connect(
        host=parsed.hostname,
        user=parsed.username,
        password=parsed.password,
        database=parsed.path[1:],
        port=parsed.port or 3306,
        autocommit=True
    )


def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    
    # ตารางเก็บข้อมูลผู้เล่น
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTO_INCREMENT,
            name VARCHAR(255) UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # ตารางเก็บคะแนนและการเล่น
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS progress (
            id INTEGER PRIMARY KEY AUTO_INCREMENT,
            user_id INTEGER NOT NULL,
            topic TEXT,
            score INTEGER,
            stars TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    
    # ตารางเก็บประวัติการเรียก API เพื่อหักโควต้า
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS api_logs (
            id INTEGER PRIMARY KEY AUTO_INCREMENT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # ตารางเก็บการตั้งค่าของระบบ (เช่น Quota)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            `key` VARCHAR(255) PRIMARY KEY,
            value TEXT
        )
    ''')
    cursor.execute("INSERT IGNORE INTO settings (`key`, value) VALUES ('daily_quota', '100')")
    # ตารางโปรไฟล์เสริม (เงินออม, สตรีค)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_profiles (
            user_id VARCHAR(255) PRIMARY KEY,
            wallet_balance INTEGER DEFAULT 0,
            current_streak INTEGER DEFAULT 0,
            last_played_date TEXT,
            gacha_claimed_date TEXT
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS wallet_history (
            id INTEGER PRIMARY KEY AUTO_INCREMENT,
            user_id TEXT NOT NULL,
            amount INTEGER NOT NULL,
            reason TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()
    print("Database initialized successfully.")

def get_setting(key: str, default_val: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE `key` = %s", (key,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else default_val

def update_setting(key: str, value: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("REPLACE INTO settings (`key`, value) VALUES (%s, %s)", (key, value))
    conn.commit()
    conn.close()

def log_api_call():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO api_logs DEFAULT VALUES")
    conn.commit()
    conn.close()

def get_daily_quota_usage():
    conn = get_connection()
    cursor = conn.cursor()
    # นับจำนวนครั้งที่ใช้งานภายในวันนี้
    cursor.execute("SELECT COUNT(*) FROM api_logs WHERE date(created_at, 'localtime') = date('now', 'localtime')")
    used = cursor.fetchone()[0]
    conn.close()
    return used

def get_or_create_user(name: str):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN is_deleted INTEGER DEFAULT 0")
        conn.commit()
    except pymysql.err.OperationalError:
        pass
    
    cursor.execute("SELECT id, name FROM users WHERE name = %s AND is_deleted = 0", (name,))
    user = cursor.fetchone()
    
    if not user:
        # Check if registration is locked
        cursor.execute("SELECT value FROM settings WHERE `key` = 'allow_registration'")
        reg_setting = cursor.fetchone()
        allow_reg = True
        if reg_setting and reg_setting[0] == 'false':
            allow_reg = False
            
        if not allow_reg:
            conn.close()
            return None  # Rejects creation

        cursor.execute("INSERT INTO users (name) VALUES (%s)", (name,))
        conn.commit()
        user_id = cursor.lastrowid
        user = (user_id, name)
    conn.close()
    return {"id": user[0], "name": user[1]}

def get_all_users():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM users ORDER BY id DESC")
    users = [{"id": row[0], "name": row[1]} for row in cursor.fetchall()]
    conn.close()
    return users

def save_progress(user_id: int, topic: str, score: int, stars: str):
    if user_id <= 0: return # ถ้าเป็น 0 คือเล่นแบบไม่ล็อกอิน (Guest)
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO progress (user_id, topic, score, stars)
        VALUES (%s, %s, %s, %s)
    ''', (user_id, topic, score, stars))
    conn.commit()
    conn.close()

def get_user_dashboard(user_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    
    # สรุปผล: จำนวนครั้งที่เล่น, คะแนนเฉลี่ย, ดาวรวมทั้งหมด
    cursor.execute('''
        SELECT 
            COUNT(*) as total_interactions,
            AVG(score) as avg_score,
            SUM(CASE WHEN stars LIKE '%⭐%' THEN length(stars) ELSE 0 END) as total_stars
        FROM progress
        WHERE user_id = %s
    ''', (user_id,))
    row = cursor.fetchone()
    conn.close()
    
    return {
        "total_interactions": row[0] or 0,
        "avg_score": round(row[1] or 0, 1) if row[1] else 0,
        "total_stars": row[2] or 0
    }

def get_learning_history(user_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT 
            date(created_at, 'localtime') as play_date, 
            strftime('%H:00', created_at, 'localtime') as play_hour, 
            COUNT(id) as interactions, 
            AVG(score) as avg_score,
            GROUP_CONCAT(DISTINCT topic) as topics
        FROM progress 
        WHERE user_id = %s 
        GROUP BY play_date, play_hour
        ORDER BY play_date DESC, play_hour DESC
        LIMIT 50
    ''', (user_id,))
    rows = cursor.fetchall()
    conn.close()
    
    history = []
    for r in rows:
        history.append({
            "date": r[0],
            "hour": r[1],
            "interactions": r[2],
            "avg_score": round(r[3], 1) if r[3] else 0,
            "topics": r[4]
        })
    return history

def reset_today_progress(user_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        DELETE FROM progress 
        WHERE user_id = %s AND date(created_at, 'localtime') = date('now', 'localtime')
    ''', (user_id,))
    conn.commit()
    conn.close()
    return True

def get_today_dashboard(user_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT 
            COUNT(id), 
            AVG(score), 
            SUM(CASE WHEN stars LIKE '%⭐%' THEN length(stars) ELSE 0 END),
            SUM(CASE WHEN topic LIKE 'Game_%' THEN 1 ELSE 0 END)
        FROM progress 
        WHERE user_id = %s AND date(created_at, 'localtime') = date('now', 'localtime')
    ''', (user_id,))
    row = cursor.fetchone()
    conn.close()
    return {
        "today_interactions": row[0] or 0,
        "today_avg_score": round(row[1] or 0, 1) if row[1] else 0,
        "today_stars": row[2] or 0,
        "played_game": (row[3] or 0) > 0
    }

# ─── User Profile & Wallet ───
def get_user_profile(user_id: int):
    from datetime import datetime, timedelta
    conn = get_connection()
    cursor = conn.cursor()
    
    # พยายามสร้างคอลัมน์ lost_streak ถ้ายังไม่มี
    try:
        cursor.execute("ALTER TABLE user_profiles ADD COLUMN lost_streak INTEGER DEFAULT 0")
        conn.commit()
    except pymysql.err.OperationalError:
        pass # มีคอลัมน์อยู่แล้ว

    cursor.execute("SELECT wallet_balance, current_streak, last_played_date, gacha_claimed_date, lost_streak FROM user_profiles WHERE user_id=%s", (str(user_id),))
    row = cursor.fetchone()
    
    today = datetime.now().strftime('%Y-%m-%d')
    yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    
    if not row:
        cursor.execute("INSERT INTO user_profiles (user_id) VALUES (%s)", (str(user_id),))
        conn.commit()
        conn.close()
        return {"wallet_balance": 0, "current_streak": 0, "last_played_date": None, "gacha_claimed_date": None, "lost_streak": 0}
    
    wallet_balance, current_streak, last_played_date, gacha_claimed_date, lost_streak = row
    lost_streak = lost_streak or 0

    # เช็คว่าไฟดับหรือยัง (ไม่ได้เล่นวันนี้ และ ไม่ได้เล่นเมื่อวาน)
    if last_played_date and last_played_date < yesterday and current_streak > 0:
        lost_streak = current_streak
        current_streak = 0
        cursor.execute("UPDATE user_profiles SET current_streak = 0, lost_streak = %s WHERE user_id=%s", (lost_streak, str(user_id)))
        conn.commit()

    conn.close()
    return {
        "wallet_balance": wallet_balance, 
        "current_streak": current_streak, 
        "last_played_date": last_played_date, 
        "gacha_claimed_date": gacha_claimed_date,
        "lost_streak": lost_streak
    }

def restore_user_streak(user_id: int, cost: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT wallet_balance, lost_streak FROM user_profiles WHERE user_id=%s", (str(user_id),))
    row = cursor.fetchone()
    if row and row[0] >= cost and row[1] > 0:
        cursor.execute("UPDATE user_profiles SET wallet_balance = wallet_balance - %s, current_streak = %s, lost_streak = 0 WHERE user_id=%s", (cost, row[1], str(user_id)))
        cursor.execute("INSERT INTO wallet_history (user_id, amount, reason) VALUES (%s, %s, %s)", (str(user_id), -cost, "จ่ายเงินฟื้นคืนชีพ Streak"))
        conn.commit()
        conn.close()
        return True
    conn.close()
    return False

def add_money(user_id: int, amount: int, reason: str = "ได้รับรางวัล"):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT IGNORE INTO user_profiles (user_id) VALUES (%s)", (str(user_id),))
    cursor.execute("UPDATE user_profiles SET wallet_balance = wallet_balance + %s WHERE user_id=%s", (amount, str(user_id)))
    cursor.execute("INSERT INTO wallet_history (user_id, amount, reason) VALUES (%s, %s, %s)", (str(user_id), amount, reason))
    conn.commit()
    conn.close()

def withdraw_money(user_id: int, amount: int, reason: str = "ถอนเงินสด (คุณพ่อจ่ายให้)"):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT wallet_balance FROM user_profiles WHERE user_id=%s", (str(user_id),))
    row = cursor.fetchone()
    if row and row[0] >= amount:
        cursor.execute("UPDATE user_profiles SET wallet_balance = wallet_balance - %s WHERE user_id=%s", (amount, str(user_id)))
        cursor.execute("INSERT INTO wallet_history (user_id, amount, reason) VALUES (%s, %s, %s)", (str(user_id), -amount, reason))
        conn.commit()
        conn.close()
        return True
    conn.close()
    return False

def get_wallet_history(user_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT amount, reason, created_at FROM wallet_history WHERE user_id=%s ORDER BY id DESC LIMIT 20", (str(user_id),))
    history = [{"amount": row[0], "reason": row[1], "date": row[2]} for row in cursor.fetchall()]
    conn.close()
    return history

def record_play_for_streak(user_id: int):
    from datetime import datetime, timedelta
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT IGNORE INTO user_profiles (user_id) VALUES (%s)", (str(user_id),))
    
    today = datetime.now().strftime('%Y-%m-%d')
    yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    
    cursor.execute("SELECT current_streak, last_played_date FROM user_profiles WHERE user_id=%s", (str(user_id),))
    row = cursor.fetchone()
    
    if row:
        streak, last_date = row[0], row[1]
        if last_date == yesterday:
            cursor.execute("UPDATE user_profiles SET current_streak = current_streak + 1, last_played_date = %s WHERE user_id=%s", (today, str(user_id)))
        elif last_date != today:
            cursor.execute("UPDATE user_profiles SET current_streak = 1, last_played_date = %s WHERE user_id=%s", (today, str(user_id)))
    else:
        cursor.execute("UPDATE user_profiles SET current_streak = 1, last_played_date = %s WHERE user_id=%s", (today, str(user_id)))

    conn.commit()
    conn.close()

def claim_daily_gacha(user_id: int, reward_amount: int):
    from datetime import datetime

def get_connection():
    import os
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise Exception("DATABASE_URL is missing. Format: mysql://user:pass@host:3306/dbname")
    
    if db_url.startswith("mysql+pymysql://"):
        db_url = db_url.replace("mysql+pymysql://", "mysql://")
        
    parsed = urlparse(db_url)
    return pymysql.connect(
        host=parsed.hostname,
        user=parsed.username,
        password=parsed.password,
        database=parsed.path[1:],
        port=parsed.port or 3306,
        autocommit=True
    )
    conn = get_connection()
    cursor = conn.cursor()
    today = datetime.now().strftime('%Y-%m-%d')
    cursor.execute("UPDATE user_profiles SET wallet_balance = wallet_balance + %s, gacha_claimed_date = %s WHERE user_id=%s", (reward_amount, today, str(user_id)))
    cursor.execute("INSERT INTO wallet_history (user_id, amount, reason) VALUES (%s, %s, %s)", (str(user_id), reward_amount, "สุ่มกาชาประจำวัน"))
    conn.commit()
    conn.close()

def get_admin_dashboard_data():
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN is_deleted INTEGER DEFAULT 0")
        conn.commit()
    except pymysql.err.OperationalError:
        pass # already exists

    cursor.execute('''
        SELECT 
            u.id, 
            u.name, 
            COALESCE(p.wallet_balance, 0) as wallet_balance, 
            COALESCE(p.current_streak, 0) as current_streak,
            (SELECT COUNT(*) FROM progress WHERE user_id = u.id) as total_interactions,
            (SELECT AVG(score) FROM progress WHERE user_id = u.id) as avg_score,
            u.is_deleted
        FROM users u
        LEFT JOIN user_profiles p ON u.id = p.user_id
        ORDER BY u.id DESC
    ''')
    users = []
    for row in cursor.fetchall():
        users.append({
            "id": row[0],
            "name": row[1],
            "wallet_balance": row[2],
            "current_streak": row[3],
            "total_interactions": row[4] or 0,
            "avg_score": round(row[5] or 0, 1),
            "is_deleted": bool(row[6])
        })
    conn.close()
    return users

def delete_user(user_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN is_deleted INTEGER DEFAULT 0")
        conn.commit()
    except pymysql.err.OperationalError:
        pass
    cursor.execute("UPDATE users SET is_deleted = 1 WHERE id=%s", (user_id,))
    conn.commit()
    conn.close()

def restore_user(user_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_deleted = 0 WHERE id=%s", (user_id,))
    conn.commit()
    conn.close()

# ─── Invite Token System ───
def _init_invite_table():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS invite_tokens (
            id INTEGER PRIMARY KEY AUTO_INCREMENT,
            code VARCHAR(255) UNIQUE,
            is_used INTEGER DEFAULT 0,
            used_by TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def generate_invite_code():
    _init_invite_table()
    import random
    import string
    # e.g., VIP-A7K9
    code = "VIP-" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO invite_tokens (code) VALUES (%s)", (code,))
    conn.commit()
    conn.close()
    return code

def get_all_invite_codes():
    _init_invite_table()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT code, is_used, used_by, created_at FROM invite_tokens ORDER BY id DESC")
    results = [{"code": r[0], "is_used": bool(r[1]), "used_by": r[2], "created_at": r[3]} for r in cursor.fetchall()]
    conn.close()
    return results

def validate_and_use_invite_code(code: str, username: str):
    _init_invite_table()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT is_used FROM invite_tokens WHERE code = %s", (code,))
    row = cursor.fetchone()
    
    if not row:
        conn.close()
        return False # Code doesn't exist
    if row[0] == 1:
        conn.close()
        return False # Code already used
        
    # Valid! Mark as used
    cursor.execute("UPDATE invite_tokens SET is_used = 1, used_by = %s WHERE code = %s", (username, code))
    conn.commit()
    conn.close()
    return True

# ─── Vocabulary Arsenal ───
def _init_vocab_table():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_vocabulary (
            id INTEGER PRIMARY KEY AUTO_INCREMENT,
            user_id INTEGER,
            word VARCHAR(255),
            part_of_speech TEXT,
            meaning TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, word)
        )
    ''')
    conn.commit()
    conn.close()

def add_vocabulary(user_id: int, word: str, pos: str, meaning: str):
    _init_vocab_table()
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO user_vocabulary (user_id, word, part_of_speech, meaning) VALUES (%s, %s, %s, %s)", 
                       (user_id, word, pos, meaning))
        conn.commit()
        success = True
    except pymysql.err.IntegrityError:
        success = False # Already has this word
    conn.close()
    return success

def get_user_vocabulary(user_id: int):
    _init_vocab_table()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT word, part_of_speech, meaning, created_at FROM user_vocabulary WHERE user_id = %s ORDER BY id DESC", (user_id,))
    vocab = [{"word": r[0], "part_of_speech": r[1], "meaning": r[2], "created_at": r[3]} for r in cursor.fetchall()]
    conn.close()
    return vocab
