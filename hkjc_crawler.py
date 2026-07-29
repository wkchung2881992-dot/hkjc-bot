import asyncio
from datetime import datetime
import os
from apscheduler.schedulers.blocking import BlockingScheduler
import pandas as pd
from playwright.async_api import async_playwright

# 設定目標網址與儲存檔案名稱
TARGET_URL = "https://bet.hkjc.com/ch/racing/wpq/2026-07-28/S1"
CSV_FILE = "hkjc_odds_history.csv"


async def scrape_hkjc_odds():
    """使用 Playwright 抓取 HKJC W (獨贏) & P (位置) 賠率"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] 開始抓取賠率數據...")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        )
        page = await context.new_page()

        try:
            await page.goto(TARGET_URL, wait_until="networkidle", timeout=60000)
            await page.wait_for_timeout(3000)

            rows = await page.query_selector_all("tr.tableRow, tr.td_win_pla")
            scraped_data = []

            for row in rows:
                horse_no_el = await row.query_selector(".horseNo, .td_no")
                horse_name_el = await row.query_selector(".horseName, .td_name")
                win_odds_el = await row.query_selector(".winOdds, .td_win")
                pla_odds_el = await row.query_selector(".plaOdds, .td_pla")

                if horse_no_el and win_odds_el:
                    horse_no = (await horse_no_el.inner_text()).strip()
                    horse_name = (
                        (await horse_name_el.inner_text()).strip()
                        if horse_name_el
                        else ""
                    )
                    win_odds = (await win_odds_el.inner_text()).strip()
                    pla_odds = (
                        (await pla_odds_el.inner_text()).strip()
                        if pla_odds_el
                        else "-"
                    )

                    try:
                        win_val = float(win_odds)
                    except ValueError:
                        win_val = None

                    try:
                        pla_val = float(pla_odds)
                    except ValueError:
                        pla_val = None

                    scraped_data.append({
                        "Timestamp": timestamp,
                        "HorseNo": horse_no,
                        "HorseName": horse_name,
                        "WinOdds": win_val,
                        "PlaOdds": pla_val,
                    })

            await browser.close()
            return scraped_data

        except Exception as e:
            print(f"[{timestamp}] 抓取失敗: {e}")
            await browser.close()
            return []


def process_and_save_data(new_data):
    """處理賠率變化並追加寫入 CSV"""
    if not new_data:
        return

    df_new = pd.DataFrame(new_data)

    if os.path.exists(CSV_FILE):
        df_history = pd.read_csv(CSV_FILE)

        first_records = df_history.groupby("HorseNo").first().reset_index()
        overnight_map_win = dict(
            zip(first_records["HorseNo"].astype(str), first_records["WinOdds"])
        )
        overnight_map_pla = dict(
            zip(first_records["HorseNo"].astype(str), first_records["PlaOdds"])
        )

        latest_timestamp = df_history["Timestamp"].max()
        last_records = df_history[df_history["Timestamp"] == latest_timestamp]
        last_map_win = dict(
            zip(last_records["HorseNo"].astype(str), last_records["WinOdds"])
        )
        last_map_pla = dict(
            zip(last_records["HorseNo"].astype(str), last_records["PlaOdds"])
        )

        df_new["Win_Diff_30m"] = df_new.apply(
            lambda r: round(
                r["WinOdds"] - last_map_win.get(str(r["HorseNo"]), r["WinOdds"]), 2
            )
            if r["WinOdds"] is not None
            else 0,
            axis=1,
        )
        df_new["Win_Diff_Overnight"] = df_new.apply(
            lambda r: round(
                r["WinOdds"] - overnight_map_win.get(str(r["HorseNo"]), r["WinOdds"]),
                2,
            )
            if r["WinOdds"] is not None
            else 0,
            axis=1,
        )
        df_new["Pla_Diff_30m"] = df_new.apply(
            lambda r: round(
                r["PlaOdds"] - last_map_pla.get(str(r["HorseNo"]), r["PlaOdds"]), 2
            )
            if r["PlaOdds"] is not None
            else 0,
            axis=1,
        )
        df_new["Pla_Diff_Overnight"] = df_new.apply(
            lambda r: round(
                r["PlaOdds"] - overnight_map_pla.get(str(r["HorseNo"]), r["PlaOdds"]),
                2,
            )
            if r["PlaOdds"] is not None
            else 0,
            axis=1,
        )

        df_new.to_csv(CSV_FILE, mode="a", header=False, index=False)
    else:
        df_new["Win_Diff_30m"] = 0.0
        df_new["Win_Diff_Overnight"] = 0.0
        df_new["Pla_Diff_30m"] = 0.0
        df_new["Pla_Diff_Overnight"] = 0.0
        df_new.to_csv(CSV_FILE, mode="w", header=True, index=False)

    print(f"[{datetime.now().strftime('%H:%M:%S')}] 賠率數據已更新至 {CSV_FILE}")


def job():
    """排程執行的主任務"""
    data = asyncio.run(scrape_hkjc_odds())
    process_and_save_data(data)


if __name__ == "__main__":
    print("=== HKJC 賠率自動監控腳本已啟動 ===")
    job()

    scheduler = BlockingScheduler()
    scheduler.add_job(job, "interval", minutes=30)

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        print("腳本已停止執行。")
