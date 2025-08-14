import pandas as pd
from lxml import etree
import re
import os
import time
from typing import List, Callable, Dict

# ==============================================================================
# 地址正規化輔助函式 (v1.3)
# ==============================================================================

def arabic_to_chinese_numerals(text: str) -> str:
    """將字串中的阿拉伯數字轉換為中文國字數字 (逐字轉換)。"""
    if not isinstance(text, str):
        return ""
    num_map = {
        '0': '〇', '1': '一', '2': '二', '3': '三', '4': '四',
        '5': '五', '6': '六', '7': '七', '8': '八', '9': '九'
    }
    return "".join(num_map.get(char, char) for char in text)

def normalize_taiwan_address(address: str) -> Dict[str, str]:
    """
    對台灣地址進行深度正規化 (v1.3版，增加括號內容移除)。
    """
    if not isinstance(address, str) or pd.isna(address) or not address.strip():
        return {'full': "", 'city': "", 'district': ""}

    # 1. 基礎清理
    addr = address.strip().upper().replace(" ", "").replace("\u3000", "").replace("臺", "台")
    addr = addr.replace('-', '之')
    
    full_width_nums = "０１２３４５６７８９"
    half_width_nums = "0123456789"
    translation_table = str.maketrans(full_width_nums, half_width_nums)
    addr = addr.translate(translation_table)
    
    addr = addr.replace('F', '樓')
    
    # 【本次新增】移除所有括號 (包含半形/全形) 及其中的內容
    addr = re.sub(r'[\(（].*?[\)）]', '', addr)
    
    addr = re.sub(r'(\d+)鄰', '', addr)

    # 2. 使用強健的正則表達式拆分地址元件
    pattern = (
        r'(?P<city>\D+?[縣市])?'
        r'(?P<district>[^村里路街巷弄號樓\d]+[區鄉鎮市])?'
        r'(?P<village>[^村里路街巷弄號樓\d]+[村里])?'
        r'(?P<road>.*?((路|街|大道|道)(?!.*(路|街|大道|道))))?'
        r'(?P<section>[\d一二三四五六七八九十百]+[段])?'
        r'(?P<lane>[\d一二三四五六七八九十百]+[巷])?'
        r'(?P<alley>[\d一二三四五六七八九十百]+[弄])?'
        r'(?P<number>[\d一二三四五六七八九十百之-]+[號])?'
        r'(?P<floor>[\d一二三四五六七八九十百]+[樓])?'
        r'(?P<rest>.*)'
    )
    
    match = re.search(pattern, addr)
    
    if not match:
        simple_pattern = r'(?P<main_address>.*?號)?(?P<rest>.*)'
        match = re.search(simple_pattern, addr)
        if not match:
             return {'full': addr, 'city': "", 'district': ""}
    
    parts = match.groupdict(default='')

    # 3. 對特定地址元件進行數字到中文的轉換
    parts['section'] = arabic_to_chinese_numerals(parts.get('section', ''))
    parts['lane'] = arabic_to_chinese_numerals(parts.get('lane', ''))
    parts['alley'] = arabic_to_chinese_numerals(parts.get('alley', ''))
    parts['number'] = arabic_to_chinese_numerals(parts.get('number', ''))
    parts['floor'] = arabic_to_chinese_numerals(parts.get('floor', ''))
    parts['rest'] = arabic_to_chinese_numerals(parts.get('rest', ''))

    # 4. 重新組合
    normalized_full = (
        f"{parts.get('city', '')}{parts.get('district', '')}{parts.get('village', '')}{parts.get('road', '')}"
        f"{parts.get('section', '')}{parts.get('lane', '')}{parts.get('alley', '')}"
        f"{parts.get('number', '')}{parts.get('floor', '')}{parts.get('rest', '')}"
        f"{parts.get('main_address', '')}"
    )
    normalized_full = re.sub(r'\s+', '', normalized_full).strip()
    
    return {'full': normalized_full, 'city': parts.get('city', ''), 'district': parts.get('district', '')}

