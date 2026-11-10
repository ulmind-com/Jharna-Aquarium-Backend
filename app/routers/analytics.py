from datetime import datetime, timezone
from collections import defaultdict
from fastapi import APIRouter, Depends
from app.db.mongodb import get_db
from app.deps import require_admin
from app.models.common import to_object_id

router = APIRouter(prefix="/analytics", tags=["analytics"])

@router.get("/dashboard", dependencies=[Depends(require_admin)])
async def get_dashboard_analytics():
    db = get_db()
    # Total Revenue & Orders — excludes cancelled orders AND "ghost" online
    # orders that were never actually paid (razorpay_payment_id never set,
    # e.g. an abandoned checkout). Same exclusion already used by
    # /orders/admin/all and /orders (my_orders) — keeps every admin-facing
    # number consistent with what a real, paid order means.
    no_ghosts = {"$nor": [{"payment_method": "online", "razorpay_payment_id": None}]}
    orders = await db.orders.find({"status": {"$ne": "cancelled"}, **no_ghosts}).to_list(length=10000)
    
    total_revenue = 0.0
    total_orders = len(orders)
    
    # Trackers for aggregation
    product_sales = defaultdict(int)
    category_revenue = defaultdict(float)
    monthly_sales = defaultdict(float)
    
    # Collect all unique product IDs first to avoid N+1 queries
    product_ids_to_fetch = set()
    for order in orders:
        for item in order.get("items", []):
            if pid := item.get("product_id"):
                product_ids_to_fetch.add(to_object_id(pid))
    
    # Pre-fetch all products in one query
    products_cache = {}
    if product_ids_to_fetch:
        all_products = await db.products.find({"_id": {"$in": list(product_ids_to_fetch)}}).to_list(length=None)
        products_cache = {str(p["_id"]): p for p in all_products}
    
    for order in orders:
        amount = order.get("amount", 0)
        total_revenue += amount
        
        # Monthly trend (YYYY-MM)
        created_at = order.get("created_at")
        if created_at:
            month_key = created_at.strftime("%Y-%m")
            monthly_sales[month_key] += amount
            
        # Items processing
        for item in order.get("items", []):
            pid = item.get("product_id")
            if not pid: continue
            
            qty = item.get("qty", 0)
            price = item.get("price", 0)
            line_total = qty * price
            
            product_sales[pid] += qty
            
            p = products_cache.get(pid)
            if p:
                cat_id = p.get("category_id")
                if cat_id:
                    category_revenue[cat_id] += line_total
                    
    # Format top products (Top 10)
    top_products_list = []
    for pid, qty in product_sales.items():
        p = products_cache.get(pid)
        if p:
            top_products_list.append({
                "product_id": pid,
                "title": p.get("title"),
                "qty": qty,
                "image": (p.get("images") or [None])[0]
            })
    top_products_list.sort(key=lambda x: x["qty"], reverse=True)
    
    # Format category revenue (fetch category names)
    cat_rev_list = []
    if category_revenue:
        cat_ids = list(category_revenue.keys())
        categories = await db.categories.find({"_id": {"$in": [to_object_id(cid) for cid in cat_ids]}}).to_list(length=100)
        cat_map = {str(c["_id"]): c.get("name") for c in categories}
        
        for cid, rev in category_revenue.items():
            cat_rev_list.append({
                "category_id": cid,
                "name": cat_map.get(cid, "Unknown"),
                "revenue": rev
            })
    cat_rev_list.sort(key=lambda x: x["revenue"], reverse=True)
    
    # Format monthly sales chronologically
    sales_trend = [{"month": k, "revenue": v} for k, v in monthly_sales.items()]
    sales_trend.sort(key=lambda x: x["month"])
    
    return {
        "total_revenue": total_revenue,
        "total_orders": total_orders,
        "top_products": top_products_list[:10],
        "category_revenue": cat_rev_list,
        "sales_trend": sales_trend
    }
