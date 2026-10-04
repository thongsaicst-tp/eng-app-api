import pymysql
from urllib.parse import urlparse
import os
from datetime import datetime

def get_connection():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise Exception("DATABASE_URL is missing.")
    
    parsed = urlparse(db_url)
    conn = pymysql.connect(
        host=parsed.hostname,
        user=parsed.username,
        password=parsed.password,
        database=parsed.path[1:],
        port=parsed.port or 3306,
        autocommit=True
    )
    return conn

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTO_INCREMENT,
            name VARCHAR(255) NOT NULL,
            pin VARCHAR(10) DEFAULT '9999',
            is_deleted INTEGER DEFAULT 0
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS progress (
            id INTEGER PRIMARY KEY AUTO_INCREMENT,
            user_id INTEGER,
            topic VARCHAR(255),
            score INTEGER,
            stars INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_profiles (
            user_id INTEGER PRIMARY KEY,
            wallet_balance INTEGER DEFAULT 0,
            current_streak INTEGER DEFAULT 0,
            last_played_date DATE,
            gacha_claimed_date DATE,
            lost_streak INTEGER DEFAULT 0
        )
    """)
    try:
        cursor.execute("ALTER TABLE user_profiles ADD COLUMN lost_streak INTEGER DEFAULT 0")
    except Exception:
        pass
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS wallet_history (
            id INTEGER PRIMARY KEY AUTO_INCREMENT,
            user_id INTEGER,
            amount INTEGER,
            reason TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    try:
        cursor.execute("SELECT setting_value FROM settings LIMIT 1")
    except Exception:
        cursor.execute("DROP TABLE IF EXISTS settings")
        cursor.execute("""
            CREATE TABLE settings (
                setting_key VARCHAR(255) PRIMARY KEY,
                setting_value TEXT
            )
        """)
    try:
        cursor.execute("SELECT called_at FROM api_logs LIMIT 1")
    except Exception:
        cursor.execute("DROP TABLE IF EXISTS api_logs")
        cursor.execute("""
            CREATE TABLE api_logs (
                id INTEGER PRIMARY KEY AUTO_INCREMENT,
                called_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
    conn.close()


def get_users():
    init_db()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM users WHERE is_deleted = 0")
    users = [{"id": row[0], "name": row[1]} for row in cursor.fetchall()]
    conn.close()
    return users

def get_user(user_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM users WHERE id = %s", (user_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {"id": row[0], "name": row[1]}
    return None

def create_user(name: str):
    init_db()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO users (name) VALUES (%s) RETURNING id", (name,))
    new_id = cursor.fetchone()[0]
    conn.close()
    return {"id": new_id, "name": name}

def save_progress(user_id: int, topic: str, score: int, stars: int):
    init_db()
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO progress (user_id, topic, score, stars) VALUES (%s, %s, %s, %s)", (user_id, topic, score, stars))
    except Exception as e:
        print(f"[DB] save_progress skipped for user_id={user_id}: {e}")
    finally:
        conn.close()

def get_learning_history(user_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT 
            DATE(created_at) as play_date, 
            DATE_FORMAT(created_at, '%%H:00') as play_hour, 
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
            "date": r[0].strftime('%Y-%m-%d') if r[0] else None,
            "hour": r[1],
            "interactions": r[2],
            "avg_score": round(r[3], 1) if r[3] else 0,
            "topics": r[4]
        })
    return history

def get_dashboard_stats(user_id: int):
    init_db()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*), AVG(score), SUM(stars) FROM progress WHERE user_id = %s", (user_id,))
    total_r = cursor.fetchone()
    
    today = datetime.now().strftime('%Y-%m-%d')
    cursor.execute("SELECT COUNT(*), AVG(score), SUM(stars) FROM progress WHERE user_id = %s AND DATE(created_at) = %s", (user_id, today))
    today_r = cursor.fetchone()
    
    cursor.execute("SELECT wallet_balance, current_streak, last_played_date, gacha_claimed_date, lost_streak FROM user_profiles WHERE user_id = %s", (user_id,))
    profile_r = cursor.fetchone()
    conn.close()
    
    return {
        "total_interactions": total_r[0] or 0,
        "average_score": round(float(total_r[1]) if total_r[1] else 0, 1),
        "total_stars": total_r[2] or 0,
        "today": {
            "interactions": today_r[0] or 0,
            "average_score": round(float(today_r[1]) if today_r[1] else 0, 1),
            "total_stars": today_r[2] or 0
        },
        "profile": {
            "wallet_balance": profile_r[0] if profile_r else 0,
            "current_streak": profile_r[1] if profile_r else 0,
            "last_played_date": str(profile_r[2]) if profile_r and profile_r[2] else None,
            "gacha_claimed_today": (str(profile_r[3]) == today) if profile_r else False,
            "lost_streak": profile_r[4] if profile_r and len(profile_r) > 4 else 0
        }
    }

def spend_wallet(user_id: int, amount: int, reason: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT wallet_balance FROM user_profiles WHERE user_id=%s", (user_id,))
    row = cursor.fetchone()
    if row and row[0] >= amount:
        cursor.execute("UPDATE user_profiles SET wallet_balance = wallet_balance - %s WHERE user_id=%s", (amount, user_id))
        cursor.execute("INSERT INTO wallet_history (user_id, amount, reason) VALUES (%s, %s, %s)", (user_id, -amount, reason))
        conn.close()
        return True
    conn.close()
    return False

def get_wallet_history(user_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT amount, reason, created_at FROM wallet_history WHERE user_id=%s ORDER BY id DESC LIMIT 20", (user_id,))
    history = [{"amount": row[0], "reason": row[1], "date": row[2].strftime('%Y-%m-%d %H:%M:%S') if row[2] else None} for row in cursor.fetchall()]
    conn.close()
    return history

def record_play_for_streak(user_id: int):
    from datetime import datetime, timedelta
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT IGNORE INTO user_profiles (user_id) VALUES (%s)", (user_id,))
        today = datetime.now().strftime("%Y-%m-%d")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        cursor.execute("SELECT current_streak, last_played_date FROM user_profiles WHERE user_id=%s", (user_id,))
        row = cursor.fetchone()
        if row:
            streak, last_date = row[0], row[1]
            last_date_str = str(last_date) if last_date else None
            if last_date_str == yesterday:
                cursor.execute("UPDATE user_profiles SET current_streak = current_streak + 1, last_played_date = %s WHERE user_id=%s", (today, user_id))
            elif last_date_str != today:
                cursor.execute("UPDATE user_profiles SET current_streak = 1, last_played_date = %s WHERE user_id=%s", (today, user_id))
        else:
            cursor.execute("UPDATE user_profiles SET current_streak = 1, last_played_date = %s WHERE user_id=%s", (today, user_id))
    except Exception:
        pass
    conn.close()
    
def claim_daily_gacha(user_id: int, reward_amount: int):
    conn = get_connection()
    cursor = conn.cursor()
    today = datetime.now().strftime('%Y-%m-%d')
    cursor.execute("UPDATE user_profiles SET wallet_balance = wallet_balance + %s, gacha_claimed_date = %s WHERE user_id=%s", (reward_amount, today, user_id))
    cursor.execute("INSERT INTO wallet_history (user_id, amount, reason) VALUES (%s, %s, %s)", (user_id, reward_amount, "สุ่มกาชาประจำวัน"))
    conn.close()
    
def get_admin_dashboard_data():
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN is_deleted INTEGER DEFAULT 0")
    except Exception:
        pass
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
            "avg_score": round(float(row[5]) if row[5] else 0, 1),
            "is_deleted": bool(row[6])
        })
    conn.close()
    return users

def delete_user(user_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN is_deleted INTEGER DEFAULT 0")
    except Exception:
        pass
    cursor.execute("UPDATE users SET is_deleted = 1 WHERE id=%s", (user_id,))
    conn.close()

def restore_user(user_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_deleted = 0 WHERE id=%s", (user_id,))
    conn.close()

# Invite Token System
def _init_invite_table():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS invite_tokens (
            id INTEGER PRIMARY KEY AUTO_INCREMENT,
            code VARCHAR(255) UNIQUE,
            is_used INTEGER DEFAULT 0,
            used_by TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.close()

def generate_invite_code():
    _init_invite_table()
    import random, string
    code = "VIP-" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO invite_tokens (code) VALUES (%s)", (code,))
    conn.close()
    return code

def get_all_invite_codes():
    _init_invite_table()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT code, is_used, used_by, created_at FROM invite_tokens ORDER BY id DESC")
    results = [{"code": r[0], "is_used": bool(r[1]), "used_by": r[2], "created_at": r[3].strftime('%Y-%m-%d %H:%M:%S') if r[3] else None} for r in cursor.fetchall()]
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
        return False
    if row[0] == 1:
        conn.close()
        return False
        
    cursor.execute("UPDATE invite_tokens SET is_used = 1, used_by = %s WHERE code = %s", (username, code))
    conn.close()
    return True

# Vocabulary Arsenal
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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, word)
        )
    ''')
    conn.close()

def add_vocabulary(user_id: int, word: str, pos: str, meaning: str):
    _init_vocab_table()
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO user_vocabulary (user_id, word, part_of_speech, meaning) VALUES (%s, %s, %s, %s)", (user_id, word, pos, meaning))
        success = True
    except Exception:
        success = False
    conn.close()
    return success

def get_user_vocabulary(user_id: int):
    _init_vocab_table()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT word, part_of_speech, meaning, created_at FROM user_vocabulary WHERE user_id = %s ORDER BY id DESC", (user_id,))
    vocab = [{"word": r[0], "part_of_speech": r[1], "meaning": r[2], "created_at": r[3].strftime('%Y-%m-%d %H:%M:%S') if r[3] else None} for r in cursor.fetchall()]
    conn.close()
    return vocab


def get_user_dashboard(user_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*), AVG(score), SUM(stars) FROM progress WHERE user_id = %s", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return {
        "total_interactions": row[0] or 0,
        "average_score": round(float(row[1]) if row[1] else 0, 1),
        "total_stars": row[2] or 0
    }

def get_today_dashboard(user_id: int):
    from datetime import datetime
    conn = get_connection()
    cursor = conn.cursor()
    today = datetime.now().strftime('%Y-%m-%d')
    cursor.execute("SELECT COUNT(*), AVG(score), SUM(stars) FROM progress WHERE user_id = %s AND DATE(created_at) = %s", (user_id, today))
    row = cursor.fetchone()
    conn.close()
    return {
        "interactions": row[0] or 0,
        "average_score": round(float(row[1]) if row[1] else 0, 1),
        "total_stars": row[2] or 0
    }

def get_user_profile(user_id: int):
    from datetime import datetime
    conn = get_connection()
    cursor = conn.cursor()
    today = datetime.now().strftime('%Y-%m-%d')
    cursor.execute("SELECT wallet_balance, current_streak, last_played_date, gacha_claimed_date, lost_streak FROM user_profiles WHERE user_id = %s", (user_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {
            "wallet_balance": row[0] or 0,
            "current_streak": row[1] or 0,
            "last_played_date": str(row[2]) if row[2] else None,
            "gacha_claimed_today": (str(row[3]) == today),
            "lost_streak": row[4] or 0
        }
    return {
        "wallet_balance": 0,
        "current_streak": 0,
        "last_played_date": None,
        "gacha_claimed_today": False,
        "lost_streak": 0
    }

def reset_today_progress(user_id: int):
    from datetime import datetime
    conn = get_connection()
    cursor = conn.cursor()
    today = datetime.now().strftime('%Y-%m-%d')
    cursor.execute("DELETE FROM progress WHERE user_id = %s AND DATE(created_at) = %s", (user_id, today))
    conn.close()


def get_setting(key: str, default: str = "") -> str:
    init_db()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT setting_value FROM settings WHERE setting_key = %s", (key,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return row[0]
    return default

def update_setting(key: str, value: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO settings (setting_key, setting_value) VALUES (%s, %s) ON DUPLICATE KEY UPDATE setting_value = %s", (key, value, value))
    conn.close()

def get_or_create_user(name: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM users WHERE name = %s AND is_deleted = 0", (name,))
    row = cursor.fetchone()
    if row:
        conn.close()
        return {"id": row[0], "name": row[1]}
    cursor.execute("INSERT INTO users (name) VALUES (%s)", (name,))
    new_id = cursor.lastrowid
    conn.close()
    return {"id": new_id, "name": name}

def get_all_users():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM users WHERE is_deleted = 0")
    users = [{"id": row[0], "name": row[1]} for row in cursor.fetchall()]
    conn.close()
    return users

def withdraw_money(user_id: int, amount: int):
    return spend_wallet(user_id, amount, "ถอนเงิน")

def add_money(user_id: int, amount: int, reason: str = "Reward"):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE user_profiles SET wallet_balance = wallet_balance + %s WHERE user_id=%s", (amount, user_id))
    cursor.execute("INSERT INTO wallet_history (user_id, amount, reason) VALUES (%s, %s, %s)", (user_id, amount, reason))
    conn.close()

def restore_user_streak(user_id: int, cost: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT wallet_balance FROM user_profiles WHERE user_id=%s", (user_id,))
    row = cursor.fetchone()
    if row and row[0] >= cost:
        cursor.execute("UPDATE user_profiles SET wallet_balance = wallet_balance - %s, lost_streak = 0 WHERE user_id=%s", (cost, user_id))
        cursor.execute("INSERT INTO wallet_history (user_id, amount, reason) VALUES (%s, %s, %s)", (user_id, -cost, "ซื้อ Streak คืน"))
        conn.close()
        return True
    conn.close()
    return False

def get_daily_quota_usage():
    from datetime import datetime
    conn = get_connection()
    cursor = conn.cursor()
    today = datetime.now().strftime('%Y-%m-%d')
    cursor.execute("SELECT COUNT(*) FROM api_logs WHERE DATE(called_at) = %s", (today,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else 0

def log_api_call():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO api_logs (called_at) VALUES (CURRENT_TIMESTAMP)")
    conn.close()

def get_full_dashboard(user_id: int):
    from datetime import datetime
    conn = get_connection()
    try:
        cursor = conn.cursor()
        today = datetime.now().strftime('%Y-%m-%d')
        
        # 1. user_dashboard
        cursor.execute("SELECT COUNT(*), AVG(score), SUM(stars) FROM progress WHERE user_id = %s", (user_id,))
        row1 = cursor.fetchone()
        stats = {
            "total_interactions": row1[0] or 0,
            "average_score": round(row1[1] or 0, 1) if row1[1] else 0,
            "total_stars": row1[2] or 0
        }
        
        # 2. today_dashboard
        cursor.execute("SELECT COUNT(*), AVG(score), SUM(stars) FROM progress WHERE user_id = %s AND DATE(created_at) = %s", (user_id, today))
        row2 = cursor.fetchone()
        today_stats = {
            "interactions": row2[0] or 0,
            "average_score": round(row2[1] or 0, 1) if row2[1] else 0,
            "total_stars": int(row2[2] or 0)
        }
        
        # 3. user_profile
        cursor.execute("SELECT wallet_balance, current_streak, last_played_date, gacha_claimed_date, lost_streak FROM user_profiles WHERE user_id = %s", (user_id,))
        row3 = cursor.fetchone()
        if row3:
            profile = {
                "wallet_balance": row3[0],
                "current_streak": row3[1],
                "last_played_date": str(row3[2]) if row3[2] else None,
                "gacha_claimed_today": str(row3[3]) == today if row3[3] else False,
                "lost_streak": row3[4] or 0
            }
        else:
            profile = {
                "wallet_balance": 0, "current_streak": 0, "last_played_date": None,
                "gacha_claimed_today": False, "lost_streak": 0
            }
            
        # 4. wallet_history
        cursor.execute("SELECT amount, reason, created_at FROM wallet_history WHERE user_id=%s ORDER BY id DESC LIMIT 20", (user_id,))
        wallet_history = [{"amount": r[0], "reason": r[1], "date": r[2].strftime('%Y-%m-%d %H:%M:%S') if r[2] else None} for r in cursor.fetchall()]
        
        # 5. learning_history
        cursor.execute('''
            SELECT 
                DATE(created_at) as play_date, 
                DATE_FORMAT(created_at, '%%H:00') as play_hour, 
                COUNT(id) as interactions, 
                AVG(score) as avg_score,
                GROUP_CONCAT(DISTINCT topic) as topics
            FROM progress 
            WHERE user_id = %s 
            GROUP BY play_date, play_hour
            ORDER BY play_date DESC, play_hour DESC
            LIMIT 50
        ''', (user_id,))
        rows5 = cursor.fetchall()
        learning_history = []
        for r in rows5:
            learning_history.append({
                "date": r[0].strftime('%Y-%m-%d') if hasattr(r[0], 'strftime') else str(r[0]) if r[0] else None,
                "hour": r[1],
                "interactions": r[2],
                "avg_score": round(r[3], 1) if r[3] else 0,
                "topics": r[4]
            })
            
        return {
            "stats": stats,
            "today_stats": today_stats,
            "profile": profile,
            "wallet_history": wallet_history,
            "learning_history": learning_history
        }
    finally:
        conn.close()
