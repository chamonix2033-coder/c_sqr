import os
import sys
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

# .env ファイルから環境変数を読み込む
load_dotenv()

USER_ID = os.getenv("CSQR_USER_ID")
PASSWORD = os.getenv("CSQR_PASSWORD")

def login():
    if not USER_ID or not PASSWORD:
        print("Error: CSQR_USER_ID または CSQR_PASSWORD が .env ファイルに設定されていません。")
        print(".env.example を参考に .env ファイルを作成してください。")
        sys.exit(1)

    with sync_playwright() as p:
        print("ブラウザを起動しています...")
        # システムのGoogle Chromeを使用してみる（macOS Sequoia環境での起動エラー対策）
        chrome_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        launch_args = ["--no-sandbox", "--disable-setuid-sandbox"]
        
        try:
            if os.path.exists(chrome_path):
                print(f"システムChromeを使用します: {chrome_path}")
                browser = p.chromium.launch(executable_path=chrome_path, headless=True, args=launch_args)
            else:
                browser = p.chromium.launch(headless=True, args=launch_args)
        except Exception as e:
            print(f"ブラウザの起動に失敗しました: {e}")
            sys.exit(1)
        
        print("ブラウザが起動しました。")
        
        context = browser.new_context()
        page = context.new_page()
        
        print("ログインページにアクセスしています...")
        page.goto("https://www.c-sqr.net/login")
        
        print("認証情報を入力しています...")
        page.fill("#account", USER_ID)
        page.fill("#password", PASSWORD)
        
        print("ログインボタンをクリックしています...")
        # ボタンのクリック
        page.click(".p-public-form__login")
        
        # ログイン後の遷移を待機（ダッシュボード等の出現を確認するのが確実）
        # 这里使用 wait_for_url または特定の要素を待機
        try:
            # ログイン成功時に現れる可能性のある要素やURLを待機
            page.wait_for_timeout(5000) # 簡易的な待機
            
            print("認証状態を保存しています (auth.json)...")
            context.storage_state(path="auth.json")
            print("保存が完了しました。")
            
        except Exception as e:
            print(f"エラーが発生しました: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    login()
