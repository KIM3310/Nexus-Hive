import sqlite3
import pandas as pd
import random
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "nexus_enterprise.db"


def generate_data():
    print("Initializing Nexus-Hive Enterprise Data Synthesis...")

    # 1. Products Table
    categories = ["Electronics", "Software", "Consulting", "Hardware", "Cloud Services"]
    products = []
    for i in range(1, 51):
        category = random.choice(categories)
        base_price = round(random.uniform(500, 50000), 2)
        products.append(
            {
                "product_id": i,
                "product_name": f"Enterprise {category} Pro V{random.randint(1, 4)}",
                "category": category,
                "unit_price": base_price,
                "margin_percentage": round(random.uniform(0.15, 0.60), 2),
            }
        )
    df_products = pd.DataFrame(products)

    # 2. Regions Table
    regions = [
        {"region_id": 1, "region_name": "North America", "manager": "Sarah Jenkins"},
        {"region_id": 2, "region_name": "EMEA", "manager": "Marcus Oberg"},
        {"region_id": 3, "region_name": "APAC", "manager": "Kenji Sato"},
        {"region_id": 4, "region_name": "LATAM", "manager": "Maria Garcia"},
    ]
    df_regions = pd.DataFrame(regions)

    # 3. Sales Table (10,000 rows over the last 2 years)
    print("Generating 10,000 historical sales transactions...")
    sales = []
    start_date = datetime.now() - timedelta(days=730)

    for i in range(1, 10001):
        product = random.choice(products)
        region = random.choice(regions)
        qty = random.randint(1, 50)

        # Add seasonality (Q4 boost)
        random_days = random.randint(0, 730)
        sale_date = start_date + timedelta(days=random_days)
        if sale_date.month in [11, 12]:
            qty = int(qty * random.uniform(1.2, 2.0))

        discount = round(random.uniform(0.0, 0.25), 2) if random.random() > 0.7 else 0.0

        gross_revenue = product["unit_price"] * qty
        net_revenue = gross_revenue * (1 - discount)
        profit = net_revenue * product["margin_percentage"]

        sales.append(
            {
                "transaction_id": f"TXN-{100000 + i}",
                "date": sale_date.strftime("%Y-%m-%d"),
                "product_id": product["product_id"],
                "region_id": region["region_id"],
                "quantity": qty,
                "discount_applied": discount,
                "gross_revenue": round(gross_revenue, 2),
                "net_revenue": round(net_revenue, 2),
                "profit": round(profit, 2),
            }
        )

    df_sales = pd.DataFrame(sales)

    # Save to SQLite
    if DB_PATH.exists():
        DB_PATH.unlink()

    print(f"Saving to SQLite database: {DB_PATH}")
    with sqlite3.connect(DB_PATH) as conn:
        df_products.to_sql("products", conn, index=False)
        df_regions.to_sql("regions", conn, index=False)
        df_sales.to_sql("sales", conn, index=False)

    print("Database synthesis complete.")
    print(f"Total Sales Records: {len(df_sales)}")
    print(f"Total Revenue Simulated: ${df_sales['net_revenue'].sum():,.2f}")


if __name__ == "__main__":
    generate_data()
