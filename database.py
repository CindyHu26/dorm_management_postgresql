import sqlite3
import os
import pandas as pd

DB_NAME = "dorm_management.db"

def get_db_connection():
    """建立並回傳資料庫連線。"""
    try:
        conn = sqlite3.connect(DB_NAME)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as e:
        print(f"資料庫連線失敗: {e}")
        return None

def create_indexes(cursor):
    """建立所有必要的索引以提升查詢效能。"""
    print("INFO: 開始建立資料庫索引...")
    
    # --- 為所有外鍵建立索引 ---
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_rooms_dorm_id ON Rooms(dorm_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_workers_room_id ON Workers(room_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_equipment_dorm_id ON DormitoryEquipment(dorm_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_meters_dorm_id ON Meters(dorm_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_leases_dorm_id ON Leases(dorm_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_bills_dorm_id ON UtilityBills(dorm_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_bills_meter_id ON UtilityBills(meter_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_annual_expenses_dorm_id ON AnnualExpenses(dorm_id);")

    # --- 為常用查詢欄位建立索引 ---
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_dorms_legacy_code ON Dormitories(legacy_dorm_code);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_workers_employer_name ON Workers(employer_name);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_workers_data_source ON Workers(data_source);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_workers_accommodation_end_date ON Workers(accommodation_end_date);")
    
    # --- 為日期/攤提相關欄位建立索引 ---
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_equipment_check_date ON DormitoryEquipment(next_check_date);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_leases_end_date ON Leases(lease_end_date);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_annual_expenses_amortization ON AnnualExpenses(amortization_start_month, amortization_end_month);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_bills_dates ON UtilityBills(bill_start_date, bill_end_date);")
    
    print("SUCCESS: 所有索引已建立。")


def create_all_tables_and_indexes():
    """執行所有 CREATE TABLE 和 CREATE INDEX 指令。"""
    conn = get_db_connection()
    if not conn: return

    try:
        cursor = conn.cursor()
        print("INFO: 開始建立資料庫表格...")

        # 1. 宿舍地址表 (Dormitories)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS Dormitories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            legacy_dorm_code TEXT,
            original_address TEXT,
            normalized_address TEXT NOT NULL UNIQUE,
            dorm_name TEXT,
            primary_manager TEXT DEFAULT '雇主',
            rent_payer TEXT DEFAULT '雇主',
            utilities_payer TEXT DEFAULT '雇主',
            insurance_fee INTEGER,
            insurance_start_date DATE,
            insurance_end_date DATE,
            fire_safety_fee INTEGER,
            fire_safety_start_date DATE,
            fire_safety_end_date DATE,
            management_notes TEXT,
            dorm_notes TEXT
        );
        """)
        print("SUCCESS: 表格 'Dormitories' 已建立。")

        # 2. 房間表 (Rooms)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS Rooms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dorm_id INTEGER NOT NULL,
            room_number TEXT NOT NULL,
            capacity INTEGER,
            gender_policy TEXT DEFAULT '可混住',
            nationality_policy TEXT DEFAULT '不限',
            room_notes TEXT,
            FOREIGN KEY (dorm_id) REFERENCES Dormitories (id) ON DELETE CASCADE
        );
        """)
        print("SUCCESS: 表格 'Rooms' 已建立。")
        
        # 3. 移工資料表 (Workers)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS Workers (
            unique_id TEXT PRIMARY KEY,
            room_id INTEGER,
            employer_name TEXT NOT NULL,
            worker_name TEXT NOT NULL,
            gender TEXT,
            nationality TEXT,
            passport_number TEXT,
            arc_number TEXT,
            arrival_date DATE,
            departure_date DATE,
            work_permit_expiry_date DATE,
            accommodation_start_date DATE,
            accommodation_end_date DATE,
            monthly_fee INTEGER,
            fee_notes TEXT,
            payment_method TEXT,
            data_source TEXT NOT NULL,
            worker_notes TEXT,
            special_status TEXT,
            FOREIGN KEY (room_id) REFERENCES Rooms (id) ON DELETE SET NULL
        );
        """)
        print("SUCCESS: 表格 'Workers' 已建立。")

        # 4. 宿舍設備表 (DormitoryEquipment)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS DormitoryEquipment (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dorm_id INTEGER NOT NULL,
            equipment_name TEXT NOT NULL,
            location TEXT,
            last_replaced_date DATE,
            next_check_date DATE,
            status TEXT,
            FOREIGN KEY (dorm_id) REFERENCES Dormitories (id) ON DELETE CASCADE
        );
        """)
        print("SUCCESS: 表格 'DormitoryEquipment' 已建立。")

        # 5. 電水錶資料表 (Meters)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS Meters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dorm_id INTEGER NOT NULL,
            meter_type TEXT NOT NULL,
            meter_number TEXT NOT NULL,
            area_covered TEXT,
            FOREIGN KEY (dorm_id) REFERENCES Dormitories (id) ON DELETE CASCADE
        );
        """)
        print("SUCCESS: 表格 'Meters' 已建立。")

        # 6. 租賃合約表 (Leases)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS Leases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dorm_id INTEGER NOT NULL,
            lease_start_date DATE,
            lease_end_date DATE,
            monthly_rent INTEGER,
            deposit INTEGER,
            utilities_included BOOLEAN,
            contract_scan_path TEXT,
            FOREIGN KEY (dorm_id) REFERENCES Dormitories (id) ON DELETE CASCADE
        );
        """)
        print("SUCCESS: 表格 'Leases' 已建立。")

        # 7. 每月費用表 (UtilityBills) - 已重構為帳單式
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS UtilityBills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dorm_id INTEGER NOT NULL,
            meter_id INTEGER,
            bill_type TEXT NOT NULL,
            amount INTEGER NOT NULL,
            bill_start_date DATE NOT NULL,
            bill_end_date DATE NOT NULL,
            is_invoiced BOOLEAN,
            notes TEXT,
            FOREIGN KEY (dorm_id) REFERENCES Dormitories (id) ON DELETE CASCADE,
            FOREIGN KEY (meter_id) REFERENCES Meters (id) ON DELETE SET NULL
        );
        """)
        print("SUCCESS: 表格 'UtilityBills' 已重構。")
        
        # 8. 年度費用攤提表 (AnnualExpenses)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS AnnualExpenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dorm_id INTEGER NOT NULL,
            expense_item TEXT NOT NULL,
            payment_date DATE,
            total_amount INTEGER NOT NULL,
            amortization_start_month TEXT,
            amortization_end_month TEXT,
            notes TEXT,
            FOREIGN KEY (dorm_id) REFERENCES Dormitories (id) ON DELETE CASCADE
        );
        """)
        print("SUCCESS: 表格 'AnnualExpenses' 已建立。")
        
        create_indexes(cursor)
        conn.commit()
        print("\nINFO: 所有表格與索引均已成功建立！")

    except sqlite3.Error as e:
        print(f"建立資料庫時發生錯誤: {e}")
        conn.rollback()
    finally:
        if conn:
            conn.close()

if __name__ == '__main__':
    # 這個區塊的邏輯是為了方便您從零開始建立一個最乾淨、最佳化的資料庫。
    # 它會先刪除舊的檔案，再重新建立。
    # if os.path.exists(DB_NAME):
    #     print(f"警告：資料庫檔案 '{DB_NAME}' 已存在，將被刪除以建立新的結構。")
    #     try:
    #         os.remove(DB_NAME)
    #         print(f"INFO: 舊的資料庫檔案 '{DB_NAME}' 已刪除。")
    #     except OSError as e:
    #         print(f"錯誤：無法刪除舊的資料庫檔案，請檢查檔案是否被其他程式占用。錯誤訊息: {e}")
    #         exit() # 如果無法刪除，則終止程式
    
    # print(f"正在建立全新的資料庫 '{DB_NAME}'...")
    create_all_tables_and_indexes()
    print(f"\n全新的資料庫 '{DB_NAME}' 已成功建立，並包含所有表格與最佳化索引。")