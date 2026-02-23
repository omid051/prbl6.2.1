import time
import logging
import traceback
import random
import undetected_chromedriver as uc
import os
import datetime
import requests
import unicodedata
import threading
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from captcha_solver import solve_captcha
from logger import logger
from sms_handler import send_slot_sms, API_KEY

CHROMEDRIVER_PATH = os.path.abspath("chromedriver.exe")
OTP_URL = "https://omidbeheshti.ir/bls/visa_codes.json"

def normalize_text(text):
    if not text: return ""
    return ''.join(c for c in unicodedata.normalize('NFD', text) if unicodedata.category(c) != 'Mn').lower()

class VisaBotWorker:
    def __init__(self, account, config, global_lock, log_file, status_callback=None):
        self.account = account
        self.config = config
        self.min_interval = config.get("min_interval", 30) * 60
        self.max_interval = config.get("max_interval", 60) * 60
        self.running = True
        self.log_file = log_file
        self.global_lock = global_lock
        self.status_callback = status_callback
        self.driver = None
        self.keep_driver_open = False 
        self.driver_start_time = 0

    def notify_status(self, msg, next_check=None):
        if self.status_callback:
            timestamp = datetime.datetime.now().strftime("%H:%M:%S")
            full_msg = f"{msg} (at {timestamp})"
            self.status_callback(self.account.get('id', self.account['email']), full_msg, str(next_check) if next_check else "")

    def stop(self):
        self.running = False
        if self.driver:
            try: self.driver.quit()
            except: pass
            self.driver = None

    def run(self):
        logger.info(f"Worker started for {self.account['email']}")
        self.notify_status("Started")
        
        while self.running:
            try:
                if self.config.get("sleep_mode", False):
                    now = datetime.datetime.now()
                    if 3 <= now.hour < 7:
                        self.notify_status("Sleep Mode (03-07 AM)")
                        time.sleep(60)
                        continue

                self.notify_status("Waiting for execution lock...")
                with self.global_lock:
                    if not self.running: break
                    self.notify_status("Checking...")
                    logger.info(f"Lock acquired. Checking slot for {self.account['email']}")
                    self.check_slot()
                
                if not self.running: break

            except Exception as e:
                logger.error(f"CRITICAL WORKER ERROR: {e}\n{traceback.format_exc()}")
                self.notify_status("Error: Crash - Restarting...")
                time.sleep(5)
                continue 
            
            if not self.running: break
            
            sleep_seconds = self.calculate_next_sleep()
            next_time = (datetime.datetime.now() + datetime.timedelta(seconds=sleep_seconds)).strftime("%H:%M:%S")
            self.notify_status("Sleeping", next_check=next_time)
            logger.info(f"Sleeping for {sleep_seconds} seconds...")
            
            slept = 0
            while slept < sleep_seconds and self.running:
                time.sleep(1)
                slept += 1

    def calculate_next_sleep(self):
        base_sleep = random.randint(self.min_interval, self.max_interval)
        
        now = datetime.datetime.now()
        target_times = []
        special_hours = list(range(24))

        if self.config.get("special_times", False):
            for h in special_hours:
                t = now.replace(hour=h, minute=58, second=0, microsecond=0)
                if t > now: target_times.append(t)

        if self.config.get("half_hour_times", False):
            for h in special_hours:
                t = now.replace(hour=h, minute=28, second=0, microsecond=0)
                if t > now: target_times.append(t)

        if target_times:
            nearest_special = min(target_times, key=lambda x: x - now)
            next_wake_base = now + datetime.timedelta(seconds=base_sleep)
            
            if next_wake_base > nearest_special:
                seconds_until_special = (nearest_special - now).total_seconds()
                return int(seconds_until_special)

        return base_sleep

    def get_profile_path(self):
        safe_email = self.account['email'].replace("@", "_at_").replace(".", "_dot_")
        profile_dir = os.path.join(os.getcwd(), "profiles", safe_email)
        if not os.path.exists(profile_dir): os.makedirs(profile_dir)
        return profile_dir

    def is_unavailable_page(self, driver):
        try:
            if "Application Temporarily Unavailable" in driver.find_element(By.TAG_NAME, "body").text: return True
        except: pass
        return False

    def check_and_refresh_if_unavailable(self, driver, step_name):
        if self.is_unavailable_page(driver):
            logger.warning(f"'{step_name}' unavailable. Refreshing...")
            driver.refresh()
            time.sleep(5)
            return True
        return False

    def safe_fill_input(self, driver, element_id, text):
        try:
            el = driver.find_element(By.ID, element_id)
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", el)
            time.sleep(0.1)
            try:
                el.clear()
                el.click()
                el.send_keys(text)
            except:
                driver.execute_script("arguments[0].value = arguments[1];", el, text)
                driver.execute_script("arguments[0].dispatchEvent(new Event('change'));", el)
        except Exception as e:
            logger.error(f"Failed to fill {element_id}: {e}")

    def handle_disclaimer_popup(self, driver):
        logger.info("Looking for Disclaimer Popup...")
        time.sleep(0.5)
        try:
            btn_specific = driver.find_elements(By.XPATH, "//button[contains(@onclick, 'onDisclaimarClose')]")
            for b in btn_specific:
                if b.is_displayed():
                    driver.execute_script("arguments[0].click();", b)
                    logger.info("Clicked Disclaimer (onDisclaimarClose).")
                    time.sleep(0.2)
                    return
            btn_generic = driver.find_elements(By.XPATH, "//button[contains(@class,'btn-success') and (text()='Ok' or text()='OK')]")
            for b in btn_generic:
                if b.is_displayed():
                    driver.execute_script("arguments[0].click();", b)
                    logger.info("Clicked Disclaimer (Generic OK).")
                    time.sleep(0.2)
                    return
        except Exception as e:
            logger.warning(f"Disclaimer handling error: {e}")

    def check_loading_overlay(self, driver, timeout=7):
        try:
            try:
                WebDriverWait(driver, 2).until(
                    EC.visibility_of_element_located((By.CSS_SELECTOR, "#global-overlay .global-overlay-loader"))
                )
                logger.info("Loading overlay detected. Waiting...")
            except:
                return

            start_wait = time.time()
            WebDriverWait(driver, timeout).until(
                EC.invisibility_of_element_located((By.CSS_SELECTOR, "#global-overlay .global-overlay-loader"))
            )
            logger.info(f"Loading finished in {time.time() - start_wait:.2f}s.")
            
        except Exception:
            logger.error("Loading overlay stuck for > 7 seconds!")
            raise Exception("LOADING_STUCK_7S")

    def check_slot(self):
        error_strategy = self.config.get("error_strategy", "retry")
        check_mode = self.config.get("check_mode", "reopen")
        restart_interval = self.config.get("browser_restart_minutes", 60) * 60

        need_login = False
        if self.driver is None:
            need_login = True
        elif check_mode == "keep_alive" and (time.time() - self.driver_start_time > restart_interval):
            logger.info("Browser restart interval reached. Quitting old driver to refresh session.")
            try: self.driver.quit()
            except: pass
            self.driver = None
            need_login = True

        try:
            if need_login:
                self.keep_driver_open = False
                options = uc.ChromeOptions()
                prefs = {
                    "credentials_enable_service": False,
                    "profile.password_manager_enabled": False,
                    "profile.default_content_setting_values.automatic_downloads": 1,
                    "profile.default_content_setting_values.notifications": 2
                }
                options.add_experimental_option("prefs", prefs)
                options.add_argument(f'--user-data-dir={self.get_profile_path()}')
                options.add_argument("--no-first-run")
                options.add_argument("--disable-blink-features=AutomationControlled")
                options.add_argument("--disable-extensions")
                options.add_argument("--disable-infobars")
                
                self.driver = uc.Chrome(options=options, driver_executable_path=CHROMEDRIVER_PATH)
                driver = self.driver
                self.driver_start_time = time.time()

                try:
                    driver.minimize_window()
                    time.sleep(0.5)
                    driver.maximize_window()
                    driver.switch_to.window(driver.current_window_handle)
                except Exception: driver.maximize_window()

                wait = WebDriverWait(driver, 30)
                driver.get("https://iran.blsspainglobal.com/Global/account/login")
                
                for _ in range(3):
                    if self.check_and_refresh_if_unavailable(driver, "Login Page"): continue
                    break

                email_input = self.find_input(driver, "UserId")
                self.human_type(driver, email_input, self.account['email'])
                pwd_input = self.find_input(driver, "Password")
                self.human_type(driver, pwd_input, self.account['password'])
                
                verify_btn = wait.until(EC.element_to_be_clickable((By.ID, "btnVerify")))
                ActionChains(driver).move_to_element(verify_btn).click().perform()
                time.sleep(1) 
                
                if not self.robust_solve_captcha(driver, max_tries=5):
                    logger.error("Login captcha failed/unavailable. Restarting.")
                    self.notify_status("Captcha Failed")
                    return

                time.sleep(0.5)
                login_btn = wait.until(EC.element_to_be_clickable((By.ID, "btnSubmit")))
                ActionChains(driver).move_to_element(login_btn).click().perform()
                time.sleep(3) 

            else:
                driver = self.driver
                wait = WebDriverWait(driver, 30)
                driver.switch_to.default_content()

            driver.get("https://iran.blsspainglobal.com/Global/blsappointment/manageappointment")
            
            appointment_success = False
            for retry_attempt in range(3):
                try:
                    logger.info(f"Appointment Step Attempt {retry_attempt + 1}/3")
                    
                    if retry_attempt > 0:
                        logger.info("Refreshing page for retry...")
                        driver.refresh()
                        time.sleep(3)

                    for _ in range(3):
                        if self.check_and_refresh_if_unavailable(driver, "Appointment Page"): continue
                        break

                    verify_btn2 = wait.until(EC.element_to_be_clickable((By.ID, "btnVerify")))
                    driver.execute_script("arguments[0].click();", verify_btn2)
                    time.sleep(0.5) 

                    if not self.robust_solve_captcha(driver, max_tries=3):
                        raise Exception("Appointment captcha failed.")

                    time.sleep(0.5)
                    submit_btn2 = wait.until(EC.element_to_be_clickable((By.ID, "btnSubmit")))
                    driver.execute_script("arguments[0].click();", submit_btn2)
                    time.sleep(1) 

                    self.handle_disclaimer_popup(driver)
                    self.fill_visa_form(driver)
                    
                    btn = self.find_by_text(driver, "button", "Submit")
                    if btn:
                        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
                        time.sleep(0.5)
                        
                        now = datetime.datetime.now()
                        wait_seconds = 0
                        
                        if self.config.get("special_times", False) and now.minute >= 55:
                            target_time = (now + datetime.timedelta(hours=1)).replace(minute=0, second=10, microsecond=0)
                            wait_seconds = (target_time - now).total_seconds()
                        
                        elif self.config.get("half_hour_times", False) and 25 <= now.minute < 35:
                            target_time = now.replace(minute=30, second=10, microsecond=0)
                            wait_seconds = (target_time - now).total_seconds()

                        if wait_seconds > 0:
                            logger.info(f"Target Time Wait: Waiting {wait_seconds:.2f} seconds...")
                            self.notify_status(f"Waiting for {target_time.strftime('%H:%M:%S')}")
                            time.sleep(wait_seconds)

                        driver.execute_script("arguments[0].click();", btn)
                        time.sleep(0.5)
                    
                    appointment_success = True
                    break

                except Exception as e:
                    if str(e) == "LOADING_STUCK_7S":
                        raise e
                    logger.warning(f"Error in Appointment form (Attempt {retry_attempt+1}): {e}")
                    self.notify_status(f"Form Error: {e} - Retrying...")
                    time.sleep(2)
            
            if not appointment_success:
                raise Exception("Failed to process Appointment Form after 3 retries.")

            slot_modal_found = False
            for _ in range(15): 
                try:
                    headers = driver.find_elements(By.XPATH, "//span[contains(text(),'Visa Submission Address')]")
                    if headers and headers[0].is_displayed():
                        slot_modal_found = True
                        break 
                    
                    ok_btns = driver.find_elements(By.XPATH, "//button[contains(@class,'btn-success') and (text()='Ok' or text()='OK')]")
                    for ob in ok_btns:
                        if ob.is_displayed():
                            onclick_attr = ob.get_attribute("onclick")
                            if onclick_attr and "OnAddressModalClose" in onclick_attr:
                                slot_modal_found = True
                                break
                            else:
                                logger.info("Clicking informational OK button.")
                                driver.execute_script("arguments[0].click();", ob)
                                time.sleep(0.4)
                    if slot_modal_found: break
                except: pass
                time.sleep(0.5)

            if slot_modal_found:
                logger.info("!!! SLOT MODAL DETECTED !!!")
                self.notify_status("SLOT FOUND - PROCEEDING...")
                
                if error_strategy == "manual":
                    self.keep_driver_open = True 
                    self.running = False 
                
                try:
                    ok_btn = driver.find_element(By.XPATH, "//button[contains(@onclick, 'OnAddressModalClose')]")
                    driver.execute_script("arguments[0].click();", ok_btn)
                    logger.info("Clicked Address Modal OK.")
                    time.sleep(0.5) 
                    
                    self.perform_booking(driver)
                    self.running = False 
                except Exception as ex:
                    if str(ex) == "NO_VALID_DATE_LEGALIZATION":
                        logger.info("No matching date found for Legalization preferences. Resuming check...")
                        self.notify_status("Date Mismatch - Skipping & Retrying")
                        self.running = True 
                        self.keep_driver_open = False
                    else:
                        logger.error(f"Booking Process Error: {ex}\n{traceback.format_exc()}")
                        if error_strategy == "manual":
                            self.notify_status("Error in Booking - Manual Help Needed")
                        else:
                            self.notify_status("Error Booking")
            else:
                logger.info("No slot found (Modal not seen).")
                self.notify_status("Slot Not Found")

            time.sleep(0.5)

        except Exception as e:
            logger.error(f"Check Error: {e}\n{traceback.format_exc()}")
            # بستن مرورگر در صورت وجود ارور برای جلوگیری از گیر کردن در سشن خراب
            if self.driver and not self.keep_driver_open:
                try: self.driver.quit()
                except: pass
                self.driver = None

            if error_strategy == "manual":
                self.notify_status("Error Detected - Waiting for Manual Action")
                self.keep_driver_open = True
                self.running = False 
            else:
                self.notify_status("Error during check - Restarting...")
                raise e 
        finally:
            if not self.running or check_mode == "reopen":
                if self.driver and not self.keep_driver_open: 
                    try: self.driver.quit()
                    except: pass
                    self.driver = None

    def find_active_date_slot_ids(self, driver):
        for i in range(1, 6):
            date_id = f"AppointmentDate{i}"
            slot_id = f"AppointmentSlot{i}"
            try:
                inp = driver.find_element(By.ID, date_id)
                parent = inp.find_element(By.XPATH, "./..")
                if inp.is_displayed() or parent.is_displayed():
                    logger.info(f"Detected active fields: {date_id} and {slot_id}")
                    return date_id, slot_id
            except: continue
        return "AppointmentDate1", "AppointmentSlot1"

    def perform_booking(self, driver):
        wait = WebDriverWait(driver, 30)
        date_id, slot_id = self.find_active_date_slot_ids(driver)
        
        failed_attempts_keys = [] 
        max_retries = 4
        current_retry = 0
        
        while current_retry <= max_retries:
            logger.info(f"Booking Try: {current_retry + 1}")
            
            logger.info(f"Selecting Date ({date_id})...")
            date_input = driver.find_element(By.ID, date_id)
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", date_input)
            time.sleep(0.2)
            driver.execute_script(f"$('#{date_id}').data('kendoDatePicker').open();")
            time.sleep(0.3) 
            
            available_days = driver.find_elements(By.CSS_SELECTOR, "table.k-content tbody td:not(.k-state-disabled) a.k-link")
            if not available_days: raise Exception("No available date found in calendar.")
            
            day_texts = [d.text.strip() for d in available_days]
            logger.info(f"روزهای موجود باز شده در سامانه: {', '.join(day_texts)}")
            
            selected_day_element = None
            is_legalization = "legalization" in self.account.get('visa_type', '').lower()
            
            if current_retry > 0 and len(available_days) > 1:
                selected_day_element = random.choice(available_days)
                logger.info(f"Retry: Picked random day {selected_day_element.text}")
            elif is_legalization:
                target_str = self.account.get('target_days', '')
                targets = [x.strip() for x in target_str.split(',') if x.strip().isdigit()]
                if not targets:
                    selected_day_element = available_days[0]
                else:
                    valid_choices = [d for d in available_days if d.text.strip() in targets]
                    if not valid_choices: raise Exception("NO_VALID_DATE_LEGALIZATION")
                    selected_day_element = valid_choices[0]
            else:
                pref = self.account.get('date_pref', 'Earliest')
                if "Latest" in pref: selected_day_element = available_days[-1]
                elif "Random" in pref: selected_day_element = random.choice(available_days)
                else: selected_day_element = available_days[0]

            selected_date_text = selected_day_element.text.strip()
            driver.execute_script("arguments[0].click();", selected_day_element)
            logger.info(f"روز انتخاب شده برای رزرو: {selected_date_text}")
            time.sleep(0.5)

            if current_retry == 0:
                recipients = self.config.get("recipients", [])
                sms_config = {
                    "slot_sms_enabled": self.config.get("slot_sms_enabled", True),
                    "server_type": self.config.get("sms_server_type", "iran"),
                }
                
                # ارسال پیامک در ترد مجزا برای جلوگیری از اتلاف وقت در حین رزرو
                def send_sms_async(user_data):
                    name = user_data.get("name", "کاربر")
                    number = user_data.get("number", "")
                    if number:
                        try:
                            send_slot_sms(API_KEY, number, self.account['visa_subtype'], name, sms_config)
                        except: pass
                        
                for user in recipients:
                    threading.Thread(target=send_sms_async, args=(user,), daemon=True).start()

            logger.info(f"Selecting Time ({slot_id})...")
            slot_input = driver.find_element(By.ID, slot_id)
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", slot_input)
            time.sleep(0.5)
            driver.execute_script(f"$('#{slot_id}').data('kendoDropDownList').open();")
            time.sleep(0.3) 
            listbox_id = f"{slot_id}_listbox"
            success_slots = driver.find_elements(By.XPATH, f"//ul[@id='{listbox_id}']//li//div[contains(@class,'bg-success')]")
            if not success_slots: raise Exception("No available time slots (bg-success) found.")
            
            target_slot = None
            try:
                slot_index = -1 - current_retry
                if abs(slot_index) > len(success_slots):
                     slot_index = -1 
                target_slot = success_slots[slot_index]
                logger.info(f"Attempt {current_retry+1}: Selected slot at index {slot_index}")
            except Exception as e:
                target_slot = success_slots[-1]

            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", target_slot)
            time.sleep(0.3)
            driver.execute_script("arguments[0].click();", target_slot)
            logger.info("Time selected.")
            time.sleep(0.3)

            if current_retry == 0:
                logger.info("Requesting OTP...")
                req_btn = driver.find_element(By.ID, "btnSenderificationCode")
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", req_btn)
                time.sleep(0.1) 
                
                try: driver.execute_script("arguments[0].click();", req_btn)
                except: ActionChains(driver).move_to_element(req_btn).click().perform()
                
                try:
                    WebDriverWait(driver, 5).until(EC.visibility_of_element_located((By.XPATH, "//div[contains(@class,'modal-content')]//h6[contains(text(),'OTP Sent')]")))
                    otp_ok_btn = driver.find_element(By.XPATH, "//button[contains(text(),'Ok') and @data-bs-dismiss='modal']")
                    driver.execute_script("arguments[0].click();", otp_ok_btn)
                except: self.try_click_ok_popup(driver, timeout=3)

                logger.info("Waiting 0.5s before fetching OTP...") 
                time.sleep(0.5)
                otp_verified = False
                for attempt in range(2):
                    otp_code = self.fetch_otp_from_server(self.account['email'])
                    if not otp_code:
                        if attempt < 1: time.sleep(1.5); continue
                        else: raise Exception("Could not retrieve OTP from server.")

                    otp_input = driver.find_element(By.ID, "EmailVerificationCode")
                    try: otp_input.clear()
                    except: pass
                    self.human_type(driver, otp_input, otp_code)
                    
                    verify_email_btn = driver.find_element(By.ID, "btnVerifyEmail")
                    driver.execute_script("arguments[0].click();", verify_email_btn)
                    time.sleep(0.5) 
                    
                    try:
                        error_msg = driver.find_element(By.CSS_SELECTOR, "div.validation-summary.alert-danger")
                        if error_msg.is_displayed() and "Invalid email verification code" in error_msg.text:
                            if attempt < 1: time.sleep(1); continue
                            else: raise Exception("Invalid OTP Code provided 2 times.")
                    except: pass
                    otp_verified = True
                    break
                
                if not otp_verified: raise Exception("OTP Verification failed.")

                logger.info("Handling Photo Upload...")
                js_replace_btn = """
                var btn = document.getElementById('btnOpenCamera');
                if (btn) {
                    var newBtn = btn.cloneNode(true);
                    newBtn.id = 'btnOpenCamera_Modified';
                    newBtn.setAttribute('onclick', "document.getElementById('uploadfile-1').click()");
                    newBtn.innerText = 'Capture';
                    btn.parentNode.replaceChild(newBtn, btn);
                }
                """
                driver.execute_script(js_replace_btn)
                time.sleep(0.3)

                photo_dir = os.path.join(os.getcwd(), "photos")
                if not os.path.exists(photo_dir): os.makedirs(photo_dir)
                photo_path = None
                for ext in [".jpg", ".jpeg", ".png"]:
                    p = os.path.join(photo_dir, f"{self.account['email']}{ext}")
                    if os.path.exists(p):
                        photo_path = p
                        break
                if not photo_path: raise Exception(f"Photo not found for {self.account['email']} in photos/ directory.")
                
                file_input = driver.find_element(By.ID, "uploadfile-1")
                driver.execute_script("arguments[0].style.display = 'block';", file_input)
                file_input.send_keys(photo_path)
                time.sleep(1)
                try:
                    understood_btn = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.XPATH, "//button[contains(@onclick, 'OnPhotoAccepted')]")))
                    driver.execute_script("arguments[0].click();", understood_btn)
                except: pass
                time.sleep(0.3)

                logger.info("Verifying Appointment...")
                verify_app_btn = driver.find_element(By.ID, "btnVerifyAppointment")
                driver.execute_script("arguments[0].click();", verify_app_btn)
                time.sleep(0.5)

                logger.info("Solving Final Captcha...")
                if not self.robust_solve_captcha(driver, max_tries=5): raise Exception("Final Captcha Failed.")

            logger.info("Submitting Appointment (Step 1)...")
            submit_final_btn = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.ID, "btnSubmit")))
            driver.execute_script("arguments[0].click();", submit_final_btn)
            
            time.sleep(1) 

            try:
                valid_summary = driver.find_element(By.CSS_SELECTOR, "div.validation-summary")
                if valid_summary.is_displayed():
                    error_text = valid_summary.text.lower()
                    
                    if "expired captcha" in error_text or "invalid captcha" in error_text:
                        logger.error("Error: Invalid/Expired Captcha.")
                        raise Exception("Captcha Invalid/Expired - Restarting...")
                    
                    if "not valid" in error_text and "appointment date and slot" in error_text:
                        logger.warning(f"Slot {selected_date_text} invalid (taken). Retrying with next available slot...")
                        current_retry += 1
                        continue 
            except Exception as e:
                if "Captcha Invalid" in str(e): raise e
                pass

            logger.info("APPOINTMENT STEP 1 SUBMITTED SUCCESS!")
            break

        if current_retry > max_retries:
            raise Exception("Max retries reached for invalid slots.")

        self.handle_post_booking(driver)

    def handle_post_booking(self, driver):
        wait = WebDriverWait(driver, 15)
        logger.info("Entering Post-Booking Step (Consent & Details)...")
        time.sleep(2) 

        try:
            consent_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(@onclick,'onAgree()')]")))
            
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", consent_btn)
            time.sleep(0.5)
            
            driver.execute_script("arguments[0].click();", consent_btn)
            logger.info("Consent Agreed.")
            
            time.sleep(1)
        except Exception as e: 
            logger.warning(f"Could not find/click Consent button: {e}")

        last_name_val = self.account.get('last_name', '')
        if not last_name_val: 
            last_name_val = "N/A"
        self.safe_fill_input(driver, "LastName_0", last_name_val)

        if "legalization" in self.account.get('visa_type', '').lower():
            logger.info("Processing Legalization details...")
            reason_val = self.account.get('reason', 'Legalization Request')
            self.safe_fill_input(driver, "Reason_0", reason_val)
            
            docs = self.account.get('documents', [])
            if not docs: docs = [{"type": "OTRO", "count": 1}] 

            for i, doc_item in enumerate(docs):
                suffix = str(i + 1)
                d_type = doc_item.get('type', '')
                d_count = int(doc_item.get('count', 1))

                if i > 0:
                    try:
                        add_btn = driver.find_element(By.ID, "addDocBtn")
                        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", add_btn)
                        time.sleep(0.3)
                        driver.execute_script("arguments[0].click();", add_btn)
                        time.sleep(0.5)
                    except: pass

                dropdown_input_id = f"docType_{suffix}"
                try:
                    inp = driver.find_element(By.ID, dropdown_input_id)
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center', inline: 'nearest'});", inp)
                    time.sleep(0.2) 
                    driver.execute_script(f"$('#{dropdown_input_id}').data('kendoDropDownList').open();")
                    time.sleep(0.3)
                    
                    listbox_id = f"{dropdown_input_id}_listbox"
                    ul = driver.find_element(By.ID, listbox_id)
                    items = ul.find_elements(By.TAG_NAME, "li")
                    normalized_target = normalize_text(d_type)
                    
                    for item in items:
                        if normalized_target in normalize_text(item.text):
                            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", item)
                            time.sleep(0.1)
                            driver.execute_script("arguments[0].click();", item)
                            break

                except Exception as e: logger.error(f"Error selecting document {d_type}: {e}")

                if d_count > 1:
                    count_input_id = f"docCount_{suffix}"
                    try:
                        driver.execute_script(f"$('#{count_input_id}').data('kendoNumericTextBox').value({d_count});")
                    except: pass
                time.sleep(0.2)

        logger.info("Clicking Final Submit...")
        try:
            # جستجو و کلیک سریع جاوا اسکریپتی به جای متد کندتر ActionChains
            final_submit = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, "//button[@type='submit' and contains(@class,'btn-primary')]"))
            )
            driver.execute_script("arguments[0].click();", final_submit)
            logger.info("Clicked Final Submit (JS).")
        except Exception as e:
            logger.error(f"Error clicking Final Submit: {e}")
            try:
                btn = driver.find_element(By.XPATH, "//button[contains(@onclick,'OnApplicationSubmit')]")
                driver.execute_script("arguments[0].click();", btn)
            except: pass

        logger.info("Waiting 3s for response...")
        time.sleep(3)
        shot_name = f"result_{self.account['email']}_{int(time.time())}.png"
        driver.save_screenshot(shot_name)
        logger.info(f"Screenshot saved: {shot_name}")

        final_status = "Success"
        try:
            error_msg = driver.find_element(By.CSS_SELECTOR, "div.validation-summary")
            if error_msg.is_displayed():
                text = error_msg.text.lower()
                if "195 per day" in text: final_status = "Error 195 (Limit Reached)"
                else: final_status = f"Error: {text[:30]}"
        except: pass
        self.notify_status(f"DONE: {final_status}")

    def fetch_otp_from_server(self, email):
        target_email = email.lower().strip()
        try:
            r = requests.get(OTP_URL, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
            if r.status_code == 200:
                data = r.json()
                for k, v in data.items():
                    if k.lower().strip() == target_email:
                        if isinstance(v, dict):
                            code = str(v.get('code', '')).strip()
                            if code: return code
                        else:
                            code = str(v).strip()
                            if code: return code
        except Exception as e: logger.warning(f"Error fetching OTP: {e}")
        return None

    def try_click_ok_popup(self, driver, timeout=6):
        end_time = time.time() + timeout
        while time.time() < end_time:
            try:
                ok_btn = driver.find_element(By.XPATH, "//button[contains(@class,'btn-success') and (text()='Ok' or text()='OK')]")
                if ok_btn.is_displayed():
                    driver.execute_script("arguments[0].click();", ok_btn)
                    return True
            except: pass
            time.sleep(0.5)
        return False

    def try_click_invalid_selection(self, driver, timeout=6):
        for _ in range(timeout*2):
            try:
                ok_btn = driver.find_element(By.XPATH, "//button[contains(@class,'btn-success') and (text()='Ok' or text()='OK')]")
                if ok_btn.is_displayed():
                    msg_els = driver.find_elements(By.XPATH, "//*[contains(text(),'Invalid selection')]")
                    if msg_els:
                        driver.execute_script("arguments[0].click();", ok_btn)
                        return True
            except: pass
            time.sleep(0.5)
        return False

    def robust_solve_captcha(self, driver, max_tries=5):
        for attempt in range(1, max_tries+1):
            time.sleep(0.5) 
            try:
                loading_start = time.time()
                while time.time() - loading_start < 10:
                    try:
                        loader = driver.find_element(By.CSS_SELECTOR, ".k-loading-mask")
                        if loader.is_displayed():
                            time.sleep(0.5)
                            continue
                        else: break 
                    except: break 
            except: pass

            if not self.is_captcha_still_present(driver):
                return True

            try:
                try:
                    iframe = driver.find_element(By.CSS_SELECTOR, "iframe.k-content-frame")
                    driver.switch_to.frame(iframe)
                    body_text = driver.find_element(By.TAG_NAME, "body").text
                    if "Application Temporarily Unavailable" in body_text:
                        driver.switch_to.default_content()
                        driver.refresh()
                        time.sleep(3)
                        return False 
                    driver.switch_to.default_content()
                except: driver.switch_to.default_content()

                solve_captcha(driver)
                time.sleep(0.5)
                if self.is_captcha_invalid(driver):
                    self.try_click_invalid_selection(driver)
                    continue
                if self.is_captcha_still_present(driver):
                    continue
                return True
            except Exception as e: logger.error(f"Captcha error {attempt}: {e}")
        return False

    def is_captcha_invalid(self, driver):
        try:
            msgs = driver.find_elements(By.XPATH, "//*[contains(text(),'Invalid selection')]")
            return any(m.is_displayed() for m in msgs)
        except: return False

    def is_captcha_still_present(self, driver):
        try:
            iframes = driver.find_elements(By.CSS_SELECTOR, "iframe.k-content-frame")
            return bool(iframes)
        except: return False

    def find_input(self, driver, base_id):
        for elem in driver.find_elements(By.XPATH, f"//input[starts-with(@id, '{base_id}')]"):
            if elem.is_displayed(): return elem
        raise Exception(f"Input {base_id} not found")

    def human_type(self, driver, element, text):
        element.click()
        for ch in text:
            ActionChains(driver).send_keys(ch).perform()
            time.sleep(0.05)

    def find_by_text(self, driver, tag, text):
        elems = driver.find_elements(By.TAG_NAME, tag)
        for e in elems:
            if text.lower() in e.text.lower() and e.is_displayed(): return e
        return None

    def fill_visa_form(self, driver):
        selects = driver.find_elements(By.XPATH, "//input[@data-role='dropdownlist']")
        for s in selects:
            time.sleep(0.2) 
            try: driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", s)
            except: pass

            parent = s.find_element(By.XPATH, "./..")
            label = ""
            try: label = parent.find_element(By.XPATH, ".//label").text.strip().lower()
            except:
                try: label = parent.find_element(By.XPATH, "../label").text.strip().lower()
                except: continue
                
            if "jurisdiction" in label or "location" in label:
                self.select_kendo_dropdown(driver, s, "Tehran")
                self.check_loading_overlay(driver, timeout=7)
                
            elif "visa type" in label:
                self.select_kendo_dropdown(driver, s, self.account['visa_type'])
                time.sleep(0.2)
            elif "visa sub type" in label:
                self.select_kendo_dropdown(driver, s, self.account['visa_subtype'])
                
                subtype = self.account['visa_subtype'].strip().lower()
                if ("ley" in subtype) or ("work" in subtype):
                    time.sleep(0.2) 
                    self.wait_and_click_ley_work_ok(driver)
            elif "appointment category" in label:
                self.select_kendo_dropdown(driver, s, self.account['category'])
            elif "appointment for" in label:
                if self.account['for_type'].strip().lower() == "family":
                    radios = driver.find_elements(By.XPATH, "//input[@type='radio']")
                    for r in radios:
                        val = r.get_attribute("value")
                        if val and val.lower() == "family" and r.is_enabled():
                            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", r)
                            time.sleep(0.2)
                            r.click()
                            break
        time.sleep(0.2)
        self.try_click_ok_popup(driver, timeout=3)

    def wait_and_click_ley_work_ok(self, driver, timeout=5):
        logger.info("Waiting for Work/Ley popup...")
        end = time.time() + timeout
        xpaths = [
            "//div[contains(@class,'modal-content')]//button[contains(@class,'btn-success') and contains(text(),'Ok')]",
            "//button[contains(@class,'btn-success') and contains(text(),'Ok')]",
            "//button[@data-bs-dismiss='modal' and contains(text(),'Ok')]"
        ]
        
        while time.time() < end:
            for xp in xpaths:
                try:
                    btns = driver.find_elements(By.XPATH, xp)
                    for btn in btns:
                        if btn.is_displayed():
                            logger.info(f"Found popup button via {xp}")
                            driver.execute_script("arguments[0].click();", btn)
                            time.sleep(0.2) 
                            return True
                except: pass
            time.sleep(0.2)
        
        logger.warning("Work/Ley popup NOT found or NOT clicked.")
        return False

    def select_kendo_dropdown(self, driver, input_elem, value):
        input_id = input_elem.get_attribute("id")
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", input_elem)
        time.sleep(0.1)

        driver.execute_script(f"$('#{input_id}').data('kendoDropDownList').open();")
        time.sleep(0.2) 
        
        ul = None
        for el in driver.find_elements(By.XPATH, "//ul[contains(@class,'k-list') and contains(@id,'listbox')]"):
            if el.is_displayed():
                ul = el
                break
        if ul:
            items = ul.find_elements(By.TAG_NAME, "li")
            for item in items:
                if value.lower() in item.text.lower():
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", item)
                    time.sleep(0.1) 
                    driver.execute_script("arguments[0].click();", item)
                    return