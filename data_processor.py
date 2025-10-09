import pandas as pd
from lxml import etree
import re
import os
from datetime import datetime
from typing import List, Callable, Dict

def chinese_to_arabic(cn_num_str: str) -> str:
    """
    進階的中文數字轉阿拉伯數字函式，能處理'五百五十七'這樣的語意。
    """
    if not isinstance(cn_num_str, str): return cn_num_str
    
    cn_num_map = {'〇': 0, '一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9}
    cn_unit_map = {'十': 10, '百': 100, '千': 1000, '萬': 10000}
    
    # 直接替換，處理 "五十之三" -> "50之3"
    for cn, ar in cn_num_map.items():
        cn_num_str = cn_num_str.replace(cn, str(ar))
        
    # 處理進位
    if '十' in cn_num_str and cn_num_str.startswith('十'):
        cn_num_str = '1' + cn_num_str

    def _trans(s):
        num = 0
        if s:
            idx = s.find('十')
            if idx != -1:
                num += int(s[:idx]) * 10
                if len(s) > idx+1:
                    num += int(s[idx+1:])
            else:
                num += int(s)
        return num

    sec = cn_num_str.split('百')
    if len(sec) > 2: # 避免多個 "百"
        return cn_num_str

    num = 0
    if len(sec) == 2:
        if sec[0]:
            num += int(sec[0]) * 100
        else: #處理 "百三" -> 103
             num += 100
        num += _trans(sec[1])
    else:
        num = _trans(sec[0])
    return str(num)

def normalize_taiwan_address(address: str) -> Dict[str, str]:
    """對台灣地址進行深度正規化 (v2.8 最終版)。"""
    if not isinstance(address, str) or pd.isna(address) or not address.strip():
        return {'full': "", 'city': "", 'district': ""}
    
    addr = address.strip().upper().replace(" ", "").replace("\u3000", "").replace("臺", "台")
    addr = addr.replace('.', '、').replace('-', '之')
    full_width_nums = "０１２３４５６７８９"
    half_width_nums = "0123456789"
    addr = addr.translate(str.maketrans(full_width_nums, half_width_nums))
    addr = addr.replace('鎭', '鎮')
    addr = addr.replace('F', '樓')
    addr = re.sub(r'[\(（].*?[\)）]', '', addr)
    addr = re.sub(r'(\d+)鄰', '', addr)
    addr = re.sub(r'(縣|市|區|鄉|鎮|村|里|路|街|段|巷|弄|號|樓)\1+', r'\1', addr)

    addr = re.sub(r'([一二三四五六七八九十百]+)(?=段|巷|弄|號|樓|街)', lambda m: chinese_to_arabic(m.group(1)), addr)

    county_map = {
        # 彰化縣 (2市 6鎮 18鄉)
        "彰化市": "彰化縣彰化市",
        "員林市": "彰化縣員林市",
        "和美鎮": "彰化縣和美鎮",
        "鹿港鎮": "彰化縣鹿港鎮",
        "溪湖鎮": "彰化縣溪湖鎮",
        "二林鎮": "彰化縣二林鎮",
        "田中鎮": "彰化縣田中鎮",
        "北斗鎮": "彰化縣北斗鎮",
        "花壇鄉": "彰化縣花壇鄉",
        "芬園鄉": "彰化縣芬園鄉",
        "大村鄉": "彰化縣大村鄉",
        "永靖鄉": "彰化縣永靖鄉",
        "伸港鄉": "彰化縣伸港鄉",
        "線西鄉": "彰化縣線西鄉",
        "福興鄉": "彰化縣福興鄉",
        "秀水鄉": "彰化縣秀水鄉",
        "埔心鄉": "彰化縣埔心鄉",
        "埔鹽鄉": "彰化縣埔鹽鄉",
        "大城鄉": "彰化縣大城鄉",
        "芳苑鄉": "彰化縣芳苑鄉",
        "竹塘鄉": "彰化縣竹塘鄉",
        "社頭鄉": "彰化縣社頭鄉",
        "二水鄉": "彰化縣二水鄉",
        "田尾鄉": "彰化縣田尾鄉",
        "埤頭鄉": "彰化縣埤頭鄉",
        "溪州鄉": "彰化縣溪州鄉",

        # 雲林縣 (1市 5鎮 14鄉)
        "斗六市": "雲林縣斗六市",
        "斗南鎮": "雲林縣斗南鎮",
        "虎尾鎮": "雲林縣虎尾鎮",
        "西螺鎮": "雲林縣西螺鎮",
        "土庫鎮": "雲林縣土庫鎮",
        "北港鎮": "雲林縣北港鎮",
        "莿桐鄉": "雲林縣莿桐鄉",
        "林內鄉": "雲林縣林內鄉",
        "古坑鄉": "雲林縣古坑鄉",
        "大埤鄉": "雲林縣大埤鄉",
        "崙背鄉": "雲林縣崙背鄉",
        "二崙鄉": "雲林縣二崙鄉",
        "麥寮鄉": "雲林縣麥寮鄉",
        "東勢鄉": "雲林縣東勢鄉",
        "褒忠鄉": "雲林縣褒忠鄉",
        "臺西鄉": "雲林縣臺西鄉",
        "元長鄉": "雲林縣元長鄉",
        "四湖鄉": "雲林縣四湖鄉",
        "口湖鄉": "雲林縣口湖鄉",
        "水林鄉": "雲林縣水林鄉",

        # 嘉義縣 (2市 3鎮 15鄉)
        "太保市": "嘉義縣太保市",
        "朴子市": "嘉義縣朴子市",
        "布袋鎮": "嘉義縣布袋鎮",
        "大林鎮": "嘉義縣大林鎮",
        "民雄鄉": "嘉義縣民雄鄉",
        "溪口鄉": "嘉義縣溪口鄉",
        "新港鄉": "嘉義縣新港鄉",
        "六腳鄉": "嘉義縣六腳鄉",
        "東石鄉": "嘉義縣東石鄉",
        "義竹鄉": "嘉義縣義竹鄉",
        "鹿草鄉": "嘉義縣鹿草鄉",
        "水上鄉": "嘉義縣水上鄉",
        "中埔鄉": "嘉義縣中埔鄉",
        "竹崎鄉": "嘉義縣竹崎鄉",
        "梅山鄉": "嘉義縣梅山鄉",
        "番路鄉": "嘉義縣番路鄉",
        "大埔鄉": "嘉義縣大埔鄉",
        "阿里山鄉": "嘉義縣阿里山鄉",

        # 嘉義市 (直轄市)
        "嘉義市": "嘉義市嘉義市",

        # 新竹縣 (1市 3鎮 9鄉)
        "竹北市": "新竹縣竹北市",
        "竹東鎮": "新竹縣竹東鎮",
        "新埔鎮": "新竹縣新埔鎮",
        "關西鎮": "新竹縣關西鎮",
        "湖口鄉": "新竹縣湖口鄉",
        "新豐鄉": "新竹縣新豐鄉",
        "芎林鄉": "新竹縣芎林鄉",
        "橫山鄉": "新竹縣橫山鄉",
        "北埔鄉": "新竹縣北埔鄉",
        "寶山鄉": "新竹縣寶山鄉",
        "峨眉鄉": "新竹縣峨眉鄉",
        "尖石鄉": "新竹縣尖石鄉",
        "五峰鄉": "新竹縣五峰鄉",

        # 新竹市 (直轄市)
        "新竹市": "新竹市新竹市",
    }

    for city_short, city_full in county_map.items():
        if addr.startswith(city_short):
            addr = addr.replace(city_short, city_full, 1)
            break
    pattern = r'(?P<city>\D+?[縣市])?(?P<district>\D+?[區鄉鎮市])?(?P<village>\D+?[村里])?(?P<road>.*?((路|街|大道|道)(?!.*(路|街|大道|道))))?(?P<section>.*?[段])?(?P<lane>.*?[巷])?(?P<alley>.*?[弄])?(?P<number>[\d之、-]+[號])?(?P<floor>.*?[樓])?(?P<rest>.*)'
    match = re.search(pattern, addr)
    if not match: return {'full': addr, 'city': "", 'district': ""}
    parts = match.groupdict(default='')
    
    # --- 擴充權威性判斷規則 ---
    village_part = parts.get('village', '')
    # 如果地址中包含路/街/段，或「巷」，則村里為贅述，應忽略
    if parts.get('road') or parts.get('section') or parts.get('lane'):
        village_part = ''
        
    normalized_full = f"{parts.get('city', '')}{parts.get('district', '')}{village_part}{parts.get('road', '')}{parts.get('section', '')}{parts.get('lane', '')}{parts.get('alley', '')}{parts.get('number', '')}{parts.get('floor', '')}{parts.get('rest', '')}"
    normalized_full = re.sub(r'\s+', '', normalized_full).strip()
    
    return {'full': normalized_full, 'city': parts.get('city', ''), 'district': parts.get('district', '')}

def parse_and_process_reports(
    file_paths: List[str],
    log_callback: Callable[[str], None]
) -> pd.DataFrame:
    """
    【v2.11 地址過濾版】解析所有下載的XML報表檔案，進行清理、正規化。
    """
    log_callback("INFO: 開始執行報表解析與資料處理程序 (新版系統)...")
    all_dataframes = []
    ns = {'ss': 'urn:schemas-microsoft-com:office:spreadsheet'}

    parser = etree.XMLParser(recover=True, encoding='utf-8')

    for file_path in file_paths:
        try:
            with open(file_path, 'rb') as f:
                file_content = f.read()
            
            if not file_content:
                log_callback(f"WARNING: 檔案 {os.path.basename(file_path)} 內容為空，已略過。")
                continue

            tree = etree.fromstring(file_content, parser=parser)
            rows_xml = tree.xpath('.//ss:Row', namespaces=ns)
            header, all_rows_data, is_data_section = [], [], False
            
            for row in rows_xml:
                cells_text = [(data.text or "").strip() for cell in row.findall('ss:Cell', ns) for data in cell.findall('ss:Data', ns)]
                if not cells_text: continue
                
                if "客戶簡稱" in cells_text and "姓名(中)" in cells_text and not is_data_section:
                    is_data_section = True
                    header = [h.replace('\n', '') for h in cells_text]
                    log_callback(f"INFO: 在檔案 {os.path.basename(file_path)} 中找到資料標頭。")
                    continue

                if is_data_section:
                    row_data = cells_text[:len(header)]
                    while len(row_data) < len(header):
                        row_data.append("")
                    all_rows_data.append(row_data)
            
            if header and all_rows_data:
                df = pd.DataFrame(all_rows_data, columns=header)
                all_dataframes.append(df)
            elif not header:
                 log_callback(f"WARNING: 在檔案 {os.path.basename(file_path)} 中找不到有效的資料標頭，已略過。")

        except Exception as e:
            log_callback(f"ERROR: 解析檔案 {os.path.basename(file_path)} 時發生錯誤: {e}")

    if not all_dataframes:
        log_callback("CRITICAL: 所有檔案均解析失敗或為空。")
        return pd.DataFrame()

    master_df = pd.concat(all_dataframes, ignore_index=True)
    log_callback(f"INFO: 所有報表已成功合併！總共有 {len(master_df)} 筆原始資料。")

    log_callback("INFO: 正在過濾無效的空白資料列...")
    original_rows = len(master_df)
    master_df.dropna(subset=['客戶簡稱', '姓名(中)'], inplace=True)
    master_df = master_df[master_df['客戶簡稱'].str.strip() != '']
    master_df = master_df[master_df['姓名(中)'].str.strip() != '']
    log_callback(f"INFO: 已過濾 {original_rows - len(master_df)} 筆客戶或姓名為空的資料列。")

    # --- 【核心修改】在此處新增地址過濾邏輯 ---
    log_callback("INFO: 正在過濾地址為空的資料列...")
    original_rows = len(master_df)
    # 確保 '居住地址' 欄位存在
    if '居住地址' in master_df.columns:
        # 使用 .loc 來避免 SettingWithCopyWarning
        master_df = master_df.loc[master_df['居住地址'].notna() & (master_df['居住地址'].str.strip() != '')].copy()
        log_callback(f"INFO: 已過濾 {original_rows - len(master_df)} 筆地址為空的資料列。")
    else:
        log_callback("WARNING: 在報表中找不到 '居住地址' 欄位，無法進行地址過濾。")


    log_callback("INFO: 正在進行資料欄位標準化與正規化...")
    column_mapping = {
        '客戶簡稱': 'employer_name', 
        '姓名(中)': 'worker_name', 
        '英文姓名': 'native_name',
        '性別': 'gender', 
        '國籍': 'nationality', 
        '護照號碼': 'passport_number', 
        '居留證號': 'arc_number', 
        '聘僱起始日': 'accommodation_start_date',
        '聘僱期滿日': 'work_permit_expiry_date', 
        '居住地址': 'original_address',
    }
    master_df.rename(columns=column_mapping, inplace=True)

    log_callback("INFO: 正在強制統一所有日期欄位格式為 YYYY-MM-DD...")
    date_columns = ['accommodation_start_date', 'work_permit_expiry_date']
    for col in date_columns:
        if col in master_df.columns:
            master_df[col] = pd.to_datetime(master_df[col], errors='coerce').dt.strftime('%Y-%m-%d')
            master_df[col] = master_df[col].where(pd.notna(master_df[col]), None)

    regex_pattern = r'\s?\(接\)$|\s?\(遞:.*?\)$'
    master_df['employer_name'] = master_df['employer_name'].str.replace(regex_pattern, '', regex=True).str.strip()
    
    log_callback("INFO: 正在根據最新規則生成 Unique ID...")
    def generate_unique_id(row):
        employer = str(row.get('employer_name', '')).strip()
        name = str(row.get('worker_name', '')).strip()
        passport = str(row.get('passport_number', '')).strip()
        
        if passport:
            return f"{employer}_{name}_{passport}"
        else:
            return f"{employer}_{name}"

    master_df['unique_id'] = master_df.apply(generate_unique_id, axis=1)

    addr_info = master_df['original_address'].apply(normalize_taiwan_address).apply(pd.Series)
    master_df[['normalized_address', 'city', 'district']] = addr_info[['full', 'city', 'district']]
    
    final_columns = [
        'unique_id', 'employer_name', 'worker_name', 'native_name', 'gender', 'nationality', 
        'passport_number', 'arc_number', 
        'accommodation_start_date',
        'work_permit_expiry_date', 
        'original_address', 'normalized_address', 'city', 'district'
    ]
    existing_final_columns = [col for col in final_columns if col in master_df.columns]
    
    final_df = master_df[master_df['unique_id'] != '_'].copy()
    final_df = final_df[existing_final_columns].drop_duplicates(subset=['unique_id'], keep='first')
    
    log_callback(f"INFO: 資料清理與正規化完成，最終處理完畢資料共 {len(final_df)} 筆。")
    return final_df