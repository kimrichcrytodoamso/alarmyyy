import pandas as pd
import requests
import time
from datetime import datetime, timedelta
from telegram import Bot
import asyncio
import os

class CryptoAlert:
    def __init__(self):
        self.crypto_api_key = os.environ.get('CRYPTO_API_KEY')
        self.telegram_token = os.environ.get('TELEGRAM_TOKEN')
        self.chat_id = os.environ.get('CHAT_ID')
        self.bot = Bot(token=self.telegram_token)
        self.last_alert_times = {}
        self.pre_candle_alerts = {}  # 캔들 시작 전 알림을 위한 추적
        
    def get_candlestick_data(self, symbol, timeframe):
        url = f"https://min-api.cryptocompare.com/data/v2/histohour"
        params = {
            "fsym": symbol,
            "tsym": "USD",
            "limit": 5,
            "api_key": self.crypto_api_key,
            "aggregate": timeframe
        }
        
        response = requests.get(url, params=params)
        data = response.json()
        
        if data['Response'] == 'Success':
            df = pd.DataFrame(data['Data']['Data'])
            df['time'] = pd.to_datetime(df['time'], unit='s')
            return df
        else:
            raise Exception(f"API 요청 실패: {data['Message']}")

    def get_next_candle_time(self, timeframe):
        current_time = datetime.now()
        hours_since_start = current_time.hour
        current_period = (hours_since_start // timeframe) * timeframe
        next_period = current_period + timeframe
        next_candle = current_time.replace(hour=next_period, minute=0, second=0, microsecond=0)
        
        if next_period >= 24:
            next_candle = next_candle + timedelta(days=1)
            next_candle = next_candle.replace(hour=next_period % 24)
        
        return next_candle

    async def check_pattern(self, symbol, timeframe):
        df = self.get_candlestick_data(symbol, timeframe)
        timeframe_str = f"{timeframe}시간"
        alert_key = f"{symbol}_{timeframe}"
        
        # 3연속 하락 패턴 체크
        last_three = df.tail(3)
        if all(last_three['close'] < last_three['open']):
            current_time = datetime.now()
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

        # 2연속 하락 후 다음 캔들 시작 전 알림 체크
        last_two = df.tail(2)
        if all(last_two['close'] < last_two['open']):
            next_candle_time = self.get_next_candle_time(timeframe)
            current_time = datetime.now()
            time_to_next = (next_candle_time - current_time).total_seconds() / 60  # 분 단위

            pre_alert_key = f"pre_{symbol}_{timeframe}"
            
            # 다음 캔들 시작 5분 전이고 아직 알림을 보내지 않았다면
            if (4.5 <= time_to_next <= 5.5 and 
                (pre_alert_key not in self.pre_candle_alerts or 
                 self.pre_candle_alerts[pre_alert_key] != next_candle_time)):
                
                entry_price = last_two.iloc[-1]['close']
                message = (
                    f"⚠️ {symbol} {timeframe_str}봉 주의! ⚠️\n"
                    f"2연속 하락 발생, 다음 캔들 시작 5분 전\n"
                    f"현재 시간: {current_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"다음 캔들 시작: {next_candle_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"현재 가격: ${entry_price:,.2f}\n"
                    f"타임프레임: {timeframe_str}"
                )
                
                await self.bot.send_message(chat_id=self.chat_id, text=message)
                self.pre_candle_alerts[pre_alert_key] = next_candle_time

    async def run(self):
        symbols = ['BTC', 'ETH', 'XRP']
        timeframes = [2, 4]
        
        print("암호화폐 패턴 감시를 시작합니다...")
        await self.bot.send_message(
            chat_id=self.chat_id, 
            text="🤖 암호화폐 패턴 감시를 시작합니다!\n"
            "모니터링 중: BTC, ETH, XRP\n"
            "타임프레임: 2시간봉, 4시간봉\n"
            "알림 유형:\n"
            "1. 3연속 하락 패턴 (3시간 간격)\n"
            "2. 2연속 하락 후 다음 캔들 5분 전 알림"
        )
        
        while True:
            try:
                for symbol in symbols:
                    for timeframe in timeframes:
                        await self.check_pattern(symbol, timeframe)
                await asyncio.sleep(30)  # 30초마다 체크
            except Exception as e:
                print(f"오류 발생: {str(e)}")
                await asyncio.sleep(30)

if __name__ == "__main__":
    alert_bot = CryptoAlert()
    asyncio.run(alert_bot.run())
