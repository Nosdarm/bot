import psycopg2

def test_connection():
    conn_string = "postgresql://postgres:test123@localhost:5433/kvelin_bot"
    try:
        conn = psycopg2.connect(conn_string)
        print("Successfully connected to the PostgreSQL database!")
        conn.close()
    except Exception as e:
        print(f"Error connecting to the PostgreSQL database: {e}")

if __name__ == "__main__":
    test_connection()
