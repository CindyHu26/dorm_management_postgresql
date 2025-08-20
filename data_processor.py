import pandas as pd
from lxml import etree
import re
import os
from datetime import datetime
from typing import List, Callable, Dict

def arabic_to_chinese_numerals(text: str) -> str:
    if not isinstance(text, str): return ""
    num_map = {'0': '〇','1': '一','2': '二','3': '三','4': '四','5': '五','6': '六','7': '七','8': '八','9': '九'}
    return "".join(num_map.get(char, char) for char in text)

def advanced_arabic_to_chinese(num_str: str) -> str:
    """
    進階的阿拉伯數字轉中文數字函式，能處理進位。
    例如： "21" -> "二十一", "105" -> "一百零五"
    """
    if not num_str.isdigit():
        return num_str # 如果不是純數字，直接返回原樣

    num = int(num_str)
    num_map = {0: '〇', 1: '一', 2: '二', 3: '三', 4: '四', 5: '五', 6: '六', 7: '七', 8: '八', 9: '九'}
    unit_map = {1: '', 10: '十', 100: '百'}

    if 0 <= num <= 9:
        return num_map[num]
    
    if 10 <= num <= 19:
        return f"十{num_map[num % 10]}" if num % 10 != 0 else "十"
        
    if 20 <= num <= 99:
        return f"{num_map[num // 10]}十{num_map[num % 10]}" if num % 10 != 0 else f"{num_map[num // 10]}十"

    if 100 <= num <= 999:
        hundred = num // 100
        rest = num % 100
        if rest == 0:
            return f"{num_map[hundred]}百"
        elif rest < 10:
            return f"{num_map[hundred]}百零{num_map[rest]}"
        elif rest % 10 == 0:
            return f"{num_map[hundred]}百{num_map[rest // 10]}十"
        else:
            return f"{num_map[hundred]}百{num_map[rest // 10]}十{num_map[rest % 10]}"
            
    return num_str # 超出範圍則返回原樣

def normalize_taiwan_address(address: str) -> Dict[str, str]:
    """
    對台灣地址進行深度正規化 (v2.5 最終版)。
    """
    if not isinstance(address, str) or pd.isna(address) or not address.strip():
        return {'full': "", 'city': "", 'district': ""}
    
    # 1. 基礎清理
    addr = address.strip().upper().replace(" ", "").replace("\u3000", "").replace("臺", "台")
    
    # --- 依照規則，精準地統一標點符號 ---
    # 1a. 將所有 . 替換為 、
    addr = addr.replace('.', '、')
    # 1b. 將所有 - 替換為 之
    addr = addr.replace('-', '之')

    # 1c. 繼續其餘清理
    full_width_nums = "０１２３４５６７８９"
    half_width_nums = "0123456789"
    translation_table = str.maketrans(full_width_nums, half_width_nums)
    addr = addr.translate(translation_table)
    addr = addr.replace('F', '樓')
    addr = re.sub(r'[\(（].*?[\)）]', '', addr)
    addr = re.sub(r'(\d+)鄰', '', addr)
    addr = re.sub(r'(縣|市|區|鄉|鎮|村|里|路|街|段|巷|弄|號|樓)\1+', r'\1', addr)

    # 【核心修改】使用一個新的正則表達式，在轉換前先將數字和單位分開
    def convert_numbers_in_address(text):
        if not text: return ""
        # 尋找 "數字+單位" 的模式
        return re.sub(r'(\d+)(段|巷|弄|號|樓)', lambda m: advanced_arabic_to_chinese(m.group(1)) + m.group(2), text)
        
    # 2. 特殊城市/縣的映射規則
    county_map = {
        "彰化市": "彰化縣彰化市", "嘉義市": "嘉義縣嘉義市", "新竹市": "新竹縣新竹市",
        "屏東市": "屏東縣屏東市", "宜蘭市": "宜蘭縣宜蘭市", "花蓮市": "花蓮縣花蓮市",
        "台東市": "台東縣台東市", "苗栗市": "苗栗縣苗栗市", "南投市": "南投縣南投市",
        "斗六市": "雲林縣斗六市", "太保市": "嘉義縣太保市", "朴子市": "嘉義縣朴子市",
        "馬公市": "澎湖縣馬公市",
    }
    for city_short, city_full in county_map.items():
        if addr.startswith(city_short):
            addr = addr.replace(city_short, city_full, 1)
            break

    # 3. 寬鬆地解析所有可能的地址元件
    pattern = (
        r'(?P<city>\D+?[縣市])?'
        r'(?P<district>\D+?[區鄉鎮市])?'
        r'(?P<village>\D+?[村里])?'
        r'(?P<road>.*?((路|街|大道|道)(?!.*(路|街|大道|道))))?'
        r'(?P<section>[\d一二三四五六七八九十百]+[段])?'
        r'(?P<lane>[\d一二三四五六七八九十百]+[巷])?'
        r'(?P<alley>[\d一二三四五六七八九十百]+[弄])?'
        # 讓 number 欄位可以匹配 '之' 和 '、'
        r'(?P<number>[\d一二三四五六七八九十百之、]+[號])?'
        r'(?P<floor>[\d一二三四五六七八九十百]+[樓])?'
        r'(?P<rest>.*)'
    )
    match = re.search(pattern, addr)
    if not match:
        return {'full': addr, 'city': "", 'district': ""}
    
    parts = match.groupdict(default='')

    # 4. 數字轉中文
    parts['number'] = arabic_to_chinese_numerals(parts.get('number', ''))
    # ... 其餘數字轉換不變 ...
    
    # 5. 權威性判斷與重組
    village_part = parts.get('village', '')
    if parts.get('road') or parts.get('section'):
        village_part = ''
        
    normalized_full = (
        f"{parts.get('city', '')}{parts.get('district', '')}{village_part}{parts.get('road', '')}"
        f"{parts.get('section', '')}{parts.get('lane', '')}{parts.get('alley', '')}"
        f"{parts.get('number', '')}{parts.get('floor', '')}{parts.get('rest', '')}"
    )
    normalized_full = re.sub(r'\s+', '', normalized_full).strip()
    
    return {'full': normalized_full, 'city': parts.get('city', ''), 'district': parts.get('district', '')}

