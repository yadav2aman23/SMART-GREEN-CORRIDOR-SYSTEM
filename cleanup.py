import os
import psycopg2
from datetime import datetime, timedelta

UPLOAD_DIR = "uploads"
RETENTION_DAYS = 7


def get_db_connection():
    return psycopg2.connect(
        host="localhost",
        database="smartgate",
        user="smartgate_user",
        password="SmartGate@123"
    )


def cleanup_old_logs():

    conn = get_db_connection()
    cursor = conn.cursor()

    cutoff = datetime.now() - timedelta(days=RETENTION_DAYS)

    # Find old logs and their photos
    cursor.execute(
        """
        SELECT id, photo_url
        FROM access_logs
        WHERE created_at < %s
        """,
        (cutoff,)
    )

    old_logs = cursor.fetchall()

    for log_id, photo_url in old_logs:

        # Delete photo
        if photo_url and os.path.exists(photo_url):
            os.remove(photo_url)
            print("Deleted photo:", photo_url)

        # Delete database record
        cursor.execute(
            """
            DELETE FROM access_logs
            WHERE id = %s
            """,
            (log_id,)
        )

        print("Deleted log:", log_id)

    conn.commit()

    cursor.close()
    conn.close()

    print("Cleanup completed.")


if __name__ == "__main__":
    cleanup_old_logs()
