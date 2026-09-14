"""
Create missing database partitions for OHLC data
Run this when you get "no partition found" errors
"""

import asyncio
from datetime import datetime, timedelta
from models.database import db


async def create_partitions():
    """Create monthly partitions for the next 12 months"""

    await db.connect()
    print("Creating missing OHLC data partitions...")

    # Start from 2 months ago to cover any historical data, then next 12 months
    current_date = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    start_date = current_date - timedelta(days=60)  # Go back 2 months
    start_date = start_date.replace(day=1)

    for i in range(14):  # 2 past months + 12 future months
        partition_date = start_date + timedelta(days=32 * i)
        partition_date = partition_date.replace(day=1)

        # Calculate next month
        if partition_date.month == 12:
            next_month = partition_date.replace(year=partition_date.year + 1, month=1)
        else:
            next_month = partition_date.replace(month=partition_date.month + 1)

        partition_name = f"ohlc_data_{partition_date.strftime('%Y_%m')}"

        # Check if partition exists
        check_query = """
            SELECT EXISTS (
                SELECT FROM pg_tables
                WHERE tablename = $1
            );
        """
        result = await db.fetch(check_query, partition_name)
        exists = result[0]['exists'] if result else False

        if not exists:
            # Create partition
            create_query = f"""
                CREATE TABLE IF NOT EXISTS {partition_name}
                PARTITION OF ohlc_data
                FOR VALUES FROM ('{partition_date.strftime('%Y-%m-%d')}')
                TO ('{next_month.strftime('%Y-%m-%d')}');
            """

            try:
                await db.execute(create_query)
                print(f"[OK] Created partition: {partition_name} ({partition_date.strftime('%Y-%m')})")
            except Exception as e:
                print(f"[ERROR] Failed to create {partition_name}: {e}")
        else:
            print(f"[SKIP] Partition already exists: {partition_name}")

    await db.disconnect()
    print("\n[DONE] Partition creation complete!")


if __name__ == "__main__":
    asyncio.run(create_partitions())