def parse_and_process_reports(file_paths: List[str], log_callback: Callable[[str], None]) -> pd.DataFrame:
    """
    解析所有下載的XML報表檔案，進行清理、正規化。
    """
    log_callback("INFO: 開始執行報表解析與資料處理程序...")
    all_dataframes = []
    ns = {'ss': 'urn:schemas-microsoft-com:office:spreadsheet'}

    for file_path in file_paths:
        try:
            tree = etree.parse(file_path)
            rows_xml = tree.xpath('.//ss:Row', namespaces=ns)
            header, all_rows_data, is_data_section = [], [], False
            for row in rows_xml:
                cells_text = [(data.text or "").strip() for cell in row.findall('ss:Cell', ns) for data in cell.findall('ss:Data', ns)]
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
    
    log_callback("INFO: 正在過濾無效的空白資料列...")
    original_rows = len(master_df)
    master_df.dropna(subset=['雇主簡稱', '中文譯名'], inplace=True)
    master_df = master_df[master_df['雇主簡稱'].str.strip() != '']
    master_df = master_df[master_df['中文譯名'].str.strip() != '']
    log_callback(f"INFO: 已過濾 {original_rows - len(master_df)} 筆無效資料列。")

    log_callback("INFO: 正在進行資料欄位標準化與正規化...")
    column_mapping = {
        '雇主簡稱': 'employer_name', '中文譯名': 'worker_name', '性別': 'gender',
        '國籍': 'nationality', '護照號碼': 'passport_number', '居留證號': 'arc_number',
        '入境日': 'arrival_date', '離境日': 'departure_date', '工作期限': 'work_permit_expiry_date',
        '居留地址': 'original_address',
    }
    master_df.rename(columns=column_mapping, inplace=True)
    
    regex_pattern = r'\s?\(接\)$|\s?\(遞:.*?\)$'
    master_df['employer_name'] = master_df['employer_name'].str.replace(regex_pattern, '', regex=True).str.strip()
    
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