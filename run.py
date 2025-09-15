import streamlit.web.cli as stcli
import sys
import os

def get_resource_path(relative_path):
    """
    獲取資源的正確路徑，無論是在開發環境還是打包後的 .exe 環境。
    """
    try:
        # PyInstaller 建立一個暫存資料夾，並將路徑儲存在 _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

if __name__ == "__main__":
    # 獲取主程式 main_app.py 的路徑
    # 我們需要 --add-data "main_app.py;." 來確保這個檔案被打包進去
    app_path = get_resource_path('main_app.py')
    
    # --- 關鍵：設定 Streamlit 命令列參數 ---
    # 這等同於在命令列執行 streamlit run app_path --server.headless=true ...
    sys.argv = [
        "streamlit",
        "run",
        app_path,
        "--global.developmentMode=false",
        "--server.headless=true",
        "--server.fileWatcherType=none",
        # 您可以自訂 port，或移除這兩行讓 Streamlit 自動尋找可用 port
        "--server.port", "8501" 
    ]

    # --- 執行 Streamlit ---
    sys.exit(stcli.main())