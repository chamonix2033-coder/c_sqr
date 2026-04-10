import os
import time
import pandas as pd
from datetime import datetime
from dateutil.relativedelta import relativedelta
from playwright.sync_api import sync_playwright

# 設定
AUTH_FILE = "auth.json"
START_DATE = datetime(2025,11, 1)
END_DATE = datetime(2026, 3, 1)
BASE_URL = "https://www.c-sqr.net"
OUTPUT_CSV = "events_attendance.csv"

def get_event_links(page, url, date_str):
    print(f"URLにアクセス中: {url}")
    # load 待ちに変更し、その後セレクタで待機することでタイムアウトを防ぐ
    page.goto(url, wait_until="load", timeout=30000)
    try:
        page.wait_for_selector(".ul_c-main-index__has-respond-status, .c-list-box__link-wrap", timeout=10000)
    except:
        pass # イベントがない月などの対応
    
    if "/login" in page.url:
        print(f"警告: ログイン画面にリダイレクトされました。")
        return []

    try:
        # 確実に表示されるまで少し待機（セレクタが不明なため汎用的な待機）
        page.wait_for_timeout(3000)
        
        # イベント一覧の各項目アイテムを取得
        list_items = page.locator("li:has(.c-list-box__link-wrap)").all()
        
        events_found = []
        seen_urls = set()
        for item in list_items:
            try:
                # イベントURL (出欠画面) の取得
                attend_link_elem = item.locator(".c-respond-status a").first
                if attend_link_elem.count() > 0:
                    href = attend_link_elem.get_attribute("href")
                    attends_url = href if href.startswith("http") else f"{BASE_URL}{href}"
                else:
                    # c-respond-status a が無い場合のフォールバック処理
                    link_elem = item.locator(".c-list-box__link-wrap").first
                    href = link_elem.get_attribute("href")
                    if not href: 
                        continue
                    full_url = href if href.startswith("http") else f"{BASE_URL}{href}"
                    
                    if "/event_rules/" in full_url:
                        parts = full_url.split("?")
                        base_path = parts[0]
                        query = "?" + parts[1] if len(parts) > 1 else ""
                        attends_url = f"{base_path}/event_rule_attends{query}"
                    else:
                        if "?" in full_url:
                            parts = full_url.split("?")
                            base_path = parts[0]
                            query = "?" + parts[1] if len(parts) > 1 else ""
                            attends_url = f"{base_path}/attends{query}"
                        else:
                            attends_url = full_url if full_url.endswith("/attends") else f"{full_url}/attends"
                            
                if attends_url in seen_urls:
                    continue
                seen_urls.add(attends_url)

                # イベント名
                title_elem = item.locator(".c-list-box__title")
                event_name = title_elem.inner_text().strip() if title_elem.count() > 0 else "不明なイベント名"
                
                # イベント日時
                clock_elem = item.locator(".icon-clock")
                if clock_elem.count() > 0:
                    parent_elem = clock_elem.first.locator("..")
                    event_datetime = parent_elem.inner_text().strip()
                else:
                    event_datetime = "不明"
                # イベントカテゴリ
                category_elem = item.locator(".c-marks")
                event_category = category_elem.first.inner_text().strip() if category_elem.count() > 0 else ""
                    
                events_found.append({
                    "url": attends_url,
                    "name": event_name,
                    "category": event_category,
                    "datetime": event_datetime
                })
            except Exception as e:
                continue
                
        return events_found
    except Exception as e:
        screenshot_path = f"error_timeout_{date_str}.png"
        page.screenshot(path=screenshot_path)
        print(f"{date_str} の待機中にエラーが発生しました: {e}")
        return []

