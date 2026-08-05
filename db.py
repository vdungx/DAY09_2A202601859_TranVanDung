import os
import math
import pandas as pd
import numpy as np

class OlistDB:
    def __init__(self, data_dir="data"):
        self.data_dir = data_dir
        self.orders = None
        self.customers = None
        self.order_items = None
        self.order_payments = None
        self.order_reviews = None
        self.products = None
        self.sellers = None
        self.load_data()

    def load_data(self):
        print("Loading Olist datasets...")
        self.orders = pd.read_csv(os.path.join(self.data_dir, "olist_orders_dataset.csv"))
        self.customers = pd.read_csv(os.path.join(self.data_dir, "olist_customers_dataset.csv"))
        self.order_items = pd.read_csv(os.path.join(self.data_dir, "olist_order_items_dataset.csv"))
        self.order_payments = pd.read_csv(os.path.join(self.data_dir, "olist_order_payments_dataset.csv"))
        self.order_reviews = pd.read_csv(os.path.join(self.data_dir, "olist_order_reviews_dataset.csv"))
        self.products = pd.read_csv(os.path.join(self.data_dir, "olist_products_dataset.csv"))
        self.sellers = pd.read_csv(os.path.join(self.data_dir, "olist_sellers_dataset.csv"))
        print("Datasets loaded successfully.")

    @staticmethod
    def _clean_value(val):
        """Convert NaN/NaT to None for JSON-safe output."""
        if val is None:
            return None
        if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
            return None
        if isinstance(val, (pd.Timestamp, np.datetime64)):
            return str(val)
        if isinstance(val, (np.integer,)):
            return int(val)
        if isinstance(val, (np.floating,)):
            return float(val)
        return val

    @staticmethod
    def _clean_dict(d):
        """Recursively clean a dict of NaN values."""
        return {k: OlistDB._clean_value(v) for k, v in d.items()}

    def get_order_details(self, order_id):
        """
        Retrieves all database facts related to a specific order_id.
        All NaN values are converted to None for JSON safety.
        Returns a dict containing:
        - order: dict or None
        - customer: dict or None
        - items: list of dicts
        - payments: list of dicts
        - reviews: list of dicts
        """
        # Find order
        order_df = self.orders[self.orders["order_id"] == order_id]
        if order_df.empty:
            return None

        order_dict = self._clean_dict(order_df.iloc[0].to_dict())

        # Find customer
        customer_id = order_dict.get("customer_id")
        customer_df = self.customers[self.customers["customer_id"] == customer_id]
        customer_dict = self._clean_dict(customer_df.iloc[0].to_dict()) if not customer_df.empty else None

        # Find order items and join product info
        items_df = self.order_items[self.order_items["order_id"] == order_id]
        items_list = []
        for _, row in items_df.iterrows():
            item = self._clean_dict(row.to_dict())
            prod_id = item.get("product_id")
            if prod_id:
                prod_df = self.products[self.products["product_id"] == prod_id]
                if not prod_df.empty:
                    item["product"] = self._clean_dict(prod_df.iloc[0].to_dict())
            items_list.append(item)

        # Find order payments
        payments_df = self.order_payments[self.order_payments["order_id"] == order_id]
        payments_list = [self._clean_dict(row.to_dict()) for _, row in payments_df.iterrows()]

        # Find reviews
        reviews_df = self.order_reviews[self.order_reviews["order_id"] == order_id]
        reviews_list = [self._clean_dict(row.to_dict()) for _, row in reviews_df.iterrows()]

        return {
            "order": order_dict,
            "customer": customer_dict,
            "items": items_list,
            "payments": payments_list,
            "reviews": reviews_list
        }

if __name__ == "__main__":
    # Simple self-test
    db = OlistDB()
    test_order = db.get_order_details("e481f51cbdc54678b7cc49136f2d6af7")
    import json
    print(json.dumps(test_order, indent=2, ensure_ascii=False, default=str))
