import os
import sys
import configparser
import psycopg2
from psycopg2.extras import RealDictCursor

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
import pandas as pd
# 建立一個全域變數來存放資料庫引擎。
# 初始為 None，表示尚未連線。
# 使用底線 _ 開頭是 Python 的一種慣例，代表這是模組內部使用的變數。
_engine: Engine | None = None

def setup_connection(host, port, dbname, user, password):
    """
    初始化資料庫連線引擎。
    這個函式會由 main.py 在程式一開始時呼叫一次，
    建立一個共用的連線引擎供整個專案使用。
    """
    global _engine
    
    # 如果已經連線，就不要再重複建立
    if _engine is not None:
        print("資料庫引擎已存在，無需重複初始化。")
        return

    try:
        # 建立 PostgreSQL 的連線 URL
        # 格式為：postgresql://使用者名稱:密碼@主機IP:埠號/資料庫名稱
        db_url = f"postgresql://{user}:{password}@{host}:{port}/{dbname}"
        
        # 建立引擎，並設定 pool_pre_ping=True 可以在每次使用前檢查連線是否有效，增加穩定性
        _engine = create_engine(db_url, pool_pre_ping=True)
        
        # 執行一個簡單的查詢來驗證連線是否成功
        with _engine.connect() as connection:
            print("資料庫連線成功！引擎已準備就緒。")
            
    except Exception as e:
        # 如果連線失敗，印出錯誤訊息並將引擎設回 None
        print(f"CRITICAL: 資料庫連線設定失敗: {e}")
        _engine = None
        # 拋出異常，讓主程式知道發生嚴重錯誤
        raise

def get_engine() -> Engine:
    """
    提供給其他模組 (updater.py, export_model.py) 呼叫的函式，
    用來取得已經建立好的資料庫引擎。
    """
    if _engine is None:
        # 如果引擎尚未初始化就試圖使用，拋出錯誤
        raise ConnectionError("資料庫連線尚未初始化。請確保主程式已執行 setup_connection。")
    return _engine

