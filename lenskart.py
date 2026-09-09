#!/usr/bin/env python3
"""
Lenskart "Run For Frame" - FAKE DEVICE GENERATOR
Har account ke liye alag device aur unique voucher
"""

import json
import random
import sys
import time
import uuid
import hashlib
import base64
import requests
from datetime import datetime

BASE = "https://api-gateway.juno.lenskart.com"

# Device pools for randomization
BRANDS = ["xiaomi", "realme", "samsung", "oneplus", "oppo", "vivo"]
MODELS = {
    "xiaomi": ["Mi 11X", "Redmi Note 10", "Mi 10", "Poco X3"],
    "realme": ["RMX3031", "RMX3370", "RMX3360", "RMX3263"],
    "samsung": ["SM-G998B", "SM-G991B", "SM-A526B", "SM-M515F"],
    "oneplus": ["LE2115", "LE2125", "KB2001", "IN2015"],
    "oppo": ["CPH2207", "CPH2249", "CPH2217"],
    "vivo": ["V2024", "V2036", "V2041", "V2115"]
}
ANDROID_VERSIONS = ["13", "14"]

class LenskartFakeDevice:
    def __init__(self, phone: str, phone_code: str = "+91"):
        self.phone = phone
        self.phone_code = phone_code
        
        # Generate random device
        self.brand = random.choice(BRANDS)
        self.model = random.choice(MODELS.get(self.brand, ["RMX3031"]))
        self.android_version = random.choice(ANDROID_VERSIONS)
        self.udid = self.generate_udid()
        self.advertising_id = str(uuid.uuid4())
        self.build_version = f"TP1A.220905.00{random.randint(1,9)}"
        
        # Session data
        self.session_token = None
        self.auth_token = None
        self.user_id = None
        self.customer_type = "EXISTING"
        self.s = requests.Session()
        
        # Generate x-assertion from device data
        self.x_assertion = self.generate_x_assertion()
        self.last_response = None
        
    def generate_udid(self):
        return uuid.uuid4().hex[:16]
        
    def generate_x_assertion(self):
        """Generate unique x-assertion for each device"""
        device_data = f"{self.udid}:{self.advertising_id}:{self.brand}:{self.model}:{self.phone}"
        hash_obj = hashlib.sha256(device_data.encode())
        hash_bytes = hash_obj.digest()
        assertion = base64.b64encode(hash_bytes).decode('utf-8')
        assertion = assertion.replace('+', '-').replace('/', '_')
        
        while len(assertion) < 100:
            assertion += random.choice("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")
        
        return assertion[:100]
        
    def base_headers(self, extra: dict = None) -> dict:
        h = {
            "Content-Type": "application/json; charset=UTF-8",
            "api_key": "valyoo123",
            "x-api-client": "android",
            "x-app-version": "5.8.2 (260713001)",
            "appversion": "5.8.2 (260713001)",
            "X-Build-Version": "260713001",
            "x-country-code": "IN",
            "x-country-code-override": "IN",
            "x-accept-language": "en",
            "accept-language": "en",
            "x-customer-type": self.customer_type,
            "udid": self.udid,
            "uniqueId": self.advertising_id[:16],
            "brand": self.brand,
            "model": self.model,
            "x-b3-traceid": str(int(time.time() * 1000)),
            "User-Agent": f"Dalvik/2.1.0 (Linux; U; Android {self.android_version}; {self.model} Build/{self.build_version})",
            "Accept-Encoding": "gzip",
            "Connection": "Keep-Alive",
        }
        
        if self.phone:
            h["x-customer-phone"] = self.phone
            h["x-customer-phone-code"] = self.phone_code.replace("+", "")
            
        if self.session_token:
            h["x-session-token"] = self.session_token
            
        if self.x_assertion:
            h["x-assertion"] = self.x_assertion
            
        if extra:
            h.update(extra)
        return h

    def post(self, path, body=None, params=None):
        headers = self.base_headers()
        url = f"{BASE}{path}"
        if params:
            url += "?" + "&".join([f"{k}={v}" for k, v in params.items()])
        try:
            r = self.s.post(url, headers=headers, json=body, timeout=30)
            self.last_response = r
            return r
        except Exception as e:
            self.last_response = None
            raise e

    def get(self, path, params=None):
        headers = self.base_headers()
        url = f"{BASE}{path}"
        if params:
            url += "?" + "&".join([f"{k}={v}" for k, v in params.items()])
        try:
            r = self.s.get(url, headers=headers, timeout=30)
            self.last_response = r
            return r
        except Exception as e:
            self.last_response = None
            raise e

    def create_session(self):
        try:
            r = self.post("/v2/sessions", {})
            if r.status_code == 200:
                data = r.json()
                self.session_token = data.get("result", {}).get("id")
                return True
            return False
        except:
            return False

    def send_otp(self):
        if not self.session_token:
            return None
        try:
            body = {"phoneCode": self.phone_code, "telephone": self.phone}
            r = self.post("/v3/customers/sendOtp", body)
            if r.status_code == 200:
                data = r.json()
                res = data.get("result") or {}
                self.customer_type = "NEW" if res.get("isNewUser") else "EXISTING"
                return res
            return None
        except:
            return None

    def verify_otp(self, code: str):
        try:
            body = {"code": code, "phoneCode": self.phone_code, "telephone": self.phone}
            r = self.post("/v2/customers/authenticate/mobile", body)
            if r.status_code == 200:
                data = r.json()
                res = data.get("result") or {}
                self.auth_token = res.get("token")
                self.user_id = res.get("user_id")
                
                if self.auth_token:
                    self.session_token = self.auth_token
                    return res
            return None
        except:
            return None

    def me(self):
        try:
            r = self.get("/v2/customers/me")
            if r.status_code == 200:
                data = r.json()
                result = data.get("result", {})
                self.user_id = result.get("id")
                return data
            return None
        except:
            return None

    def build_steps_payload(self, steps: int = 30000):
        DAY_MS = 86400000
        ist_offset_ms = 5.5 * 3600 * 1000
        
        now_utc_ms = int(time.time() * 1000)
        now_ist_ms = now_utc_ms + ist_offset_ms
        today_midnight_ist = (now_ist_ms // DAY_MS) * DAY_MS
        today_midnight_utc = today_midnight_ist - ist_offset_ms
        
        step_counts = [0, 0, 0, 0, 0, 0, steps]
        
        payload = []
        for i in range(6, -1, -1):
            ts = today_midnight_utc - i * DAY_MS
            payload.append({
                "distance": 0.0,
                "steps": step_counts[i],
                "timestamp": int(ts)
            })
        return payload

    def claim_reward(self, steps: int = 30000):
        try:
            body = self.build_steps_payload(steps)
            params = {"campaignName": "run-for-frame"}
            
            r = self.post("/v2/customers/bff/campaign/eligibility", body, params)
            
            try:
                data = r.json()
            except:
                data = {"raw": r.text[:500]}
            
            if r.status_code == 200:
                res = data.get("result") or {}
                if res.get("giftVoucher"):
                    # Save reward to file
                    filename = f"reward_{self.phone}.json"
                    with open(filename, "w") as f:
                        json.dump(data, f, indent=2)
                    return {
                        "success": True,
                        "tier": res.get("tier"),
                        "giftVoucher": res.get("giftVoucher"),
                        "steps": res.get("steps"),
                        "expiry": res.get("giftVoucherExpiryDate"),
                        "message": res.get("message", "Reward claimed successfully!")
                    }
                else:
                    return {
                        "success": False,
                        "message": res.get("message", "No reward available"),
                        "code": r.status_code
                    }
            else:
                return {
                    "success": False,
                    "message": f"API Error: {r.status_code}",
                    "response": data
                }
        except Exception as e:
            return {
                "success": False,
                "message": f"Exception: {str(e)}"
            }

    def check_vouchers(self):
        try:
            r = self.get("/v2/customers/me/giftVoucher", params={"campaignName": "run-for-frame"})
            if r.status_code == 200:
                return r.json()
            return None
        except:
            return None


def main():
    print("="*60)
    print("🏃 LENSKART - FAKE DEVICE GENERATOR")
    print("🔑 Har account ke liye alag device")
    print("="*60)
    
    phones = []
    print("\n📱 Enter phone numbers (one per line, press Enter twice to finish):")
    while True:
        phone = input("> ").strip()
        if not phone:
            break
        phones.append(phone)
    
    if not phones:
        print("❌ No phone numbers entered!")
        return
    
    print(f"\n✅ Found {len(phones)} numbers")
    
    results = []
    for i, phone in enumerate(phones, 1):
        print(f"\n{'='*60}")
        print(f"📱 [{i}/{len(phones)}] Processing: {phone}")
        print(f"{'='*60}")
        
        device = LenskartFakeDevice(phone)
        
        if not device.create_session():
            results.append({"phone": phone, "status": "❌ Session failed"})
            continue
        
        device.send_otp()
        otp = input(f"🔑 Enter OTP for {phone}: ").strip()
        if not device.verify_otp(otp):
            results.append({"phone": phone, "status": "❌ OTP failed"})
            continue
        
        device.me()
        result = device.claim_reward(steps=30000)
        
        if result.get("success"):
            print(f"\n🎉 REWARD UNLOCKED for {phone}!")
            print(f"   🏆 Tier: {result.get('tier')}")
            print(f"   🎫 Voucher: {result.get('giftVoucher')}")
            print(f"   📊 Steps: {result.get('steps')}")
            results.append({
                "phone": phone,
                "status": "✅ Success",
                "voucher": result.get('giftVoucher'),
                "user_id": device.user_id,
                "device": f"{device.brand} {device.model}"
            })
        else:
            print(f"\n❌ Failed: {result.get('message')}")
            results.append({
                "phone": phone,
                "status": f"❌ Failed: {result.get('message', 'Unknown error')}",
                "user_id": device.user_id,
                "device": f"{device.brand} {device.model}"
            })
        
        device.check_vouchers()
    
    print("\n" + "="*60)
    print("📊 SUMMARY")
    print("="*60)
    for r in results:
        print(f"   {r['status']} {r['phone']} ({r.get('device', 'N/A')})")
    print("="*60)


if __name__ == "__main__":
    main()
