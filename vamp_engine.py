import requests
import base64
import logging
import os
import json
import base58
import time
import random
from typing import Optional, Dict, Tuple
from config import Config

logger = logging.getLogger(__name__)


def get_token_metadata(ca: str) -> Optional[Dict]:
    """Get metadata via GMGN API (fast) with IPFS fallback"""
    clean_ca = ca.strip()
    if clean_ca.endswith('pump') and len(clean_ca) > 44:
        clean_ca = clean_ca[:-4].strip()
    
    logger.info(f"Getting metadata for CA: {clean_ca}")
    
    # Try GMGN API first (fast)
    try:
        url = f"https://gmgn.ai/defi/quotation/v1/tokens/sol/{clean_ca}"
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            token = data.get('data', {}).get('token', {})
            if token:
                name = token.get('name', '')
                symbol = token.get('symbol', '')
                description = token.get('description', '')
                image = token.get('logo', '')
                twitter = token.get('twitter', '')
                telegram = token.get('telegram', '')
                website = token.get('website', '')
                
                if name:
                    logger.info(f"GMGN OK: name={name} symbol={symbol}")
                    return {
                        'name': name,
                        'ticker': symbol,
                        'description': description,
                        'image_url': image,
                        'twitter': twitter,
                        'telegram': telegram,
                        'website': website,
                        'market_cap': 0,
                    }
    except Exception as e:
        logger.warning(f"GMGN API failed: {e}, falling back to Helius")
    
    # Fallback to Helius + IPFS
    try:
        rpc = Config.HELIUS_RPC
        payload = {"jsonrpc": "2.0", "id": 1, "method": "getAsset", "params": {"id": clean_ca}}
        resp = requests.post(rpc, json=payload, timeout=10)
        full = resp.json()
        result = full.get('result', {})
        content = result.get('content', {})
        json_uri = content.get('json_uri', '')
        metadata = content.get('metadata', {})
        files = content.get('files', [])
        
        name = metadata.get('name', '')
        ticker = metadata.get('symbol', '')
        description = metadata.get('description', '')
        image_url = ''
        if files:
            image_url = files[0].get('cdn_uri', '') or files[0].get('uri', '')
        
        twitter = ''
        telegram = ''
        website = ''
        
        if json_uri:
            ipfs_hash = json_uri
            for prefix in ['https://ipfs.io/ipfs/', 'https://gateway.ipfs.io/ipfs/']:
                ipfs_hash = ipfs_hash.replace(prefix, '')
            gateways = [
                f"https://gateway.pinata.cloud/ipfs/{ipfs_hash}",
                f"https://dweb.link/ipfs/{ipfs_hash}",
                f"https://ipfs.io/ipfs/{ipfs_hash}",
            ]
            for gw in gateways:
                try:
                    r = requests.get(gw, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
                    if r.status_code == 200:
                        j = r.json()
                        name = j.get('name', name)
                        ticker = j.get('symbol', ticker)
                        description = j.get('description', description)
                        image_url = j.get('image', image_url)
                        twitter = j.get('twitter', '')
                        telegram = j.get('telegram', '')
                        website = j.get('website', '')
                        logger.info(f"IPFS OK: name={name} ticker={ticker}")
                        break
                except Exception as e:
                    logger.warning(f"IPFS gateway {gw} failed: {e}")
                    continue
        
        if not name:
            logger.error(f"No name found for {clean_ca}")
            return None
        
        logger.info(f"Got metadata: name={name} ticker={ticker} twitter={twitter}")
        return {
            'name': name, 'ticker': ticker, 'description': description,
            'image_url': image_url, 'website': website,
            'twitter': twitter, 'telegram': telegram, 'market_cap': 0,
        }
    except Exception as e:
        logger.error(f"get_token_metadata error: {e}")
    return None


def get_token_market_cap(ca: str) -> Optional[float]:
    clean_ca = ca.strip()
    if clean_ca.endswith('pump') and len(clean_ca) > 44:
        clean_ca = clean_ca[:-4].strip()
    try:
        # Try GMGN first
        url = f"https://gmgn.ai/defi/quotation/v1/tokens/sol/{clean_ca}"
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            mc = data.get('data', {}).get('token', {}).get('market_cap')
            if mc:
                return float(mc)
    except:
        pass
    
    # Fallback to DexScreener
    try:
        url = f"https://api.dexscreener.com/latest/dex/tokens/{clean_ca}"
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            pairs = data.get('pairs', [])
            if pairs:
                mc = pairs[0].get('marketCap', 0)
                return float(mc) if mc else 0
    except Exception as e:
        logger.error(f"get_market_cap error: {e}")
    return None


def download_image(image_url: str) -> Optional[Tuple[bytes, str]]:
    """Download image from URL, returns (data, content_type)"""
    try:
        if not image_url:
            logger.error("No image URL provided")
            return None
            
        ipfs_hash = image_url
        for prefix in ['https://ipfs.io/ipfs/', 'https://gateway.ipfs.io/ipfs/']:
            ipfs_hash = ipfs_hash.replace(prefix, '')
        
        image_urls = [
            f"https://gateway.pinata.cloud/ipfs/{ipfs_hash}",
            f"https://dweb.link/ipfs/{ipfs_hash}",
            image_url,
        ]
        
        for img_url in image_urls:
            try:
                img_resp = requests.get(img_url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
                if img_resp.status_code == 200 and len(img_resp.content) > 100:
                    image_data = img_resp.content
                    ct = img_resp.headers.get('content-type', 'image/png')
                    image_content_type = ct.split(';')[0]
                    logger.info(f"Image OK: {len(image_data)} bytes from {img_url[:50]}")
                    return (image_data, image_content_type)
            except Exception as e:
                logger.warning(f"Image download failed from {img_url[:50]}: {e}")
        
        logger.error("Could not download image from any gateway")
        return None
    except Exception as e:
        logger.error(f"download_image error: {e}")
        return None


def upload_metadata_to_pumpfun(image_data: bytes, image_content_type: str, meta: dict) -> Optional[str]:
    """Upload metadata to pump.fun IPFS ONCE, returns metadataUri"""
    try:
        form_data = {
            'file': ('image.png', image_data, image_content_type),
            'name': (None, meta.get('name', '')[:32]),
            'symbol': (None, meta.get('ticker', '')[:10]),
            'description': (None, meta.get('description', '')[:500]),
            'showName': (None, 'true')
        }
        
        if meta.get('twitter'):
            form_data['twitter'] = (None, meta['twitter'])
        if meta.get('telegram'):
            form_data['telegram'] = (None, meta['telegram'])
        if meta.get('website'):
            form_data['website'] = (None, meta['website'])

        logger.info(f"Uploading to pump.fun IPFS: name={meta.get('name')} twitter={meta.get('twitter')}")
        
        resp = requests.post(
            'https://pump.fun/api/ipfs',
            files=form_data,
            timeout=60
        )
        
        logger.info(f"pump.fun IPFS: {resp.status_code}")
        
        if resp.status_code != 200:
            logger.error(f"pump.fun IPFS failed: {resp.status_code} {resp.text[:200]}")
            return None
            
        result = resp.json()
        metadata_uri = result.get('metadataUri')
        
        if not metadata_uri:
            logger.error(f"No metadataUri in response: {result}")
            return None
            
        logger.info(f"pump.fun metadataUri: {metadata_uri}")
        return metadata_uri
        
    except Exception as e:
        logger.error(f"pump.fun IPFS error: {e}", exc_info=True)
        return None


def launch_token(meta: dict, dev_wallet: str, dev_buy_sol: float, privkey: str) -> Optional[str]:
    """
    DEPRECATED - use prepare_launches + launch_single instead
    This is kept for backwards compatibility
    """
    try:
        # Download image
        image_result = download_image(meta.get('image_url', ''))
        if not image_result:
            logger.error("Could not download image")
            return None
        
        image_data, image_content_type = image_result
        
        # Upload metadata
        metadata_uri = upload_metadata_to_pumpfun(image_data, image_content_type, meta)
        if not metadata_uri:
            logger.error("pump.fun IPFS upload failed")
            return None
        
        # Launch single token
        return launch_single(metadata_uri, meta, dev_wallet, dev_buy_sol, privkey)
        
    except Exception as e:
        logger.error(f"launch_token error: {e}", exc_info=True)
        return None


def prepare_launches(meta: dict) -> Optional[str]:
    """
    Step 1: Download image and upload metadata ONCE
    Returns metadataUri to use for multiple launches
    """
    try:
        # Download image
        image_result = download_image(meta.get('image_url', ''))
        if not image_result:
            logger.error("Could not download image")
            return None
        
        image_data, image_content_type = image_result
        
        # Upload metadata ONCE
        metadata_uri = upload_metadata_to_pumpfun(image_data, image_content_type, meta)
        if not metadata_uri:
            logger.error("pump.fun IPFS upload failed")
            return None
        
        return metadata_uri
        
    except Exception as e:
        logger.error(f"prepare_launches error: {e}", exc_info=True)
        return None


def launch_single(metadata_uri: str, meta: dict, dev_wallet: str, dev_buy_sol: float, privkey: str) -> Optional[str]:
    """
    Step 2: Launch single token using pre-uploaded metadataUri
    Each call creates a NEW mint keypair = unique CA
    """
    try:
        from solders.keypair import Keypair
        from solders.transaction import VersionedTransaction

        logger.info(f"pumpdev.io launch: wallet={dev_wallet} buy={dev_buy_sol}")

        # Get transaction from pumpdev.io
        create_payload = {
            "publicKey": dev_wallet,
            "name": meta.get('name', '')[:32],
            "symbol": meta.get('ticker', '')[:10],
            "uri": metadata_uri,
            "buyAmountSol": float(dev_buy_sol),
            "slippage": 30,
            "priorityFee": 0.0005
        }

        logger.info(f"pumpdev.io request")
        
        try:
            create_resp = requests.post(
                'https://pumpdev.io/api/create',
                headers={"Content-Type": "application/json"},
                json=create_payload,
                timeout=60
            )
            
            logger.info(f"pumpdev.io status: {create_resp.status_code}")
            
            if create_resp.status_code != 200:
                logger.error(f"pumpdev.io failed: {create_resp.status_code} {create_resp.text[:300]}")
                return None

            result = create_resp.json()
            
            if "error" in result:
                logger.error(f"pumpdev.io error: {result['error']}")
                return None

            mint_pubkey = result.get('mint')
            mint_secret = result.get('mintSecretKey')
            tx_b58 = result.get('transaction')

            if not all([mint_pubkey, mint_secret, tx_b58]):
                logger.error(f"pumpdev.io missing fields: {result}")
                return None

            logger.info(f"Got tx from pumpdev.io, mint={mint_pubkey}")

            # Sign transaction
            mint_kp = Keypair.from_base58_string(mint_secret)
            dev_kp = Keypair.from_base58_string(privkey)
            
            tx = VersionedTransaction.from_bytes(base58.b58decode(tx_b58))
            signed_tx = VersionedTransaction(tx.message, [dev_kp, mint_kp])

            # Send to RPC
            tx_bytes = bytes(signed_tx)
            encoded = base64.b64encode(tx_bytes).decode()
            
            send_payload = {
                "jsonrpc": "2.0", "id": 1,
                "method": "sendTransaction",
                "params": [encoded, {
                    "encoding": "base64",
                    "skipPreflight": True,
                    "maxRetries": 3,
                    "preflightCommitment": "processed"
                }]
            }
            
            send_resp = requests.post(Config.HELIUS_RPC, json=send_payload, timeout=20)
            send_result = send_resp.json()
            
            logger.info(f"Send result: {send_result}")

            if "result" in send_result:
                sig = send_result["result"]
                logger.info(f"Token launched! mint={mint_pubkey} sig={sig}")
                return mint_pubkey
            else:
                logger.error(f"Send failed: {send_result.get('error')}")
                return None
                
        except requests.exceptions.Timeout:
            logger.error("pumpdev.io request timeout")
            return None
        except Exception as e:
            logger.error(f"pumpdev.io request error: {e}")
            return None

    except Exception as e:
        logger.error(f"launch_single error: {e}", exc_info=True)
        return None


def sell_token(ca: str, wallet_address: str, privkey: str, slippage: int = 25) -> bool:
    try:
        sell_payload = {
            "publicKey": wallet_address,
            "action": "sell",
            "mint": ca,
            "denominatedInSol": False,
            "amount": "100%",
            "slippage": slippage,
            "priorityFee": 0.0001,
            "pool": "pump"
        }
        resp = requests.post(
            'https://pumpportal.fun/api/trade-local',
            json=sell_payload,
            timeout=15
        )
        if resp.status_code != 200:
            logger.warning(f"Sell API error: {resp.status_code} {resp.text[:200]}")
            return False
        sig = _sign_and_send(resp.content, privkey)
        if sig:
            logger.info(f"Dev sell OK: {sig[:16]}...")
            return True
        return False
    except Exception as e:
        logger.error(f"sell_token error: {e}")
        return False


def _sign_and_send(tx_bytes: bytes, privkey_b58: str) -> Optional[str]:
    try:
        from solders.keypair import Keypair
        from solders.transaction import VersionedTransaction
        kp = Keypair.from_base58_string(privkey_b58)
        tx = VersionedTransaction.from_bytes(tx_bytes)
        signed = VersionedTransaction(tx.message, [kp])
        signed_bytes = bytes(signed)
        encoded = base64.b64encode(signed_bytes).decode()
        payload = {
            "jsonrpc": "2.0", "id": 1,
            "method": "sendTransaction",
            "params": [encoded, {
                "encoding": "base64",
                "skipPreflight": True,
                "maxRetries": 3,
                "preflightCommitment": "processed"
            }]
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
