import pandas as pd
import requests
import time
from datetime import datetime
from telegram import Bot
import os

class CryptoAlert:
    def __init__(self):
        self.crypto_api_key = os.environ.get('CRYPTO_API_KEY')
        self.telegram_token = os.environ.get('TELEGRAM_TOKEN')
        self.chat_id = os.environ.get('CHAT_ID')
        self.bot = Bot(token=self.telegram_token)
        self.last_alert_times = {}
        
    def get_candlestick_data(self, symbol):
        url = f"https://min-api.cryptocompare.com/data/v2/histohour"
        params = {
            "fsym": symbol,
            "tsym": "USD",
            "limit": 5,
            "api_key": self.crypto_api_key,
            "aggregate": 4
        }
        
        response = requests.get(url, params=params)
        data = response.json()
        
        if data['Response'] == 'Success':
            df = pd.DataFrame(data['Data']['Data'])
            df['time'] = pd.to_datetime(df['time'], unit='s')
            return df
        else:
            raise Exception(f"API 요청 실패: {data['Message']}")

    def check_pattern(self, symbol):
        df = self.get_candlestick_data(symbol)
        
        last_three = df.tail(3)
        if all(last_three['close'] < last_three['open']):
            current_time = datetime.now()
            
            if (symbol not in self.last_alert_times or 
                (current_time - self.last_alert_times[symbol]).total_seconds() > 14400):
                
                entry_price = last_three.iloc[-1]['close']
                message = (
                    f"🚨 {symbol} 3연속 하락 패턴 발견! 🚨\n"
                    f"시간: {current_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"현재 가격: ${entry_price:,.2f}"
                )
                
                self.bot.send_message(chat_id=self.chat_id, text=message)
                self.last_alert_times[symbol] = current_time
                print(f"알림 전송 완료: {symbol}")

    def run(self):
        symbols = ['BTC', 'ETH', 'XRP']
        
        print("암호화폐 패턴 감시를 시작합니다...")
        self.bot.send_message(
            chat_id=self.chat_id, 
            text="🤖 암호화폐 패턴 감시를 시작합니다!\n모니터링 중: BTC, ETH, XRP"
        )
        
        while True:
            try:
                for symbol in symbols:
                    self.check_pattern(symbol)
                time.sleep(60)
            except Exception as e:
                print(f"오류 발생: {str(e)}")
                time.sleep(60)

if __name__ == "__main__":
    alert_bot = CryptoAlert()
    alert_bot.run()
