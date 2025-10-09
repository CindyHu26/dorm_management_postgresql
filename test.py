# test_selenium.py (v12 - JS賦值 + Selenium點擊 最終版)

import time
import os
from datetime import datetime, timedelta
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# --- 請在這裡填寫您的設定 ---
TARGET_URL = "192.168.1.168/labor/labor_816_p02.php" # 請填寫您的目標網址(不要包含 http://)
ACCOUNT = "robot"
PASSWORD = "1930"
DOWNLOAD_DIR = os.path.join(os.getcwd(), "selenium_downloads")
# --- 設定結束 ---

def run_selenium_test():
    print("--- 開始執行 Selenium 抓取測試 (v12 - JS賦值 + Selenium點擊版) ---")

    if not os.path.exists(DOWNLOAD_DIR):
        os.makedirs(DOWNLOAD_DIR)

    options = webdriver.ChromeOptions()
    prefs = {"download.default_directory": DOWNLOAD_DIR}
    options.add_experimental_option("prefs", prefs)
    
    driver = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()), options=options)

    try:
        auth_url = f"http://{ACCOUNT}:{PASSWORD}@{TARGET_URL}"
        print(f"正在使用 Basic Auth 方式自動登入並前往目標頁面...")
        driver.get(auth_url)
        
        print("正在等待表單元素載入...")
        wait = WebDriverWait(driver, 20)
        # 我們只需要等待一個關鍵元素出現即可
        wait.until(EC.presence_of_element_located((By.NAME, "CU00_BNO1")))
        print("表單元素已成功載入！")
        
        print("\n正在使用 JavaScript 直接設定表單所有欄位的值...")
        base_date_str = (datetime.today() + timedelta(days=14)).strftime('%Y-%m-%d')
        start_code, end_code = "A01", "H99" # 我們直接用大範圍測試

        # --- 【核心修改 1】使用一大段 JavaScript 腳本來瞬間設定所有值 ---
        # 這是我們從 requests 測試中驗證過最可能正確的 payload
        js_script = f"""
        var payload = {{
            'CU00_BNO1': '{start_code}',
            'CU00_ENO1': '{end_code}',
            'CU00_SDATE': '2',
            'CU00_BASE': '{base_date_str}',
            'CU00_BASE_I': 'Y',
            'CU00_chk21': 'D',
            'CU00_SEL35': '2',
            'CU00_chk1': 'N', 'CU00_chk2': 'N',
            'CU00_ORG1': 'A', 'CU00_city': '0',
            'CU00_LA04': '0', 'CU00_LA19': '0', 'CU00_LA198': '0',
            'CU00_WORK': '0', 'CU00_PNO': '0', 'CU00_LNO': '0',
            'CU00_LA28': '0', 'CU00_SALERS': 'A', 'CU00_MEMBER': 'A',
            'CU00_SERVS': 'A', 'CU00_ACCS': '0', 'CU00_TRANSF': 'A',
            'CU00_RET': '0', 'CU00_ORD': '1'
        }};

        for (var name in payload) {{
            var element = document.getElementsByName(name)[0];
            if (element) {{
                element.value = payload[name];
                console.log('Set ' + name + ' to ' + payload[name]);
            }}
        }}
        console.log('表單賦值完成！');
        """
        driver.execute_script(js_script)
        print("JavaScript 執行完畢，所有欄位已設定。")
        
        # --- 【核心修改 2】使用 Selenium 進行最後的點擊 ---
        print("準備點擊 '轉出Excel' 按鈕...")
        # 等待按鈕變為可點擊狀態
        submit_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.NAME, 'key'))
        )
        submit_button.click()
        
        print("已提交表單，正在等待檔案下載...")
        print(f"檔案將會儲存於: {DOWNLOAD_DIR}")

        # 等待下載的邏輯維持不變
        download_wait_time = 600
        time_elapsed = 0
        downloaded_file = None
        while time_elapsed < download_wait_time:
            files = [os.path.join(DOWNLOAD_DIR, f) for f in os.listdir(DOWNLOAD_DIR) if not f.endswith('.crdownload')]
            if not files:
                time.sleep(2)
                time_elapsed += 2
                continue
            latest_file = max(files, key=os.path.getctime)
            if (time.time() - os.path.getctime(latest_file)) < 60:
                 downloaded_file = latest_file
                 break
            else:
                 time.sleep(2)
                 time_elapsed += 2
        
        if downloaded_file:
            print(f"\n[成功] 檔案下載完成！已儲存至: {downloaded_file}")
            print("🎉🎉🎉 請最後一次檢查這個檔案的內容是否完整！")
        else:
            print("\n[失敗] 等待時間超過 10 分鐘，仍未偵測到下載完成的檔案。")

    except Exception as e:
        print(f"\n[嚴重錯誤] 執行 Selenium 過程中發生錯誤: {e}")
        screenshot_path = "selenium_error_screenshot.png"
        driver.save_screenshot(screenshot_path)
        print(f"已將錯誤畫面截圖儲存至: {screenshot_path}")

    finally:
        input("測試結束，按下 Enter 鍵關閉瀏覽器...")
        driver.quit()
        print("瀏覽器已關閉。")


if __name__ == "__main__":
    run_selenium_test()