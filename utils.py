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
        # 如果不是在打包環境中，則使用目前檔案所在的目錄
        base_path = os.path.abspath(".")
    
    return os.path.join(base_path, relative_path)