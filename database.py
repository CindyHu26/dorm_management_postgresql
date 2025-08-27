import os
import sys
import configparser
import psycopg2
from psycopg2.extras import RealDictCursor

def get_base_path():
    """獲取資源的基礎路徑。"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.abspath(".")

BASE_PATH = get_base_path()
CONFIG_FILE = os.path.join(BASE_PATH, "config.ini")

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
            # 【關鍵步驟 2】: 這行是解決問題的核心，它告訴 psycopg2 將查詢結果打包成字典
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
                "primary_manager" VARCHAR(50) DEFAULT '雇主', "rent_payer" VARCHAR(50) DEFAULT '雇主',
                "utilities_payer" VARCHAR(50) DEFAULT '雇主', "insurance_fee" INTEGER,
                "insurance_start_date" DATE, "insurance_end_date" DATE, "fire_safety_fee" INTEGER,
                "fire_safety_start_date" DATE, "fire_safety_end_date" DATE,
                "management_notes" TEXT, "dorm_notes" TEXT
            );
            """
            
            TABLES['Rooms'] = """
            CREATE TABLE IF NOT EXISTS "Rooms" (
                "id" SERIAL PRIMARY KEY, "dorm_id" INTEGER NOT NULL, "room_number" VARCHAR(50) NOT NULL,
                "capacity" INTEGER, "gender_policy" VARCHAR(50) DEFAULT '可混住',
                "nationality_policy" VARCHAR(50) DEFAULT '不限', "room_notes" TEXT,
                FOREIGN KEY ("dorm_id") REFERENCES "Dormitories" ("id") ON DELETE CASCADE
            );
            """

            TABLES['Workers'] = """
            CREATE TABLE IF NOT EXISTS "Workers" (
                "unique_id" VARCHAR(255) PRIMARY KEY, "room_id" INTEGER, "employer_name" VARCHAR(255) NOT NULL,
                "worker_name" VARCHAR(255) NOT NULL, "gender" VARCHAR(10), "nationality" VARCHAR(50),
                "passport_number" VARCHAR(50), "arc_number" VARCHAR(50), "arrival_date" DATE,
                "departure_date" DATE, "work_permit_expiry_date" DATE, "accommodation_start_date" DATE,
                "accommodation_end_date" DATE, 
                "monthly_fee" INTEGER, 
                "utilities_fee" INTEGER,
                "cleaning_fee" INTEGER,
                "fee_notes" TEXT, "payment_method" VARCHAR(50), "data_source" VARCHAR(50) NOT NULL,
                "worker_notes" TEXT, 
                "special_status" VARCHAR(100), -- <<<<<<<<<<< 這就是關鍵的「當前狀態」欄位
                FOREIGN KEY ("room_id") REFERENCES "Rooms" ("id") ON DELETE SET NULL
            );
            """

            TABLES['DormitoryEquipment'] = """
            CREATE TABLE IF NOT EXISTS "DormitoryEquipment" (
                "id" SERIAL PRIMARY KEY, "dorm_id" INTEGER NOT NULL, "equipment_name" VARCHAR(100) NOT NULL,
                "location" VARCHAR(100), "last_replaced_date" DATE, "next_check_date" DATE,
                "status" VARCHAR(50), "report_path" VARCHAR(255),
                FOREIGN KEY ("dorm_id") REFERENCES "Dormitories" ("id") ON DELETE CASCADE
            );
            """

            TABLES['Meters'] = """
            CREATE TABLE IF NOT EXISTS "Meters" (
                "id" SERIAL PRIMARY KEY, "dorm_id" INTEGER NOT NULL, "meter_type" VARCHAR(50) NOT NULL,
                "meter_number" VARCHAR(100) NOT NULL, "area_covered" VARCHAR(100),
                FOREIGN KEY ("dorm_id") REFERENCES "Dormitories" ("id") ON DELETE CASCADE
            );
            """

            TABLES['Leases'] = """
            CREATE TABLE IF NOT EXISTS "Leases" (
                "id" SERIAL PRIMARY KEY, "dorm_id" INTEGER NOT NULL, "lease_start_date" DATE,
                "lease_end_date" DATE, "monthly_rent" INTEGER, "deposit" INTEGER,
                "utilities_included" BOOLEAN, "contract_scan_path" VARCHAR(255),
                FOREIGN KEY ("dorm_id") REFERENCES "Dormitories" ("id") ON DELETE CASCADE
            );
            """

            TABLES['UtilityBills'] = """
            CREATE TABLE IF NOT EXISTS "UtilityBills" (
                "id" SERIAL PRIMARY KEY, "dorm_id" INTEGER NOT NULL, "meter_id" INTEGER,
                "bill_type" VARCHAR(50) NOT NULL, "amount" INTEGER NOT NULL,
                "bill_start_date" DATE NOT NULL, "bill_end_date" DATE NOT NULL,
                "is_invoiced" BOOLEAN, "notes" TEXT,
                FOREIGN KEY ("dorm_id") REFERENCES "Dormitories" ("id") ON DELETE CASCADE,
                FOREIGN KEY ("meter_id") REFERENCES "Meters" ("id") ON DELETE SET NULL
            );
            """

            TABLES['AnnualExpenses'] = """
            CREATE TABLE IF NOT EXISTS "AnnualExpenses" (
                "id" SERIAL PRIMARY KEY, "dorm_id" INTEGER NOT NULL, "expense_item" VARCHAR(100) NOT NULL,
                "payment_date" DATE, "total_amount" INTEGER NOT NULL,
                "amortization_start_month" VARCHAR(7), "amortization_end_month" VARCHAR(7), "notes" TEXT,
                FOREIGN KEY ("dorm_id") REFERENCES "Dormitories" ("id") ON DELETE CASCADE
            );
            """
            
            TABLES['OtherIncome'] = """
            CREATE TABLE IF NOT EXISTS "OtherIncome" (
                "id" SERIAL PRIMARY KEY, "dorm_id" INTEGER NOT NULL, "income_item" VARCHAR(100) NOT NULL,
                "transaction_date" DATE NOT NULL, "amount" INTEGER NOT NULL, "notes" TEXT,
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
            
            print("INFO: (PostgreSQL) 正在建立所有表格...")
            for table_name, table_sql in TABLES.items():
                cursor.execute(table_sql)

            INDEXES = [
                'CREATE INDEX IF NOT EXISTS idx_dorms_normalized_address ON "Dormitories" ("normalized_address");',
                'CREATE INDEX IF NOT EXISTS idx_workers_employer_name ON "Workers" ("employer_name");',
                'CREATE INDEX IF NOT EXISTS idx_rooms_dorm_id ON "Rooms" ("dorm_id");',
                'CREATE INDEX IF NOT EXISTS idx_workers_room_id ON "Workers" ("room_id");',
                'CREATE INDEX IF NOT EXISTS idx_feehistory_worker_id ON "FeeHistory" ("worker_unique_id");',
                'CREATE INDEX IF NOT EXISTS idx_statushistory_worker_id ON "WorkerStatusHistory" ("worker_unique_id");'
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