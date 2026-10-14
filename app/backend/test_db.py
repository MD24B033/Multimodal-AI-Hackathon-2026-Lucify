from sqlalchemy import text

from app.db.database import engine


print("Testing PostgreSQL connection...")

try:
    with engine.connect() as connection:
        result = connection.execute(text("SELECT current_user, current_database();"))
        user, database = result.fetchone()

        print("Database connection successful!")
        print("User:", user)
        print("Database:", database)

except Exception as e:
    print("Database connection failed:")
    print(e)