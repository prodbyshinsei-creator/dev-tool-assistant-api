import sqlite3
import logging
from typing import Optional, List, Dict
from datetime import datetime

logger = logging.getLogger(__name__)

class Database:
    def __init__(self, db_path: str = "dev_tool_assistant.db"):
        self.db_path = db_path
        self.init_db()
    
    def get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def init_db(self):
        """Initialize database tables"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Wallets table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS wallets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                address TEXT NOT NULL,
                privkey TEXT NOT NULL,
                wallet_type TEXT NOT NULL,
                balance REAL DEFAULT 0.0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Volume sessions table (for history)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS volume_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL UNIQUE,
                user_id INTEGER NOT NULL,
                ca TEXT NOT NULL,
                wallets_count INTEGER,
                min_sol REAL,
                max_sol REAL,
                total_txs INTEGER DEFAULT 0,
                total_fees REAL DEFAULT 0.0,
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                stopped_at TIMESTAMP
            )
        """)
        
        # Launched tokens table (for history)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS launched_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                original_ca TEXT NOT NULL,
                cloned_ca TEXT NOT NULL,
                name TEXT,
                ticker TEXT,
                dev_buy_sol REAL,
                dev_wallet_address TEXT,
                launched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        conn.commit()
        conn.close()
        logger.info(f"Database initialized at {self.db_path}")
    
    # ==================== Wallet Methods ====================
    
    def add_wallet(
        self,
        user_id: int,
        name: str,
        address: str,
        privkey: str,
        wallet_type: str
    ) -> int:
        """Add a new wallet and return its ID"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO wallets (user_id, name, address, privkey, wallet_type)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, name, address, privkey, wallet_type))
        
        wallet_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        logger.info(f"Added wallet: {name} ({address[:8]}...) type={wallet_type}")
        return wallet_id
    
    def get_user_wallets(
        self,
        user_id: int,
        wallet_type: Optional[str] = None
    ) -> List[Dict]:
        """Get all wallets for a user"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        if wallet_type:
            cursor.execute("""
                SELECT id, name, address, wallet_type, balance, created_at
                FROM wallets
                WHERE user_id = ? AND wallet_type = ?
                ORDER BY created_at DESC
            """, (user_id, wallet_type))
        else:
            cursor.execute("""
                SELECT id, name, address, wallet_type, balance, created_at
                FROM wallets
                WHERE user_id = ?
                ORDER BY created_at DESC
            """, (user_id,))
        
        rows = cursor.fetchall()
        conn.close()
        
        wallets = []
        for row in rows:
            wallets.append({
                'id': row['id'],
                'name': row['name'],
                'address': row['address'],
                'wallet_type': row['wallet_type'],
                'balance': row['balance'],
                'created_at': row['created_at']
            })
        
        return wallets
    
    def get_wallet(self, user_id: int, wallet_id: int) -> Optional[Dict]:
        """Get specific wallet by ID"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, name, address, wallet_type, balance, created_at
            FROM wallets
            WHERE user_id = ? AND id = ?
        """, (user_id, wallet_id))
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return {
                'id': row['id'],
                'name': row['name'],
                'address': row['address'],
                'wallet_type': row['wallet_type'],
                'balance': row['balance'],
                'created_at': row['created_at']
            }
        return None
    
    def get_wallet_by_address(self, user_id: int, address: str) -> Optional[Dict]:
        """Get wallet by address"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, name, address, privkey, wallet_type, balance
            FROM wallets
            WHERE user_id = ? AND address = ?
        """, (user_id, address))
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return {
                'id': row['id'],
                'name': row['name'],
                'address': row['address'],
                'privkey': row['privkey'],
                'wallet_type': row['wallet_type'],
                'balance': row['balance']
            }
        return None
    
    def get_wallet_privkey(self, user_id: int, address: str) -> Optional[str]:
        """Get private key for a wallet"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT privkey FROM wallets
            WHERE user_id = ? AND address = ?
        """, (user_id, address))
        
        row = cursor.fetchone()
        conn.close()
        
        return row['privkey'] if row else None
    
    def delete_wallet(self, user_id: int, wallet_id: int):
        """Delete a wallet"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            DELETE FROM wallets
            WHERE user_id = ? AND id = ?
        """, (user_id, wallet_id))
        
        conn.commit()
        conn.close()
        logger.info(f"Deleted wallet ID: {wallet_id}")
    
    def update_wallet_balance(self, user_id: int, address: str, balance: float):
        """Update wallet balance"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE wallets
            SET balance = ?
            WHERE user_id = ? AND address = ?
        """, (balance, user_id, address))
        
        conn.commit()
        conn.close()
    
    # ==================== Volume Session Methods ====================
    
    def save_volume_session(
        self,
        session_id: str,
        user_id: int,
        ca: str,
        wallets_count: int,
        min_sol: float,
        max_sol: float
    ):
        """Save volume session to history"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO volume_sessions 
            (session_id, user_id, ca, wallets_count, min_sol, max_sol)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (session_id, user_id, ca, wallets_count, min_sol, max_sol))
        
        conn.commit()
        conn.close()
    
    def update_volume_session_stats(
        self,
        session_id: str,
        total_txs: int,
        total_fees: float
    ):
        """Update session stats"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE volume_sessions
            SET total_txs = ?, total_fees = ?, stopped_at = CURRENT_TIMESTAMP
            WHERE session_id = ?
        """, (total_txs, total_fees, session_id))
        
        conn.commit()
        conn.close()
    
    def get_volume_sessions(self, user_id: int, limit: int = 10) -> List[Dict]:
        """Get volume session history"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT * FROM volume_sessions
            WHERE user_id = ?
            ORDER BY started_at DESC
            LIMIT ?
        """, (user_id, limit))
        
        rows = cursor.fetchall()
        conn.close()
        
        sessions = []
        for row in rows:
            sessions.append(dict(row))
        
        return sessions
    
    # ==================== Launched Tokens Methods ====================
    
    def save_launched_token(
        self,
        user_id: int,
        original_ca: str,
        cloned_ca: str,
        name: str,
        ticker: str,
        dev_buy_sol: float,
        dev_wallet_address: str
    ):
        """Save launched token to history"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO launched_tokens
            (user_id, original_ca, cloned_ca, name, ticker, dev_buy_sol, dev_wallet_address)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (user_id, original_ca, cloned_ca, name, ticker, dev_buy_sol, dev_wallet_address))
        
        conn.commit()
        conn.close()
        logger.info(f"Saved launched token: {ticker} ({cloned_ca[:8]}...)")
    
    def get_launched_tokens(self, user_id: int, limit: int = 50) -> List[Dict]:
        """Get launch history"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT * FROM launched_tokens
            WHERE user_id = ?
            ORDER BY launched_at DESC
            LIMIT ?
        """, (user_id, limit))
        
        rows = cursor.fetchall()
        conn.close()
        
        tokens = []
        for row in rows:
            tokens.append(dict(row))
        
        return tokens
    
    # ==================== Utility Methods ====================
    
    def get_wallet_count(self, user_id: int, wallet_type: Optional[str] = None) -> int:
        """Get total wallet count"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        if wallet_type:
            cursor.execute("""
                SELECT COUNT(*) as count FROM wallets
                WHERE user_id = ? AND wallet_type = ?
            """, (user_id, wallet_type))
        else:
            cursor.execute("""
                SELECT COUNT(*) as count FROM wallets
                WHERE user_id = ?
            """, (user_id,))
        
        row = cursor.fetchone()
        conn.close()
        
        return row['count'] if row else 0
    
    def close(self):
        """Close database (cleanup method)"""
        pass  # SQLite doesn't need explicit close for file-based DB
