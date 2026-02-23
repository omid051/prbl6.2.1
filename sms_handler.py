import requests
import logging

API_KEY = "p7UomXXTMLrv7QFd78-s2CklC4DaBLXeN71YmBPV5P8="
SLOT_PATTERN_CODE = "9eqlqm95666efhe"
ERROR_PATTERN_CODE = "utf0b30juqfindq"
DEFAULT_SENDER = "+983000505"

def send_custom_sms(api_key, recipient, name, type_val, main_val, pattern_code, sms_config):
    if recipient.startswith("98"):
        recipient = "+" + recipient
    elif not recipient.startswith("+") and recipient.startswith("09"):
        recipient = "+98" + recipient[1:]
        
    payload = {
        "pattern_code": pattern_code,
        "originator": DEFAULT_SENDER,
        "recipient": recipient,
        "values": {
            "name": name,
            "type": type_val
        }
    }
    
    # اگر پترن پیامک ارور باشد، متغیر main ارسال می‌شود
    if main_val is not None:
        payload["values"]["main"] = main_val
        
    headers = {
        'Authorization': f'AccessKey {api_key}',
        'Content-Type': 'application/json'
    }
    
    server_type = sms_config.get("server_type", "iran")
    
    try:
        if server_type == "iran":
            url = "http://rest.ippanel.com/v1/messages/patterns/send"
        else:
            # لینک سرور هاست آلمان به صورت هاردکد شده
            url = "https://omidbeheshti.ir/bls/relay_germany.php"

        response = requests.post(url, json=payload, headers=headers, timeout=10)
        response.raise_for_status()
        
        resp_json = response.json()
        logging.info(f"SMS sent successfully to {recipient}. Response: {resp_json}")
        return True, f"ارسال موفق به {recipient}"
            
    except requests.exceptions.RequestException as e:
        error_msg = f"خطا در ارسال پیامک: {e}"
        logging.error(error_msg)
        return False, error_msg

def send_slot_sms(api_key, recipient, visa_subtype, name, sms_config):
    if not sms_config.get("slot_sms_enabled", True):
        return True, "ارسال پیامک اسلات غیرفعال است"
    return send_custom_sms(api_key, recipient, name, visa_subtype, None, SLOT_PATTERN_CODE, sms_config)

def send_error_sms_req(api_key, recipient, visa_type, name, sms_config):
    if not sms_config.get("error_sms_enabled", True):
        return True, "ارسال پیامک ارور غیرفعال است"
    return send_custom_sms(api_key, recipient, name, visa_type, "در سامانه با مشکل", ERROR_PATTERN_CODE, sms_config)