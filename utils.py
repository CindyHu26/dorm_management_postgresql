import sys
import os
import uuid
import re
from datetime import date

# 設定各類照片的儲存資料夾
UPLOAD_DIRS = {
    "dorm": "dorm_photos",
    "lease": "lease_photos",
    "accommodation": "accommodation_photos"
}

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

def ensure_directories():
    """確保上傳資料夾存在"""
    for path in UPLOAD_DIRS.values():
        if not os.path.exists(path):
            os.makedirs(path)

def sanitize_filename(name):
    """移除檔名中的非法字元"""
    return re.sub(r'[\\/*?:"<>|]', "", str(name)).replace(" ", "_")

def save_uploaded_files(uploaded_files, category, naming_prefix):
    """
    通用檔案儲存函式
    :param uploaded_files: Streamlit UploadedFile 列表
    :param category: 類別 ('dorm', 'lease', 'accommodation')
    :param naming_prefix: 檔名開頭 (例如 '地址_日期')
    :return: 儲存後的相對路徑列表
    """
    ensure_directories()
    base_dir = UPLOAD_DIRS.get(category, "temp_uploads")
    saved_paths = []

    if not uploaded_files:
        return []

    for file in uploaded_files:
        # 取得副檔名
        file_ext = os.path.splitext(file.name)[1]
        # 產生唯一檔名: 前綴_UUID.ext
        unique_id = str(uuid.uuid4())[:6]
        safe_prefix = sanitize_filename(naming_prefix)
        filename = f"{safe_prefix}_{unique_id}{file_ext}"
        
        file_path = os.path.join(base_dir, filename)
        
        with open(file_path, "wb") as f:
            f.write(file.getbuffer())
        
        saved_paths.append(file_path)
    
    return saved_paths

def delete_file(file_path):
    """刪除指定檔案"""
    try:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
            return True
    except Exception as e:
        print(f"Error deleting file {file_path}: {e}")
    return False