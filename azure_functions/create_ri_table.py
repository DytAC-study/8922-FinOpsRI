import os
import psycopg2
import sys
import time
import re # Add this import for regex

# 请在这里直接粘贴您的数据库连接字符串
# 确保替换 'YourActualStrongPassword!' 为您的真实密码
# 这个连接字符串应该与您在Function App中成功测试的格式一致
DB_CONN_STRING = "postgresql://youradmin:YourStrongPassword123!@rg-finops-ri-reporting-dev-dev-pgsql-finopst1.postgres.database.azure.com:5432/ri_finops_db?sslmode=require"
# 请务必替换为实际的连接字符串，这里使用一个占位符以确保安全
# DB_CONN_STRING = os.getenv("DATABASE_CONNECTION_STRING", "YourActualStrongPassword!") # 确保从环境变量获取或替换

def create_table_with_retries(db_conn_string, max_retries=10, initial_delay=5):
    """
    Attempts to connect to DB and create ri_usage table with retries and exponential backoff.
    """
    conn = None
    retries = 0
    while retries < max_retries:
        try:
            print(f"Attempt {retries + 1}/{max_retries}: Connecting to database and creating table...")
            conn = psycopg2.connect(db_conn_string)
            cursor = conn.cursor()
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS ri_usage (
                subscription_id TEXT NOT NULL,
                resource_id TEXT NOT NULL,
                usage_quantity REAL,
                usage_start TEXT NOT NULL, -- RI的购买/生效日期，不再是主键的一部分
                email_recipient TEXT,
                report_date TEXT NOT NULL, -- 新增列，记录这条usage数据是哪一天的
                PRIMARY KEY (subscription_id, resource_id, report_date) -- 新的主键
            );
            """)
            conn.commit()
            cursor.close()
            print("ri_usage table created or already exists successfully.")
            return True # Success
        except psycopg2.OperationalError as e:
            # This specific error is for connection issues (e.g., firewall, incorrect host)
            print(f"Connection failed: {e}. Retrying in {initial_delay * (2 ** retries)} seconds...")
            retries += 1
            if retries < max_retries:
                time.sleep(initial_delay * (2 ** (retries - 1))) # Exponential backoff
        except Exception as e:
            # Other unexpected errors (e.g., syntax error in SQL, permissions)
            print(f"Error creating ri_usage table: {e}", file=sys.stderr)
            sys.exit(1) # Exit immediately for non-connection errors
        finally:
            if conn:
                conn.close()
    print(f"Failed to create ri_usage table after {max_retries} attempts.", file=sys.stderr)
    return False # Failure after all retries

if __name__ == "__main__":
    # 检查DB_CONN_STRING是否已正确设置
    if not DB_CONN_STRING or 'YourActualStrongPassword!' in DB_CONN_STRING:
        print("错误：请设置正确的 'DATABASE_CONNECTION_STRING' 环境变量，并替换为您的真实密码。", file=sys.stderr)
        sys.exit(1)

    if not create_table_with_retries(DB_CONN_STRING):
        sys.exit(1)