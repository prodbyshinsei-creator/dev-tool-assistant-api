import sqlite3
import os
from typing import List, Dict, Optional
from cryptography.fernet import Fernet
import requests

DB_PATH = os.environ.get("DB_PATH", "/tmp/volume_bot.db")

def _get_cipher():
    key = os.environ.get("ENCRYPT_KEY", "")
    if not key:
        raise ValueError("ENCRYPT_KEY not set")
    return Fernet(key.encode())

def _get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def _init_db():
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS wallets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            address TEXT NOT NULL,
            name TEXT NOT NULL,
            private_key_enc TEXT NOT NULL,
            wallet_type TEXT NOT NULL DEFAULT 'volume',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, address, wallet_type)
        );

        CREATE TABLE IF NOT EXISTS launches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            original_ca TEXT NOT NULL,
            launched_ca TEXT,
            name TEXT,
            ticker TEXT,
            description TEXT,
            image_url TEXT,
            website TEXT,
            twitter TEXT,
            telegram TEXT,
            dev_wallet TEXT NOT NULL,
            dev_buy_sol REAL NOT NULL,
            launch_num INTEGER NOT NULL,
            status TEXT DEFAULT 'active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    conn.close()

_init_db()

def get_sol_balance(address: str) -> Optional[float]:
    try:
        rpc = os.environ.get("HELIUS_RPC", "")
        if not rpc:
            return None
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getBalance",
            "params": [address]
        }
        resp = requests.post(rpc, json=payload, timeout=5)
        result = resp.json()
        if "result" in result:
            lamports = result["result"]["value"]
            return lamports / 1_000_000_000
        return None
    except Exception:
        return None

class Database:
    # ── WALLETS ───────────────────────────────────────────────────────────────

    def get_wallets(self, user_id: int, wallet_type: str = 'volume') -> List[Dict]:
        conn = _get_conn()
        try:
            cur = conn.execute(
                "SELECT address, name, wallet_type FROM wallets WHERE user_id = ? AND wallet_type = ? ORDER BY created_at",
                (user_id, wallet_type)
            )
            return [dict(row) for row in cur.fetchall()]
        finally:
            conn.close()

    def get_wallets_with_balance(self, user_id: int, wallet_type: str = 'volume') -> List[Dict]:
        wallets = self.get_wallets(user_id, wallet_type)
        result = []
        for w in wallets:
            balance = get_sol_balance(w['address'])
            result.append({**w, 'balance': balance})
        return result

    def get_wallet_privkey(self, user_id: int, address: str) -> Optional[str]:
        conn = _get_conn()
        try:
            cur = conn.execute(
                "SELECT private_key_enc FROM wallets WHERE user_id = ? AND address = ?",
                (user_id, address)
            )
            row = cur.fetchone()
            if not row:
                return None
            cipher = _get_cipher()
            return cipher.decrypt(row["private_key_enc"].encode()).decode()
        finally:
            conn.close()

    def add_wallet(self, user_id: int, address: str, name: str, private_key: str, wallet_type: str = 'volume') -> bool:
        conn = _get_conn()
        try:
            cipher = _get_cipher()
            enc = cipher.encrypt(private_key.encode()).decode()
            conn.execute(
                "INSERT OR REPLACE INTO wallets (user_id, address, name, private_key_enc, wallet_type) VALUES (?, ?, ?, ?, ?)",
                (user_id, address, name, enc, wallet_type)
            )
            conn.commit()
            return True
        except Exception:
            conn.rollback()
            return False
        finally:
            conn.close()

    def delete_wallet(self, user_id: int, address: str, wallet_type: str = 'volume') -> bool:
        conn = _get_conn()
        try:
            cur = conn.execute(
                "DELETE FROM wallets WHERE user_id = ? AND address = ? AND wallet_type = ?",
                (user_id, address, wallet_type)
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    # ── LAUNCHES ──────────────────────────────────────────────────────────────

    def add_launch(self, user_id: int, original_ca: str, dev_wallet: str,
                   dev_buy_sol: float, launch_num: int, meta: dict) -> int:
        conn = _get_conn()
        try:
            cur = conn.execute(
                """INSERT INTO launches
                   (user_id, original_ca, name, ticker, description, image_url,
                    website, twitter, telegram, dev_wallet, dev_buy_sol, launch_num)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (user_id, original_ca,
                 meta.get('name'), meta.get('ticker'), meta.get('description'),
                 meta.get('image_url'), meta.get('website'), meta.get('twitter'),
                 meta.get('telegram'), dev_wallet, dev_buy_sol, launch_num)
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def update_launch_ca(self, launch_id: int, launched_ca: str):
        conn = _get_conn()
        try:
            conn.execute(
                "UPDATE launches SET launched_ca = ? WHERE id = ?",
                (launched_ca, launch_id)
            )
            conn.commit()
        finally:
            conn.close()

    def get_active_launches(self, user_id: int) -> List[Dict]:
        conn = _get_conn()
        try:
            cur = conn.execute(
                "SELECT * FROM launches WHERE user_id = ? AND status = 'active' ORDER BY launch_num",
                (user_id,)
            )
            return [dict(row) for row in cur.fetchall()]
        finally:
            conn.close()

    def close_launch(self, launch_id: int):
        conn = _get_conn()
        try:
            conn.execute(
                "UPDATE launches SET status = 'closed' WHERE id = ?",
                (launch_id,)
            )
            conn.commit()
        finally:
            conn.close()

    def close_all_launches(self, user_id: int):
        conn = _get_conn()
        try:
            conn.execute(
                "UPDATE launches SET status = 'closed' WHERE user_id = ? AND status = 'active'",
                (user_id,)
            )
            conn.commit()
        finally:
            conn.close()
