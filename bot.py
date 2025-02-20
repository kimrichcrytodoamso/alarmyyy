import pandas as pd
import requests
import time
from datetime import datetime
from telegram import Bot
import asyncio
import os

class CryptoAlert:
    def __init__(self):
        self.crypto_api_key = os.environ.get('CRYPTO_API_KEY')
        self.telegram_token = os.environ.get('TELEGRAM_TOKEN')
        self.chat_id = os.environ.get('CHAT_ID')
        self.bot = Bot(token=self.telegram_token)
        self.last_alert_times = {}  # timeframe_symbol을 키로 사용
        
    def get_candlestick_data(self, symbol, timeframe):
        url = f"https://min-api.cryptocompare.com/data/v2/histohour"
        params = {
            "fsym": symbol,
            "tsym": "USD",
            "limit": 5,
            "api_key": self.crypto_api_key,
            "aggregate": timeframe  # 2 또는 4
        }
        
        response = requests.get(url, params=params)
        data = response.json()
        
        if data['Response'] == 'Success':
            df = pd.DataFrame(data['Data']['Data'])
            df['time'] = pd.to_datetime(df['time'], unit='s')
            return df
        else:
            raise Exception(f"API 요청 실패: {data['Message']}")

    async def check_pattern(self, symbol, timeframe):
        df = self.get_candlestick_data(symbol, timeframe)
        timeframe_str = f"{timeframe}시간"
        alert_key = f"{symbol}_{timeframe}"
        
        last_three = df.tail(3)
        if all(last_three['close'] < last_three['open']):
            current_time = datetime.now()
            
            # 모든 타임프레임에 대해 3시간(10800초) 간격 적용
            if (alert_key not in self.last_alert_times or 
                (current_time - self.last_alert_times[alert_key]).total_seconds() > 10800):
                
                entry_price = last_three.iloc[-1]['close']
                drop_percent = ((last_three.iloc[0]['open'] - last_three.iloc[-1]['close']) 
                              / last_three.iloc[0]['open'] * 100)
                
                message = (
                    f"🚨 {symbol} {timeframe_str}봉 3연속 하락 패턴 발견! 🚨\n"
                    f"시간: {current_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"현재 가격: ${entry_price:,.2f}\n"
                    f"하락률: {drop_percent:.2f}%\n"
                    f"타임프레임: {timeframe_str}"
                )
                
                await self.bot.send_message(chat_id=self.chat_id, text=message)
                self.last_alert_times[alert_key] = current_time
                print(f"알림 전송 완료: {symbol} ({timeframe_str}봉)")

    async def run(self):
        symbols = ['BTC', 'ETH', 'XRP']
        timeframes = [2, 4]  # 2시간봉, 4시간봉
        
        print("암호화폐 패턴 감시를 시작합니다...")
        await self.bot.send_message(
            chat_id=self.chat_id, 
            text="🤖 암호화폐 패턴 감시를 시작합니다!\n"
            "모니터링 중: BTC, ETH, XRP\n"
            "타임프레임: 2시간봉, 4시간봉\n"
            "알림 간격: 3시간"
        )
        
        while True:
            try:
                for symbol in symbols:
                    for timeframe in timeframes:
                        await self.check_pattern(symbol, timeframe)
                await asyncio.sleep(60)  # 1분마다 체크
            except Exception as e:
                print(f"오류 발생: {str(e)}")
                await asyncio.sleep(60)

if __name__ == "__main__":
    alert_bot = CryptoAlert()
    asyncio.run(alert_bot.run())
