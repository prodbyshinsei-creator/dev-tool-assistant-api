import threading
import time
import random
import uuid
import logging
import base64
from typing import Dict, Optional, List
import requests

from config import Config

logger = logging.getLogger(__name__)

class Session:
    def __init__(self, session_id: str, user_id: int, ca: str,
                 wallets: List[str], min_sol: float, max_sol: float, db):
        self.session_id = session_id
        self.user_id = user_id
        self.ca = ca
        self.wallets = wallets
        self.min_sol = min_sol
        self.max_sol = max_sol
        self.db = db
        self.paused = False
        self.stopped = False
        self.txs = 0
        self.fees_sol = 0.0
        self.consecutive_errors = 0
        self.thread: Optional[threading.Thread] = None


class VolumeEngine:
    def __init__(self):
        self.sessions: Dict[str, Session] = {}

    def start_session(self, user_id: int, ca: str, wallets: List[str],
                      min_sol: float, max_sol: float, db) -> str:
        session_id = str(uuid.uuid4())[:8]
        s = Session(session_id, user_id, ca, wallets, min_sol, max_sol, db)
        self.sessions[session_id] = s
        t = threading.Thread(target=self._run_loop, args=(s,), daemon=True)
        s.thread = t
        t.start()
        logger.info(f"Session {session_id} started for user {user_id}, CA={ca}")
        return session_id

    def toggle_pause(self, session_id: str) -> bool:
        s = self.sessions.get(session_id)
        if not s:
            return False
        s.paused = not s.paused
        return s.paused

    def stop_session(self, session_id: str) -> dict:
        s = self.sessions.get(session_id)
        if not s:
            return {}
        s.stopped = True
        if s.thread and s.thread.is_alive():
            s.thread.join(timeout=10)
        sold = self._sell_all(s)
        stats = {
            "txs": s.txs,
            "fees_sol": round(s.fees_sol, 6),
            "sold": sold
        }
        self.sessions.pop(session_id, None)
        return stats

    def _sell_all(self, s: Session) -> int:
        sold_count = 0
        for address in s.wallets:
            try:
                privkey = s.db.get_wallet_privkey(s.user_id, address)
                if not privkey:
                    continue
                for attempt in range(3):
                    slippage = 20 + (attempt * 15)
                    success = self._send_sell(s.ca, address, privkey, slippage=slippage)
                    if success:
                        sold_count += 1
                        logger.info(f"[{s.session_id}] Final sell OK (attempt {attempt+1}): {address[:8]}...")
                        break
                    else:
                        logger.warning(f"[{s.session_id}] Final sell attempt {attempt+1} failed, retrying...")
                        time.sleep(1.5)
            except Exception as e:
                logger.error(f"[{s.session_id}] Final sell error {address[:8]}: {e}")
        return sold_count

    def _run_loop(self, s: Session):
        while not s.stopped:
            if s.paused:
                time.sleep(1)
                continue

            # Если несколько кошельков — запускаем их параллельно
            if len(s.wallets) > 1:
                threads = []
                for wallet in s.wallets:
                    if s.stopped:
                        break
                    t = threading.Thread(
                        target=self._cycle_one_wallet,
                        args=(s, wallet),
                        daemon=True
                    )
                    t.start()
                    threads.append(t)
                    # Небольшой сдвиг между кошельками для органики
                    time.sleep(random.uniform(0.3, 1.0))
                for t in threads:
                    t.join(timeout=30)
            else:
                wallet = s.wallets[0]
                self._cycle_one_wallet(s, wallet)

            # Пауза между раундами: 2-5 сек
            sleep_time = random.uniform(2, 5)
            for _ in range(int(sleep_time)):
                if s.stopped:
                    break
                time.sleep(1)

    def _cycle_one_wallet(self, s: Session, wallet: str):
        amount_sol = round(random.uniform(s.min_sol, s.max_sol), 6)
        try:
            privkey = s.db.get_wallet_privkey(s.user_id, wallet)
            if privkey:
                self._do_buy_sell(s, wallet, privkey, amount_sol)
                s.consecutive_errors = 0
        except Exception as e:
            s.consecutive_errors += 1
            logger.error(f"[{s.session_id}] Error #{s.consecutive_errors}: {e}")
            if s.consecutive_errors >= 3:
                logger.warning(f"[{s.session_id}] 3 errors, auto-restart in 3s...")
                s.consecutive_errors = 0
                time.sleep(3)
            else:
                time.sleep(2)

    def _do_buy_sell(self, s: Session, wallet_address: str, privkey: str, amount_sol: float):
        if s.stopped:
            return

        api_url = "https://pumpportal.fun/api/trade-local"

        buy_payload = {
            "publicKey": wallet_address,
            "action": "buy",
            "mint": s.ca,
            "denominatedInSol": "true",
            "amount": amount_sol,
            "slippage": 10,
            "priorityFee": 0.00003,
            "pool": "pump"
        }

        resp = requests.post(api_url, data=buy_payload, timeout=15)
        if resp.status_code != 200:
            raise Exception(f"Buy API error: {resp.status_code} {resp.text[:100]}")

        sig = self._sign_and_send(resp.content, privkey)
        if not sig:
            raise Exception("Buy sign/send failed")

        logger.info(f"[{s.session_id}] BUY sent: {sig[:16]}...")
        s.txs += 1
        s.fees_sol += 0.00003 + 0.000005

        if s.stopped:
            return

        # Быстрая пауза между buy и sell: 0.5-1.5 сек
        time.sleep(random.uniform(0.5, 1.5))

        if s.stopped:
            return

        success = self._send_sell(s.ca, wallet_address, privkey, slippage=10)
        if not success:
            raise Exception("Sell failed")

        s.txs += 1
        s.fees_sol += 0.00003 + 0.000005

    def _send_sell(self, ca: str, wallet_address: str, privkey: str, slippage: int = 20) -> bool:
        api_url = "https://pumpportal.fun/api/trade-local"
        sell_payload = {
            "publicKey": wallet_address,
            "action": "sell",
            "mint": ca,
            "denominatedInSol": "false",
            "amount": "100%",
            "slippage": slippage,
            "priorityFee": 0.00003,
            "pool": "pump"
        }
        try:
            resp = requests.post(api_url, data=sell_payload, timeout=15)
            if resp.status_code != 200:
                logger.warning(f"Sell API error: {resp.status_code}")
                return False
            sig = self._sign_and_send(resp.content, privkey)
            if sig:
                logger.info(f"SELL sent: {sig[:16]}...")
                return True
        except Exception as e:
            logger.error(f"Sell error: {e}")
        return False

    def _sign_and_send(self, tx_bytes: bytes, privkey_b58: str) -> Optional[str]:
        try:
            from solders.keypair import Keypair
            from solders.transaction import VersionedTransaction

            kp = Keypair.from_base58_string(privkey_b58)
            tx = VersionedTransaction.from_bytes(tx_bytes)
            signed = VersionedTransaction(tx.message, [kp])
            signed_bytes = bytes(signed)
            encoded = base64.b64encode(signed_bytes).decode()

            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "sendTransaction",
                "params": [
                    encoded,
                    {
                        "encoding": "base64",
                        "skipPreflight": True,
                        "maxRetries": 3,
                        "preflightCommitment": "processed"
                    }
                ]
            }

            rpc_resp = requests.post(Config.HELIUS_RPC, json=payload, timeout=20)
            result = rpc_resp.json()

            if "result" in result:
                return result["result"]
            else:
                logger.error(f"RPC error: {result.get('error')}")
                return None

        except Exception as e:
            logger.error(f"Sign/send error: {e}")
            return None
