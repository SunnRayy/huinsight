
import requests
import pandas as pd
from datetime import datetime, date
from typing import Optional
import time
import logging
from src.market_data.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

class CNFundMarketDataScraper(BaseScraper):
    """Scraper for Chinese Mutual Fund NAV history from EastMoney/Tiantian Fund."""
    
    BASE_URL = "http://api.fund.eastmoney.com/f10/lsjz"
    # EastMoney serves at most 20 rows per page and returns Data=null for very
    # large page sizes (seen 2026-11-08 with pageSize=2000), so history is paged.
    # see docs/architecture/data-sources.md Change Log
    PAGE_SIZE = 20
    MAX_PAGES = 200  # 4,000 trading days ≈ 16 years; guards against a runaway loop
    
    def fetch_history(self, asset_id: str, start_date: date, end_date: Optional[date] = None) -> pd.DataFrame:
        """
        Fetch historical NAV data for a CN fund.
        
        Args:
            asset_id: Canonical asset ID (e.g. CN_FUND_110020)
            start_date: Start date for data fetch
            end_date: End date (defaults to today)
            
        Returns:
            DataFrame with columns: date, close, currency
        """
        if not asset_id.startswith("CN_FUND_"):
            raise ValueError(f"Invalid asset_id {asset_id}. Must start with CN_FUND_")
            
        fund_code = asset_id.replace("CN_FUND_", "")
        
        if end_date is None:
            end_date = date.today()
            
        # EastMoney API parameters found in typical reverse engineering:
        # callback=jQuery...
        # fundCode=110020
        # pageIndex=1
        # pageSize=2000 (fetch all in one go if possible, or large page)
        # startDate=yyyy-MM-dd
        # endDate=yyyy-MM-dd
        # _=timestamp
        
        headers = {
            "Referer": "http://fund.eastmoney.com/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        
        try:
            from src.utils.http_client import http_get

            # The endpoint returns JSON directly when Referer is set, e.g.
            # http://api.fund.eastmoney.com/f10/lsjz?fundCode=110020&pageIndex=1&pageSize=20&startDate=2024-01-01&endDate=2024-01-30
            lsjz_list: list = []
            total_count: Optional[int] = None
            # Money-market funds (Data.SYType == '每万份收益', FundType 005) report
            # income per 10,000 units in DWJZ and the 7-day yield in LJJZ — neither
            # is a price. Their unit NAV is fixed at 1.00 (the CN ledger trades them
            # at 1.00), so close is recorded as 1.0. Reading DWJZ as a price gave
            # ±100%+ fake 30-day outcomes (2026-11-08).
            # see docs/architecture/data-sources.md Change Log
            is_money_fund = False
            for page_index in range(1, self.MAX_PAGES + 1):
                params = {
                    "fundCode": fund_code,
                    "pageIndex": page_index,
                    "pageSize": self.PAGE_SIZE,
                    "startDate": start_date.strftime("%Y-%m-%d"),
                    "endDate": end_date.strftime("%Y-%m-%d"),
                    "_": int(time.time() * 1000),
                }
                response = http_get(self.BASE_URL, timeout=10, headers=headers, params=params)
                response.raise_for_status()

                data = response.json()

                if data.get("ErrCode") != 0:
                    logger.error(f"API Error for {asset_id}: {data.get('ErrMsg')}")
                    raise ValueError(f"API Error: {data.get('ErrMsg')}")

                data_obj = data.get("Data") or {}
                if page_index == 1:
                    is_money_fund = bool(data_obj.get("SYType"))
                page_rows = data_obj.get("LSJZList") or []
                lsjz_list.extend(page_rows)
                if total_count is None and isinstance(data.get("TotalCount"), int):
                    total_count = data["TotalCount"]
                # Stop on a short/empty page or once every row is collected.
                if len(page_rows) < self.PAGE_SIZE:
                    break
                if total_count is not None and len(lsjz_list) >= total_count:
                    break

            if not lsjz_list:
                logger.warning(f"No data found for {asset_id} in usage range {start_date} to {end_date}")
                return pd.DataFrame(columns=["date", "close", "currency"])
                
            records = []
            for item in lsjz_list:
                # APIs return FSRQ (Date) and DWJZ (NAV)
                nav_date_str = item.get("FSRQ")
                nav_str = item.get("DWJZ")
                
                if not nav_date_str or not nav_str:
                    continue
                    
                records.append({
                    "date": datetime.strptime(nav_date_str, "%Y-%m-%d").date(),
                    "close": 1.0 if is_money_fund else float(nav_str),
                    "currency": "CNY"
                })
                
            df = pd.DataFrame(records)
            if df.empty:
                return pd.DataFrame(columns=["date", "close", "currency"])
                
            # Filter exactly by date range in case API is loose
            mask = (df["date"] >= start_date) & (df["date"] <= end_date)
            df = df[mask].sort_values("date").reset_index(drop=True)
            
            return df[["date", "close", "currency"]]
            
        except requests.RequestException as e:
            logger.error(f"Network error fetching {asset_id}: {e}")
            raise
        except Exception as e:
            logger.error(f"Error parsing data for {asset_id}: {e}")
            raise