def scrape_event_detail(page, event_url, event_name, event_category, datetime_text):
    print(f"イベント詳細を取得中: {event_name} ({event_url})")
    try:
        page.goto(event_url, wait_until="load", timeout=30000)
    except Exception as e:
        print(f"ページ読み込みに失敗しました ({event_url}): {e}")
        return []

    # 「出欠」タブへの切り替え、またはVueコンポーネントの読み込み待機
    try:
        tab = page.locator("a:has-text(\"出欠\"), a:has-text(\"回答一覧\"), a:has-text(\"出欠確認\")").first
        if tab.count() > 0:
            tab.click()
            
        # Vue.jsで生成されるテーブル要素、リスト要素、または「表示する」等のボタンが現れるまで待つ
        page.wait_for_selector(".table_p-event-attend-list, .c-list-unit, .p-event-attendance-list, :text('表示する'), :text('全て表示する'), :text('すべて表示する')", timeout=10000)
        
        # 「表示する」系のボタンが出現した場合はクリックして全件読み込む
        # タグ名を問わず、テキストベースで探す
        show_all_selectors = [
            "button:has-text('表示する')", 
            "button:has-text('全て表示する')", 
            "button:has-text('すべて表示する')",
            "a:has-text('表示する')",
            "a:has-text('全て表示する')",
            ".c-btn:has-text('表示する')",
            ":text('全て表示する')"
        ]
        
        for selector in show_all_selectors:
            btn = page.locator(selector).first
            if btn.count() > 0 and btn.is_visible():
                print(f"  -> '{selector}' ボタンをクリックして全件表示します...")
                btn.click()
                page.wait_for_timeout(4000) # ロード待ちを少し長めに
                break
        
        # ネットワークの通信が終わるまでさらに少し待つ（Vue.jsのAPIフェッチ完了待ち）
        page.wait_for_timeout(2000)
    except Exception as e:
        pass

    attendance_data = []

    # 新UI (Vue.js の table_p-event-attend-list 形式) の取得
    table_rows = page.locator(".table_p-event-attend-list tr").all()
    if table_rows and len(table_rows) > 1:
        # 最初の行はヘッダーなのでスキップする
        for row in table_rows[1:]:
            try:
                # 名前 (thの中にあるテキスト。<a>タグが無いゲスト等にも対応)
                name_elem = row.locator("th")
                if name_elem.count() > 0:
                    name_text = name_elem.first.inner_text().strip()
                    # 改行が含まれる場合（会員IDなど）、末尾の名前部分だけを抽出する
                    name = name_text.split('\n')[-1].strip() if name_text else "不明"
                else:
                    name = "不明"
                
                if name == "不明":
                    continue # ヘッダー行など空データのスキップ
                
                # 出欠ステータス (aria-label属性から取得)
                status_elem = row.locator(".table_p-event-attend-list__attend-or-not span[aria-label]")
                status = status_elem.get_attribute("aria-label").strip() if status_elem.count() > 0 else "未回答"
                
                # 更新日時
                updated_elem = row.locator(".table_p-event-attend-list__timestamp")
                updated_at = updated_elem.inner_text().replace('\n', ' ').strip() if updated_elem.count() > 0 else ""
                
                attendance_data.append({
                    "event_name": event_name,
                    "category": event_category,
                    "event_datetime": datetime_text,
                    "user_name": name,
                    "status": status,
                    "updated_at": updated_at
                })
            except Exception as e:
                continue
    else:
        # 旧UI (.c-list-unit) へのフォールバック
        units = page.locator(".c-list-unit").all()

        for unit in units:
            try:
                name_elem = unit.locator(".c-list-unit__title")
                name = name_elem.inner_text().strip() if name_elem.count() > 0 else "不明"
                
                status_elem = unit.locator(".c-list-unit__label, .c-label")
                status = status_elem.first.inner_text().replace("\n", " ").strip() if status_elem.count() > 0 else "未回答"
                
                meta_elem = unit.locator(".c-list-unit__meta")
                updated_at = meta_elem.inner_text().strip() if meta_elem.count() > 0 else ""
                
                attendance_data.append({
                    "event_name": event_name,
                    "category": event_category,
                    "event_datetime": datetime_text,
                    "user_name": name,
                    "status": status,
                    "updated_at": updated_at
                })
            except:
                continue
            
    if not attendance_data:
        # 回答者が一人もいない場合や、全員がスキップされた場合のダミー行
        attendance_data.append({
            "event_name": event_name,
            "category": event_category,
            "event_datetime": datetime_text,
            "user_name": "（回答者なし）",
            "status": "",
            "updated_at": ""
        })
        
    return attendance_data

def main():
    if not os.path.exists(AUTH_FILE):
        print(f"エラー: {AUTH_FILE} が見つかりません。")
        return

    all_data = []
    processed_urls = set()
    
    with sync_playwright() as p:
        print("ブラウザを起動しています...")
        chrome_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        launch_args = ["--no-sandbox", "--disable-setuid-sandbox", "--disable-gpu"]
        
        try:
            if os.path.exists(chrome_path):
                browser = p.chromium.launch(executable_path=chrome_path, headless=True, args=launch_args)
            else:
                browser = p.chromium.launch(headless=True, args=launch_args)
        except Exception as e:
            print(f"ブラウザ起動エラー: {e}")
            return

        context = browser.new_context(storage_state=AUTH_FILE)
        page = context.new_page()
        
        current_date = START_DATE
        while current_date <= END_DATE:
            date_str = current_date.strftime("%Y-%m-%d")
            url = f"{BASE_URL}/events/list?show_all=0&date={date_str}"
            
            event_infos = get_event_links(page, url, date_str)
            print(f"{date_str}: {len(event_infos)} 件のイベントを検出しました。")
            
            for event_info in event_infos:
                if event_info["url"] in processed_urls:
                    print(f"  既に処理済みのURLのためスキップします: {event_info['name']}")
                    continue
                processed_urls.add(event_info["url"])
                
                event_data = scrape_event_detail(page, event_info["url"], event_info["name"], event_info["category"], event_info["datetime"])
                if event_data:
                    all_data.extend(event_data)
                time.sleep(1) # イベントごとの待機
            
            current_date += relativedelta(months=1)
            time.sleep(1)

        browser.close()

    if all_data:
        df = pd.DataFrame(all_data)
        print("\n=== 取得データサマリー ===")
        print(df.head())
        df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
        print(f"\n合計 {len(df)} 件の回答データを {OUTPUT_CSV} に保存しました。")
    else:
        print("データが取得されませんでした。ログイン状態、またはイベントの有無を確認してください。")

if __name__ == "__main__":
    main()
