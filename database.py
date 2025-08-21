import sqlite3
import os
import pandas as pd

DB_NAME = "dorm_management.db"

def get_db_connection(db_name=None):
    """建立並回傳資料庫連線。"""
    target_db = db_name if db_name else DB_NAME
    try:
        base_path = os.path.dirname(os.path.abspath(__file__))
        full_path = os.path.join(base_path, target_db)
        conn = sqlite3.connect(full_path)
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
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_other_income_dorm_id ON OtherIncome(dorm_id);")

    # --- 為常用查詢欄位建立索引 ---
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_dorms_legacy_code ON Dormitories(legacy_dorm_code);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_workers_employer_name ON Workers(employer_name);")
    
    # --- 為日期/攤提相關欄位建立索引 ---
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_leases_end_date ON Leases(lease_end_date);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_bills_dates ON UtilityBills(bill_start_date, bill_end_date);")
    
    print("SUCCESS: 所有索引已建立。")


def create_all_tables_and_indexes():
    """執行所有 CREATE TABLE 和 CREATE INDEX 指令。"""
    conn = get_db_connection()
    if not conn: return

    try:
        cursor = conn.cursor()
        print("INFO: 開始建立資料庫表格...")

        # --- 所有 CREATE TABLE 語句 ---
        # 1. Dormitories
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS Dormitories (
            id INTEGER PRIMARY KEY AUTOINCREMENT, legacy_dorm_code TEXT, original_address TEXT,
            normalized_address TEXT NOT NULL UNIQUE, dorm_name TEXT, primary_manager TEXT DEFAULT '雇主',
            rent_payer TEXT DEFAULT '雇主', utilities_payer TEXT DEFAULT '雇主',
            insurance_fee INTEGER, insurance_start_date DATE, insurance_end_date DATE,
            fire_safety_fee INTEGER, fire_safety_start_date DATE, fire_safety_end_date DATE,
            management_notes TEXT, dorm_notes TEXT
        );
        """)
        # 2. Rooms
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS Rooms (
            id INTEGER PRIMARY KEY AUTOINCREMENT, dorm_id INTEGER NOT NULL, room_number TEXT NOT NULL,
            capacity INTEGER, gender_policy TEXT DEFAULT '可混住', nationality_policy TEXT DEFAULT '不限', room_notes TEXT,
            FOREIGN KEY (dorm_id) REFERENCES Dormitories (id) ON DELETE CASCADE
        );
        """)
        # 3. Workers
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS Workers (
            unique_id TEXT PRIMARY KEY, room_id INTEGER, employer_name TEXT NOT NULL,
            worker_name TEXT NOT NULL, gender TEXT, nationality TEXT, passport_number TEXT,
            arc_number TEXT, arrival_date DATE, departure_date DATE, work_permit_expiry_date DATE,
            accommodation_start_date DATE, accommodation_end_date DATE, monthly_fee INTEGER,
            fee_notes TEXT, payment_method TEXT, data_source TEXT NOT NULL,
            worker_notes TEXT, special_status TEXT,
            FOREIGN KEY (room_id) REFERENCES Rooms (id) ON DELETE SET NULL
        );
        """)
        # 4. DormitoryEquipment
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS DormitoryEquipment (
            id INTEGER PRIMARY KEY AUTOINCREMENT, dorm_id INTEGER NOT NULL, equipment_name TEXT NOT NULL,
            location TEXT, last_replaced_date DATE, next_check_date DATE, status TEXT,
            FOREIGN KEY (dorm_id) REFERENCES Dormitories (id) ON DELETE CASCADE
        );
        """)
        # 5. Meters
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS Meters (
            id INTEGER PRIMARY KEY AUTOINCREMENT, dorm_id INTEGER NOT NULL, meter_type TEXT NOT NULL,
            meter_number TEXT NOT NULL, area_covered TEXT,
            FOREIGN KEY (dorm_id) REFERENCES Dormitories (id) ON DELETE CASCADE
        );
        """)
        # 6. Leases
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS Leases (
            id INTEGER PRIMARY KEY AUTOINCREMENT, dorm_id INTEGER NOT NULL, lease_start_date DATE,
            lease_end_date DATE, monthly_rent INTEGER, deposit INTEGER, utilities_included BOOLEAN,
            contract_scan_path TEXT,
            FOREIGN KEY (dorm_id) REFERENCES Dormitories (id) ON DELETE CASCADE
        );
        """)
        # 7. UtilityBills
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS UtilityBills (
            id INTEGER PRIMARY KEY AUTOINCREMENT, dorm_id INTEGER NOT NULL, meter_id INTEGER,
            bill_type TEXT NOT NULL, amount INTEGER NOT NULL, bill_start_date DATE NOT NULL,
            bill_end_date DATE NOT NULL, is_invoiced BOOLEAN, notes TEXT,
            FOREIGN KEY (dorm_id) REFERENCES Dormitories (id) ON DELETE CASCADE,
            FOREIGN KEY (meter_id) REFERENCES Meters (id) ON DELETE SET NULL
        );
        """)
        # 8. AnnualExpenses
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS AnnualExpenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT, dorm_id INTEGER NOT NULL, expense_item TEXT NOT NULL,
            payment_date DATE, total_amount INTEGER NOT NULL, amortization_start_month TEXT,
            amortization_end_month TEXT, notes TEXT,
            FOREIGN KEY (dorm_id) REFERENCES Dormitories (id) ON DELETE CASCADE
        );
        """)
        # 9. OtherIncome
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS OtherIncome (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dorm_id INTEGER NOT NULL,
            income_item TEXT NOT NULL,
            transaction_date DATE NOT NULL,
            amount INTEGER NOT NULL,
            notes TEXT,
            FOREIGN KEY (dorm_id) REFERENCES Dormitories (id) ON DELETE CASCADE
        );
        """)
        print("SUCCESS: 所有表格已成功建立。")

        # --- 【核心修正】將 create_indexes 移至所有 CREATE TABLE 之後 ---
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
    DB_FILE = DB_NAME
    if os.path.exists(DB_FILE):
        print(f"警告：資料庫檔案 '{DB_FILE}' 已存在，將被刪除以建立新的結構。")
        try:
            os.remove(DB_FILE)
            print(f"INFO: 舊的資料庫檔案 '{DB_FILE}' 已刪除。")
        except OSError as e:
            print(f"錯誤：無法刪除舊的資料庫檔案。錯誤訊息: {e}")
            exit()
    
    print(f"正在建立全新的資料庫 '{DB_FILE}'...")
    create_all_tables_and_indexes()
    print(f"\n全新的資料庫 '{DB_FILE}' 已成功建立，並包含所有表格與索引。")