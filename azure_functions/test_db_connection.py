import os
import psycopg2
import sys

# 从环境变量获取连接字符串
# 为了手动测试方便，您也可以直接在这里粘贴您的连接字符串
# 例如：CONNECTION_STRING = "postgresql://youradmin:YourActualStrongPassword!@..."
CONNECTION_STRING = os.environ.get("DATABASE_CONNECTION_STRING")

def test_connection():
    if not CONNECTION_STRING:
        print("错误：环境变量 'DATABASE_CONNECTION_STRING' 未设置。请设置后再运行。")
        sys.exit(1)

    print(f"尝试连接到 PostgreSQL 数据库...")
    print(f"连接字符串（为安全考虑，密码已隐藏）：{CONNECTION_STRING.split(':')[0]}://***:***@{CONNECTION_STRING.split('@')[1]}")

    try:
        # 尝试建立连接
        conn = psycopg2.connect(CONNECTION_STRING)
        cursor = conn.cursor()

        # 尝试执行一个简单的查询来验证连接和认证
        cursor.execute("SELECT version();")
        db_version = cursor.fetchone()
        print(f"连接成功！数据库版本：{db_version[0]}")

        # 关闭连接
        cursor.close()
        conn.close()
        print("数据库连接已成功关闭。")
        return True

    except psycopg2.OperationalError as e:
        print(f"连接失败：{e}", file=sys.stderr)
        if "password authentication failed" in str(e):
            print("错误原因：密码认证失败。请检查用户名和密码是否正确。", file=sys.stderr)
        elif "could not connect to server" in str(e):
            print("错误原因：无法连接到服务器。请检查：", file=sys.stderr)
            print("  1. 服务器地址和端口是否正确。", file=sys.stderr)
            print("  2. 防火墙规则是否允许您的当前IP访问。", file=sys.stderr)
            print("  3. 数据库服务是否正在运行。", file=sys.stderr)
        return False
    except Exception as e:
        print(f"发生未知错误：{e}", file=sys.stderr)
        return False

if __name__ == "__main__":
    # 方法一：在命令行中设置环境变量（推荐，避免代码硬编码敏感信息）
    # Windows PowerShell: $env:DATABASE_CONNECTION_STRING="postgresql://..." ; python test_db_connection.py
    # Linux/macOS: export DATABASE_CONNECTION_STRING="postgresql://..." ; python3 test_db_connection.py

    # 方法二：直接在这里粘贴您的连接字符串（用于快速测试，完成后请删除或注释掉）
    # CONNECTION_STRING = "postgresql://youradmin:YourActualStrongPassword!@rg-finops-ri-reporting-dev-dev-pgsql-finopst.postgres.database.azure.com:5432/ri_finops_db?sslmode=require"
    # 请将 'YourActualStrongPassword!' 替换为您的实际密码

    test_connection()