def get_base_path():
    """獲取資源的基礎路徑。"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.abspath(".")

BASE_PATH = get_base_path()
CONFIG_FILE = os.path.join(BASE_PATH, "config.ini")

def get_general_config():
    """從 config.ini 讀取通用設定。"""
    if not os.path.exists(CONFIG_FILE):
        return {} # 如果檔案不存在，回傳空字典
    config = configparser.ConfigParser()
    config.read(CONFIG_FILE, encoding='utf-8')
    if 'General' in config:
        return config['General']
    return {} # 如果區塊不存在，回傳空字典

def get_db_config():
    """從 config.ini 讀取資料庫設定。"""
    if not os.path.exists(CONFIG_FILE):
        raise FileNotFoundError(f"設定檔 config.ini 不存在於 {BASE_PATH}，請建立它。")
    config = configparser.ConfigParser()
    config.read(CONFIG_FILE, encoding='utf-8')
    if 'Database' not in config:
        raise ValueError("config.ini 中缺少 [Database] 區塊")
    return config['Database']

def get_db_connection():
    """根據設定檔建立並回傳 PostgreSQL 資料庫連線。"""
    try:
        config = get_db_config()
        db_type = config.get('type', '').lower()

        if db_type != 'postgresql':
            raise ValueError(f"設定檔中的資料庫類型不是 'postgresql'，請檢查 config.ini。")

        conn = psycopg2.connect(
            host=config.get('host'),
            port=config.getint('port', 5432),
            user=config.get('user'),
            password=config.get('password'),
            dbname=config.get('dbname'),
            # 這行是解決問題的核心，它告訴 psycopg2 將查詢結果打包成字典
            cursor_factory=RealDictCursor 
        )
        # print("INFO: 已成功連線至 PostgreSQL 資料庫 (使用 RealDictCursor)。")
        return conn
            
    except Exception as e:
        print(f"資料庫連線失敗: {e}")
        return None

def create_all_tables_and_indexes():
    """為 PostgreSQL 執行所有 CREATE TABLE 和 CREATE INDEX 指令。"""
    conn = get_db_connection()
    if not conn: 
        print("錯誤：無法建立資料庫連線，建表程序終止。")
        return

    try:
        with conn.cursor() as cursor:
            TABLES = {}

            TABLES['Dormitories'] = """
            CREATE TABLE IF NOT EXISTS "Dormitories" (
                "id" SERIAL PRIMARY KEY, "legacy_dorm_code" VARCHAR(50), "original_address" VARCHAR(255),
                "normalized_address" VARCHAR(255) NOT NULL UNIQUE, "dorm_name" VARCHAR(100),
                "city" VARCHAR(50),
                "district" VARCHAR(50),
                "person_in_charge" VARCHAR(50),
                "landlord_id" INTEGER, 
                "primary_manager" VARCHAR(50) DEFAULT '雇主', "rent_payer" VARCHAR(50) DEFAULT '雇主',
                "utilities_payer" VARCHAR(50) DEFAULT '雇主', "insurance_fee" INTEGER,
                "insurance_start_date" DATE, "insurance_end_date" DATE, "fire_safety_fee" INTEGER,
                "fire_safety_start_date" DATE, "fire_safety_end_date" DATE,
                "management_notes" TEXT, "dorm_notes" TEXT, "is_self_owned" BOOLEAN DEFAULT FALSE,
                "invoice_info" TEXT,
                "photo_paths" TEXT[],
                FOREIGN KEY ("landlord_id") REFERENCES "Vendors" ("id") ON DELETE SET NULL
            );
            """

            TABLES['Rooms'] = """
            CREATE TABLE IF NOT EXISTS "Rooms" (
                "id" SERIAL PRIMARY KEY, "dorm_id" INTEGER NOT NULL, "room_number" VARCHAR(50) NOT NULL,
                "capacity" INTEGER, "gender_policy" VARCHAR(50) DEFAULT '可混住',
                "nationality_policy" VARCHAR(50) DEFAULT '不限', "room_notes" TEXT,
                "area_sq_meters" NUMERIC(10, 2),
                FOREIGN KEY ("dorm_id") REFERENCES "Dormitories" ("id") ON DELETE CASCADE
            );
            """

            TABLES['Workers'] = """
            CREATE TABLE IF NOT EXISTS "Workers" (
                "unique_id" VARCHAR(255) PRIMARY KEY, 
                "room_id" INTEGER, -- 【修改】此欄位未來僅作為「當前位置」的快取或參考，主要邏輯改查 AccommodationHistory
                "employer_name" VARCHAR(255) NOT NULL,
                "worker_name" VARCHAR(255) NOT NULL, "gender" VARCHAR(10), "nationality" VARCHAR(50),
                "passport_number" VARCHAR(50), "arc_number" VARCHAR(50), "arrival_date" DATE,
                "departure_date" DATE, "work_permit_expiry_date" DATE, "accommodation_start_date" DATE,
                "accommodation_end_date" DATE, 
                "monthly_fee" INTEGER, 
                "utilities_fee" INTEGER,
                "cleaning_fee" INTEGER,
                "restoration_fee" INTEGER, -- 宿舍復歸費
                "charging_cleaning_fee" INTEGER, -- 充電清潔費
                "fee_notes" TEXT, "payment_method" VARCHAR(50), "data_source" VARCHAR(50) NOT NULL,
                "worker_notes" TEXT, 
                "special_status" VARCHAR(100),
                FOREIGN KEY ("room_id") REFERENCES "Rooms" ("id") ON DELETE SET NULL
            );
            """

            TABLES['AccommodationHistory'] = """
            CREATE TABLE IF NOT EXISTS "AccommodationHistory" (
                "id" SERIAL PRIMARY KEY,
                "worker_unique_id" VARCHAR(255) NOT NULL,
                "room_id" INTEGER NOT NULL,
                "start_date" DATE NOT NULL,
                "end_date" DATE,
                "bed_number" VARCHAR(20),
                "notes" TEXT,
                "checkin_photo_paths" TEXT[], -- 入住照片
                "checkout_photo_paths" TEXT[], -- 退宿照片
                FOREIGN KEY ("worker_unique_id") REFERENCES "Workers" ("unique_id") ON DELETE CASCADE,
                FOREIGN KEY ("room_id") REFERENCES "Rooms" ("id") ON DELETE CASCADE
            );
            """

            TABLES['DormitoryEquipment'] = """
            CREATE TABLE IF NOT EXISTS "DormitoryEquipment" (
                "id" SERIAL PRIMARY KEY,
                "dorm_id" INTEGER NOT NULL,
                "vendor_id" INTEGER, -- 【核心修改】新增廠商關聯 ID
                "equipment_name" VARCHAR(100) NOT NULL,
                "equipment_category" VARCHAR(50),
                "location" VARCHAR(100),
                "brand_model" VARCHAR(100),
                "serial_number" VARCHAR(100),
                "purchase_cost" INTEGER,
                "installation_date" DATE,
                "maintenance_interval_months" INTEGER,
                "compliance_interval_months" INTEGER,
                "last_maintenance_date" DATE,
                "next_maintenance_date" DATE,
                "status" VARCHAR(50),
                "notes" TEXT,
                "report_path" VARCHAR(255),
                FOREIGN KEY ("dorm_id") REFERENCES "Dormitories" ("id") ON DELETE CASCADE,
                FOREIGN KEY ("vendor_id") REFERENCES "Vendors" ("id") ON DELETE SET NULL
            );
            """

            TABLES['Meters'] = """
            CREATE TABLE IF NOT EXISTS "Meters" (
                "id" SERIAL PRIMARY KEY, "dorm_id" INTEGER NOT NULL, "meter_type" VARCHAR(50) NOT NULL,
                "meter_number" VARCHAR(100) NOT NULL, "area_covered" VARCHAR(100),
                "notes" TEXT,
                FOREIGN KEY ("dorm_id") REFERENCES "Dormitories" ("id") ON DELETE CASCADE
            );
            """

            TABLES['Leases'] = """
            CREATE TABLE IF NOT EXISTS "Leases" (
                "id" SERIAL PRIMARY KEY, "dorm_id" INTEGER NOT NULL, 
                "vendor_id" INTEGER, 
                "payer" VARCHAR(50) DEFAULT '我司',
                "contract_item" VARCHAR(100) DEFAULT '房租',
                "lease_start_date" DATE,
                "lease_end_date" DATE, "monthly_rent" INTEGER, "deposit" INTEGER,
                "utilities_included" BOOLEAN, "contract_scan_path" VARCHAR(255),
                "photo_paths" TEXT[],
                "notes" TEXT,
                FOREIGN KEY ("dorm_id") REFERENCES "Dormitories" ("id") ON DELETE CASCADE,
                FOREIGN KEY ("vendor_id") REFERENCES "Vendors" ("id") ON DELETE SET NULL
            );
            """

            TABLES['UtilityBills'] = """
            CREATE TABLE IF NOT EXISTS "UtilityBills" (
                "id" SERIAL PRIMARY KEY, "dorm_id" INTEGER NOT NULL, "meter_id" INTEGER,
                "bill_type" VARCHAR(50) NOT NULL, "amount" INTEGER NOT NULL,
                "bill_start_date" DATE NOT NULL, "bill_end_date" DATE NOT NULL,
                "is_invoiced" BOOLEAN, "notes" TEXT,
                "payer" VARCHAR(50),
                "is_pass_through" BOOLEAN DEFAULT FALSE,
                "peak_usage" NUMERIC(10, 2),    
                "sat_half_peak_usage" NUMERIC(10, 2),
                "off_peak_usage" NUMERIC(10, 2),  
                FOREIGN KEY ("dorm_id") REFERENCES "Dormitories" ("id") ON DELETE CASCADE,
                FOREIGN KEY ("meter_id") REFERENCES "Meters" ("id") ON DELETE SET NULL
            );
            """

            TABLES['ComplianceRecords'] = """
            CREATE TABLE IF NOT EXISTS "ComplianceRecords" (
                "id" SERIAL PRIMARY KEY,
                "dorm_id" INTEGER NOT NULL,
                "equipment_id" INTEGER, -- 新增：關聯到特定設備 (例如飲水機的水質檢測)
                "record_type" VARCHAR(50) NOT NULL,
                "details" JSONB,
                "created_at" TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY ("dorm_id") REFERENCES "Dormitories" ("id") ON DELETE CASCADE,
                FOREIGN KEY ("equipment_id") REFERENCES "DormitoryEquipment" ("id") ON DELETE SET NULL -- 新增外鍵關聯
            );
            """

            TABLES['AnnualExpenses'] = """
            CREATE TABLE IF NOT EXISTS "AnnualExpenses" (
                "id" SERIAL PRIMARY KEY,
                "dorm_id" INTEGER NOT NULL,
                "compliance_record_id" INTEGER UNIQUE,
                "expense_item" VARCHAR(100) NOT NULL,
                "payment_date" DATE,
                "total_amount" INTEGER NOT NULL,
                "amortization_start_month" VARCHAR(7),
                "amortization_end_month" VARCHAR(7),
                "notes" TEXT,
                FOREIGN KEY ("dorm_id") REFERENCES "Dormitories" ("id") ON DELETE CASCADE,
                FOREIGN KEY ("compliance_record_id") REFERENCES "ComplianceRecords" ("id") ON DELETE SET NULL
            );
            """
            
            TABLES['OtherIncome'] = """
            CREATE TABLE IF NOT EXISTS "OtherIncome" (
                "id" SERIAL PRIMARY KEY, 
                "dorm_id" INTEGER NOT NULL, 
                "room_id" INTEGER,
                "income_item" VARCHAR(100) NOT NULL,
                "transaction_date" DATE NOT NULL, 
                "amount" INTEGER NOT NULL, 
                "notes" TEXT,
                "target_employer" VARCHAR(100),
                FOREIGN KEY ("dorm_id") REFERENCES "Dormitories" ("id") ON DELETE CASCADE,
                FOREIGN KEY ("room_id") REFERENCES "Rooms" ("id") ON DELETE SET NULL
            );
            """
            TABLES['RecurringIncomeConfigs'] = """
            CREATE TABLE IF NOT EXISTS "RecurringIncomeConfigs" (
                "id" SERIAL PRIMARY KEY,
                "dorm_id" INTEGER NOT NULL,
                "income_item" VARCHAR(100) NOT NULL,
                "amount" INTEGER NOT NULL,
                "start_date" DATE, -- 生效起始日
                "end_date" DATE,   -- 生效結束日
                "active" BOOLEAN DEFAULT TRUE,
                "calc_method" VARCHAR(20),
                "target_employer" VARCHAR(100);
                "notes" TEXT,
                FOREIGN KEY ("dorm_id") REFERENCES "Dormitories" ("id") ON DELETE CASCADE
            );
            """

            TABLES['FeeHistory'] = """
            CREATE TABLE IF NOT EXISTS "FeeHistory" (
                "id" SERIAL PRIMARY KEY,
                "worker_unique_id" VARCHAR(255) NOT NULL,
                "fee_type" VARCHAR(50) NOT NULL,
                "amount" INTEGER NOT NULL,
                "effective_date" DATE NOT NULL,
                "created_at" TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY ("worker_unique_id") REFERENCES "Workers" ("unique_id") ON DELETE CASCADE
            );
            """

            TABLES['WorkerStatusHistory'] = """
            CREATE TABLE IF NOT EXISTS "WorkerStatusHistory" (
                "id" SERIAL PRIMARY KEY,
                "worker_unique_id" VARCHAR(255) NOT NULL,
                "status" VARCHAR(100), "start_date" DATE, "end_date" DATE, "notes" TEXT,
                FOREIGN KEY ("worker_unique_id") REFERENCES "Workers" ("unique_id") ON DELETE CASCADE
            );
            """
            
            TABLES['Vendors'] = """
            CREATE TABLE IF NOT EXISTS "Vendors" (
                "id" SERIAL PRIMARY KEY,
                "service_category" TEXT,
                "vendor_name" TEXT,
                "contact_person" TEXT,
                "phone_number" TEXT,
                "tax_id" VARCHAR(20), -- 【核心修改 1】新增統一編號
                "remittance_info" TEXT, -- 【核心修改 2】新增匯款資訊
                "notes" TEXT
            );
            """

            TABLES['MaintenanceLog'] = """
            CREATE TABLE IF NOT EXISTS "MaintenanceLog" (
                "id" SERIAL PRIMARY KEY,
                "dorm_id" INTEGER NOT NULL,
                "vendor_id" INTEGER,
                "equipment_id" INTEGER, -- 新增：關聯到特定設備
                "status" VARCHAR(50) NOT NULL DEFAULT '待處理',
                "notification_date" DATE,
                "reported_by" TEXT,
                "item_type" TEXT, -- 可用於區分 維修/保養
                "description" TEXT,
                "contacted_vendor_date" DATE,
                "key_info" TEXT,
                "completion_date" DATE,
                "cost" INTEGER,
                "payer" VARCHAR(50),
                "invoice_date" DATE,
                "invoice_info" TEXT,
                "is_archived_as_expense" BOOLEAN DEFAULT FALSE,
                "notes" TEXT,
                "photo_paths" TEXT[],
                FOREIGN KEY ("dorm_id") REFERENCES "Dormitories" ("id") ON DELETE CASCADE,
                FOREIGN KEY ("vendor_id") REFERENCES "Vendors" ("id") ON DELETE SET NULL,
                FOREIGN KEY ("equipment_id") REFERENCES "DormitoryEquipment" ("id") ON DELETE SET NULL -- 新增外鍵關聯
            );
            """

            TABLES['InventoryItems'] = """
            CREATE TABLE IF NOT EXISTS "InventoryItems" (
                "id" SERIAL PRIMARY KEY,
                "item_name" TEXT NOT NULL UNIQUE,
                "item_category" TEXT,
                "dorm_id" INTEGER,
                "current_stock" INTEGER NOT NULL DEFAULT 0,
                "unit_cost" INTEGER,
                "specifications" TEXT,
                "notes" TEXT,
                FOREIGN KEY ("dorm_id") REFERENCES "Dormitories" ("id") ON DELETE SET NULL
            );
            """
            TABLES['InventoryLog'] = """
            CREATE TABLE IF NOT EXISTS "InventoryLog" (
                "id" SERIAL PRIMARY KEY,
                "item_id" INTEGER NOT NULL,
                "transaction_type" VARCHAR(50),
                "quantity" INTEGER,
                "transaction_date" DATE NOT NULL,
                "dorm_id" INTEGER,
                "person_in_charge" TEXT,
                "related_expense_id" INTEGER,
                "related_income_id" INTEGER,
                "notes" TEXT,
                FOREIGN KEY ("item_id") REFERENCES "InventoryItems" ("id") ON DELETE CASCADE,
                FOREIGN KEY ("dorm_id") REFERENCES "Dormitories" ("id") ON DELETE SET NULL
            );
            """

            print("INFO: (PostgreSQL) 正在建立所有表格...")
            for table_name, table_sql in TABLES.items():
                cursor.execute(table_sql)

            INDEXES = [
                'CREATE INDEX IF NOT EXISTS idx_dorms_normalized_address ON "Dormitories" ("normalized_address");',
                'CREATE INDEX IF NOT EXISTS idx_workers_employer_name ON "Workers" ("employer_name");',
                'CREATE INDEX IF NOT EXISTS idx_rooms_dorm_id ON "Rooms" ("dorm_id");',
                'CREATE INDEX IF NOT EXISTS idx_workers_room_id ON "Workers" ("room_id");',
                'CREATE INDEX IF NOT EXISTS idx_feehistory_worker_id ON "FeeHistory" ("worker_unique_id");',
                'CREATE INDEX IF NOT EXISTS idx_statushistory_worker_id ON "WorkerStatusHistory" ("worker_unique_id");',
                'CREATE INDEX IF NOT EXISTS idx_accomhistory_worker_id ON "AccommodationHistory" ("worker_unique_id");',
                'CREATE INDEX IF NOT EXISTS idx_accomhistory_room_id ON "AccommodationHistory" ("room_id");',
                'CREATE INDEX IF NOT EXISTS idx_vendors_service_category ON public."Vendors" (service_category);',
                'CREATE INDEX IF NOT EXISTS idx_vendors_vendor_name ON public."Vendors" (vendor_name);',
                'CREATE INDEX IF NOT EXISTS idx_vendors_contact_person ON public."Vendors" (contact_person);',
                'CREATE INDEX IF NOT EXISTS idx_vendors_phone_number ON public."Vendors" (phone_number);'

            ]
            print("INFO: (PostgreSQL) 正在建立所有索引...")
            for index_sql in INDEXES:
                cursor.execute(index_sql)
        
        conn.commit()
        print("SUCCESS: (PostgreSQL) 所有表格與索引已成功建立！")
    except psycopg2.Error as err:
        print(f"資料庫操作失敗: {err}")
        conn.rollback()
    finally:
        if conn:
            conn.close()
            
if __name__ == '__main__':
    print("正在根據 config.ini 設定初始化資料庫...")
    create_all_tables_and_indexes()