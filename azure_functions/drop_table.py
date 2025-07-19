import psycopg2
import os
import sys
import time
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 请在这里直接粘贴您的数据库连接字符串
# 确保替换为您的真实密码。
# 如果您更喜欢从环境变量获取，请使用 os.getenv("DATABASE_CONNECTION_STRING")
# 例如：DB_CONN_STRING = os.getenv("DATABASE_CONNECTION_STRING")
DB_CONN_STRING = "postgresql://youradmin:YourStrongPassword123!@rg-finops-ri-reporting-dev-dev-pgsql-finopst1.postgres.database.azure.com:5432/ri_finops_db?sslmode=require"


def delete_ri_usage_table_with_retries(db_conn_string, max_retries=10, initial_delay=5):
    """
    Attempts to connect to DB and drop the ri_usage table with retries and exponential backoff.
    """
    conn = None
    retries = 0
    while retries < max_retries:
        try:
            logger.info(f"Attempt {retries + 1}/{max_retries}: Connecting to database and dropping table...")
            conn = psycopg2.connect(db_conn_string)
            cursor = conn.cursor()

            logger.info("Executing: DROP TABLE IF EXISTS ri_usage;")
            cursor.execute("DROP TABLE IF EXISTS ri_usage;")
            conn.commit()
            cursor.close()
            logger.info("Table 'ri_usage' dropped successfully (if it existed).")
            return True # Success

        except psycopg2.OperationalError as e:
            logger.warning(f"Connection failed: {e}. Retrying in {initial_delay * (2 ** retries)} seconds...")
            retries += 1
            if retries < max_retries:
                time.sleep(initial_delay * (2 ** (retries - 1))) # Exponential backoff
        except Exception as e:
            logger.error(f"Error dropping ri_usage table: {e}", exc_info=True)
            if conn:
                conn.rollback() # Rollback in case of error
            sys.exit(1) # Exit immediately for non-connection errors
        finally:
            if conn:
                conn.close()
                logger.info("PostgreSQL connection closed.")
    
    logger.error(f"Failed to drop ri_usage table after {max_retries} attempts.", file=sys.stderr)
    return False # Failure after all retries

if __name__ == "__main__":
    # Removed the placeholder check here. The script will now use DB_CONN_STRING as provided.
    if not DB_CONN_STRING:
        logger.error("错误：DB_CONN_STRING 未设置或为空。请提供有效的数据库连接字符串。")
        sys.exit(1)

    if not delete_ri_usage_table_with_retries(DB_CONN_STRING):
        sys.exit(1)