# ==============================================================================
# 主要處理函式 (parse_and_process_reports)
# ==============================================================================

def parse_and_process_reports(
    file_paths: List[str],
    log_callback: Callable[[str], None]
) -> pd.DataFrame:
    """
    解析所有下載的XML報表檔案，進行清理、正規化，並回傳一個乾淨的DataFrame。
    """
    # ... (此函式主體邏輯不變，它會自動呼叫上面更新過的 normalize_taiwan_address 函式) ...
    log_callback("INFO: 開始執行報表解析與資料處理程序...")
    all_dataframes = []
    ns = {'ss': 'urn:schemas-microsoft-com:office:spreadsheet'}

    for file_path in file_paths:
        try:
            tree = etree.parse(file_path)
            rows_xml = tree.xpath('.//ss:Row', namespaces=ns)
            header, all_rows_data, is_data_section = [], [], False

            for row in rows_xml:
                cells_text = [
                    (data.text or "").strip()
                    for cell in row.findall('ss:Cell', ns)
                    for data in cell.findall('ss:Data', ns)
                ]
                if not cells_text: continue
                
                if cells_text[0] == "入境日" and not is_data_section:
                    is_data_section = True
                    header = [h.replace('\n', '') for h in cells_text]
                    continue
                
                if is_data_section:
                    row_data = cells_text[:len(header)]
                    while len(row_data) < len(header):
                        row_data.append("")
                    all_rows_data.append(row_data)

            if header and all_rows_data:
                df = pd.DataFrame(all_rows_data, columns=header)
                all_dataframes.append(df)
            else:
                log_callback(f"WARNING: 檔案 {os.path.basename(file_path)} 中未找到有效資料。")

        except Exception as e:
            log_callback(f"ERROR: 解析檔案 {os.path.basename(file_path)} 時發生錯誤: {e}")

    if not all_dataframes:
        log_callback("CRITICAL: 所有檔案均解析失敗或為空。")
        return pd.DataFrame()

    master_df = pd.concat(all_dataframes, ignore_index=True)
    log_callback(f"INFO: 所有報表已成功合併！總共有 {len(master_df)} 筆原始資料。")

    if not master_df.empty and str(master_df.iloc[-1, 0]).strip().startswith('合計'):
        master_df = master_df.iloc[:-1]
        log_callback("INFO: 已成功移除合計列。")

    log_callback("INFO: 正在進行資料欄位標準化與正規化...")
    column_mapping = {
        '雇主簡稱': 'employer_name', '中文譯名': 'worker_name', '性別': 'gender',
        '國籍': 'nationality', '護照號碼': 'passport_number', '居留證號': 'arc_number',
        '入境日': 'arrival_date', '離境日': 'departure_date', '工作期限': 'work_permit_expiry_date',
        '居留地址': 'original_address',
    }
    master_df.rename(columns=column_mapping, inplace=True)
    
    master_df['employer_name'] = master_df['employer_name'].str.replace(r'[\(（].*?[\)）]', '', regex=True).str.strip()
    master_df['unique_id'] = master_df['employer_name'].astype(str).str.strip() + '_' + master_df['worker_name'].astype(str).str.strip()
    
    addr_info = master_df['original_address'].apply(normalize_taiwan_address).apply(pd.Series)
    master_df[['normalized_address', 'city', 'district']] = addr_info[['full', 'city', 'district']]
    
    final_columns = [
        'unique_id', 'employer_name', 'worker_name', 'gender', 'nationality', 
        'passport_number', 'arc_number', 'arrival_date', 'departure_date', 
        'work_permit_expiry_date', 'original_address', 'normalized_address', 'city', 'district'
    ]
    existing_final_columns = [col for col in final_columns if col in master_df.columns]
    final_df = master_df[existing_final_columns].drop_duplicates(subset=['unique_id'], keep='first').copy()
    
    log_callback(f"INFO: 資料清理與正規化完成，最終處理完畢資料共 {len(final_df)} 筆。")
    return final_df