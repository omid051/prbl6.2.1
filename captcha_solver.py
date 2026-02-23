import time
import requests
import base64
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains

API_KEY = "32798173382848c11af60940c49fdd60"

def solve_captcha(driver):
    iframe = driver.find_element(By.CSS_SELECTOR, "iframe.k-content-frame")
    driver.switch_to.frame(iframe)
    captcha_element = driver.find_element(By.TAG_NAME, "body")
    captcha_screenshot = captcha_element.screenshot_as_png
    driver.switch_to.default_content()
    captcha_b64 = base64.b64encode(captcha_screenshot).decode("utf-8")

    url = "http://2captcha.com/in.php"
    data = {
        "key": API_KEY,
        "method": "base64",
        "body": captcha_b64,
        "coordinatescaptcha": 1,
        "json": 1,
    }
    r = requests.post(url, data=data)
    result = r.json()
    if result.get("status") != 1:
        raise Exception(f"2captcha input error: {result}")
    captcha_id = result.get("request")
    url = "http://2captcha.com/res.php"
    params = {
        "key": API_KEY,
        "action": "get",
        "id": captcha_id,
        "json": 1
    }
    waited = 0
    while waited < 120:
        r = requests.get(url, params=params)
        result = r.json()
        if result.get("status") == 1:
            coords_str = result.get("request")
            break
        elif result.get("request") == "CAPCHA_NOT_READY":
            time.sleep(5)
            waited += 5
        else:
            raise Exception(f"2captcha result error: {result}")
    else:
        raise Exception("Timeout waiting for 2captcha")
    coords = []
    if isinstance(coords_str, list):
        for pair in coords_str:
            x = int(pair['x'])
            y = int(pair['y'])
            coords.append((x, y))
    else:
        coords_str = coords_str.replace('coordinates:', '')
        pairs = coords_str.split(';')
        for pair in pairs:
            if not pair.strip():
                continue
            x_part, y_part = pair.split(',')
            x = int(x_part.split('=')[1])
            y = int(y_part.split('=')[1])
            coords.append((x, y))
    driver.switch_to.frame(iframe)
    for (x, y) in coords:
        driver.execute_script("""
            var x = arguments[0], y = arguments[1];
            var el = document.elementFromPoint(x, y);
            if (el) {
                el.dispatchEvent(new PointerEvent('pointerdown', {bubbles:true, clientX:x, clientY:y}));
                el.dispatchEvent(new MouseEvent('mousedown', {bubbles:true, clientX:x, clientY:y}));
                el.dispatchEvent(new PointerEvent('pointerup', {bubbles:true, clientX:x, clientY:y}));
                el.dispatchEvent(new MouseEvent('mouseup', {bubbles:true, clientX:x, clientY:y}));
                el.dispatchEvent(new MouseEvent('click', {bubbles:true, clientX:x, clientY:y}));
            }
        """, x, y)
        time.sleep(0.6)
    submit_div = None
    divs = driver.find_elements(By.CSS_SELECTOR, ".img-action-div")
    for d in divs:
        try:
            icon = d.find_element(By.CSS_SELECTOR, "i#submit")
            if icon.is_displayed():
                submit_div = d
                break
        except Exception:
            continue
    if submit_div is not None:
        ActionChains(driver).move_to_element(submit_div).pause(0.5).click().perform()
    else:
        driver.save_screenshot("submit_not_found_inside_iframe.png")
        raise Exception("No visible submit div found to click inside iframe.")
    driver.switch_to.default_content()
    time.sleep(1)