import pandas as pd
import requests
import time
from datetime import datetime, timedelta
import pytz
from telegram import Bot
import asyncio
import os
import sys
import logging

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("CryptoAlert")

class CryptoAlert:
    def __init__(self):
        # 환경 변수 확인
        self.crypto_api_key = os.environ.get('CRYPTO_API_KEY')
        self.telegram_token = os.environ.get('TELEGRAM_TOKEN')
        self.chat_id = os.environ.get('CHAT_ID')
        
        # 필수 환경 변수 확인
        if not self.crypto_api_key:
            logger.error("CRYPTO_API_KEY 환경 변수가 설정되지 않았습니다.")
            sys.exit(1)
        if not self.telegram_token:
            logger.error("TELEGRAM_TOKEN 환경 변수가 설정되지 않았습니다.")
            sys.exit(1)
        if not self.chat_id:
            logger.error("CHAT_ID 환경 변수가 설정되지 않았습니다.")
            sys.exit(1)
            
        self.bot = Bot(token=self.telegram_token)
        self.last_alert_times = {}  # 알림 반복 방지를 위한 마지막 알림 시간 저장
        self.pre_candle_alerts = {}  # 사전 알림 저장
        self.error_wait_time = 0  # API 요율 제한 시 대기 시간
        
        logger.info("CryptoAlert 초기화 완료")
        
    async def fetch_candlestick_data(self, symbol, timeframe_hours):
        """
        암호화폐 캔들 데이터를 가져옵니다.
        
        Args:
            symbol (str): 암호화폐 심볼 (BTC, ETH 등)
            timeframe_hours (int): 타임프레임 (시간 단위)
            
        Returns:
            DataFrame: 캔들 데이터가 포함된 데이터프레임
        """
        url = "https://min-api.cryptocompare.com/data/v2/histohour"
        params = {
            "fsym": symbol,
            "tsym": "USD",
            "limit": 10,  # 패턴 감지를 위해 충분한 캔들 데이터
            "api_key": self.crypto_api_key,
            "aggregate": timeframe_hours
        }
        
        logger.info(f"{symbol} {timeframe_hours}시간봉 데이터 요청 중...")
        
        try:
            response = requests.get(url, params=params, timeout=30)
            data = response.json()
            
            if data['Response'] == 'Success':
                # 데이터 변환 및 타임존 설정
                df = pd.DataFrame(data['Data']['Data'])
                df['time'] = pd.to_datetime(df['time'], unit='s').dt.tz_localize('UTC')
                
                # 필요한 컬럼만 선택 및 정렬
                df = df[['time', 'open', 'high', 'low', 'close', 'volumefrom', 'volumeto']]
                df = df.sort_values('time')
                
                # 하락 캔들 여부 표시
                df['is_bearish'] = df['close'] < df['open']
                
                logger.info(f"{symbol} {timeframe_hours}시간봉 데이터 {len(df)}개 가져옴")
                logger.info(f"가장 최근 캔들: {df['time'].iloc[-1]}")
                
                return df
            else:
                error_msg = f"API 요청 실패: {data.get('Message', '알 수 없는 오류')}"
                logger.error(error_msg)
                raise Exception(error_msg)
                
        except Exception as e:
            logger.error(f"데이터 요청 중 오류 발생: {str(e)}")
            raise

    def is_candle_complete(self, candle_time, timeframe_hours):
        """
        캔들이 완료되었는지 확인합니다.
        
        Args:
            candle_time (datetime): 캔들 시작 시간
            timeframe_hours (int): 타임프레임 (시간 단위)
            
        Returns:
            bool: 캔들이 완료되었으면 True, 아니면 False
        """
        current_time = datetime.now(pytz.UTC)
        candle_end_time = candle_time + timedelta(hours=timeframe_hours)
        
        logger.debug(f"캔들 완료 확인 - 현재: {current_time}, 캔들 종료: {candle_end_time}")
        
        return current_time >= candle_end_time

    def get_current_and_next_candle_times(self, timeframe_hours):
        """
        현재 진행 중인 캔들과 다음 캔들의 시간을 계산합니다.
        
        Args:
            timeframe_hours (int): 타임프레임 (시간 단위)
            
        Returns:
            tuple: (현재 캔들 시작 시간, 현재 캔들 종료 시간, 다음 캔들 종료 시간)
        """
        now = datetime.now(pytz.UTC)
        
        # 타임프레임에 맞게 현재 캔들의 시작 시간 계산
        hours_since_epoch = int(now.timestamp() / 3600)  # 1970년부터 현재까지의 시간 (시간 단위)
        current_candle_start_hour = (hours_since_epoch // timeframe_hours) * timeframe_hours
        
        current_candle_start = datetime.fromtimestamp(current_candle_start_hour * 3600, pytz.UTC)
        current_candle_end = current_candle_start + timedelta(hours=timeframe_hours)
        next_candle_end = current_candle_end + timedelta(hours=timeframe_hours)
        
        logger.debug(f"현재 캔들: {current_candle_start} ~ {current_candle_end}")
        logger.debug(f"다음 캔들: {current_candle_end} ~ {next_candle_end}")
        
        return current_candle_start, current_candle_end, next_candle_end

    def detect_consecutive_bearish(self, df, count):
        """
        연속적인 하락 캔들 패턴을 감지합니다.
        
        Args:
            df (DataFrame): 캔들 데이터
            count (int): 연속 하락 캔들 수
            
        Returns:
            bool: 패턴이 감지되면 True, 아니면 False
        """
        if len(df) < count:
            return False
            
        # 마지막 N개 캔들 선택
        last_candles = df.tail(count)
        
        # 마지막 캔들이 완료되었는지 확인
        last_candle_time = last_candles['time'].iloc[-1]
        
        # 모든 캔들이 하락 캔들인지 확인
        all_bearish = all(last_candles['is_bearish'])
        
        # 마지막 캔들이 완료된 경우에만 패턴 감지
        if all_bearish and self.is_candle_complete(last_candle_time, df['time'].diff().mean().total_seconds() / 3600):
            logger.info(f"{count}연속 하락 캔들 패턴 감지됨")
            return True
            
        return False

    async def send_alert(self, symbol, timeframe_hours, alert_type, data=None):
        """
        텔레그램으로 알림을 전송합니다.
        
        Args:
            symbol (str): 암호화폐 심볼
            timeframe_hours (int): 타임프레임 (시간 단위)
            alert_type (str): 알림 유형 ('consecutive_bearish' 또는 'pre_candle')
            data (dict): 알림에 필요한 추가 데이터
        """
        timeframe_str = f"{timeframe_hours}시간"
        current_time = datetime.now(pytz.UTC)
        
        try:
            if alert_type == 'consecutive_bearish':
                count = data['count']
                last_candles = data['candles']
                
                entry_price = last_candles['close'].iloc[-1]
                drop_percent = ((last_candles['open'].iloc[0] - last_candles['close'].iloc[-1]) / 
                                last_candles['open'].iloc[0] * 100)
                
                message = (
                    f"🚨 {symbol} {timeframe_str}봉 {count}연속 하락 패턴 발견! 🚨\n"
                    f"시간: {current_time.strftime('%Y-%m-%d %H:%M:%S %Z')}\n"
                    f"마지막 캔들 종료 시간: {(last_candles['time'].iloc[-1] + timedelta(hours=timeframe_hours)).strftime('%Y-%m-%d %H:%M:%S %Z')}\n"
                    f"현재 가격: ${entry_price:,.2f}\n"
                    f"하락률: {drop_percent:.2f}%\n"
                    f"타임프레임: {timeframe_str}"
                )
                
            elif alert_type == 'pre_candle':
                minutes_before = data['minutes_before']
                next_candle_end = data['next_candle_end']
                entry_price = data['price']
                
                message = (
                    f"⚠️ {symbol} {timeframe_str}봉 주의! ⚠️\n"
                    f"2연속 하락 발생, 다음 캔들 종료 {minutes_before}분 전\n"
                    f"현재 시간: {current_time.strftime('%Y-%m-%d %H:%M:%S %Z')}\n"
                    f"다음 캔들 종료 시간: {next_candle_end.strftime('%Y-%m-%d %H:%M:%S %Z')}\n"
                    f"현재 가격: ${entry_price:,.2f}\n"
                    f"타임프레임: {timeframe_str}"
                )
            else:
                logger.error(f"알 수 없는 알림 유형: {alert_type}")
                return
                
            logger.info(f"텔레그램 알림 전송 중: {alert_type}")
            await self.bot.send_message(chat_id=self.chat_id, text=message)
            logger.info("알림 전송 완료")
            
        except Exception as e:
            logger.error(f"알림 전송 중 오류 발생: {str(e)}")

    async def check_patterns(self, symbol, timeframe_hours):
        """
        특정 심볼과 타임프레임에 대한 모든 패턴을 확인합니다.
        """
        try:
            # 캔들스틱 데이터 가져오기
            df = await self.fetch_candlestick_data(symbol, timeframe_hours)
            
            # 현재 시간 (UTC)
            current_time = datetime.now(pytz.UTC)
            
            # 1. 3, 4, 5 연속 하락 패턴 확인
            for count in [3, 4, 5]:
                alert_key = f"{symbol}_{timeframe_hours}_{count}"
                
                # 마지막 알림 이후 2시간 이상 지났는지 확인
                if (alert_key in self.last_alert_times and 
                    (current_time - self.last_alert_times[alert_key]).total_seconds() < 7200):
                    continue
                    
                if self.detect_consecutive_bearish(df, count):
                    # 3, 4, 5 연속 하락 패턴 감지됨
                    await self.send_alert(
                        symbol, 
                        timeframe_hours, 
                        'consecutive_bearish', 
                        {'count': count, 'candles': df.tail(count)}
                    )
                    self.last_alert_times[alert_key] = current_time
            
            # 2. 2연속 하락 패턴 확인 및 다음 캔들 종료 전 알림
            if len(df) >= 2:
                last_two = df.tail(2)
                
                if all(last_two['is_bearish']):
                    logger.info(f"{symbol} {timeframe_hours}시간봉 2연속 하락 패턴 감지됨")
                    
                    # 현재 캔들과 다음 캔들 시간 계산
                    _, current_candle_end, next_candle_end = self.get_current_and_next_candle_times(timeframe_hours)
                    
                    # 다음 캔들 종료까지 남은 시간 (분)
                    time_to_end = (next_candle_end - current_time).total_seconds() / 60
                    
                    # 1시간 전 알림 (55~65분 범위)
                    pre_alert_key_1hour = f"pre_1hour_{symbol}_{timeframe_hours}"
                    if (55 <= time_to_end <= 65 and 
                        (pre_alert_key_1hour not in self.pre_candle_alerts or 
                         self.pre_candle_alerts[pre_alert_key_1hour] != next_candle_end)):
                        
                        await self.send_alert(
                            symbol, 
                            timeframe_hours, 
                            'pre_candle', 
                            {
                                'minutes_before': 60,
                                'next_candle_end': next_candle_end,
                                'price': last_two['close'].iloc[-1]
                            }
                        )
                        self.pre_candle_alerts[pre_alert_key_1hour] = next_candle_end
                    
                    # 5분 전 알림 (3~7분 범위)
                    pre_alert_key_5min = f"pre_5min_{symbol}_{timeframe_hours}"
                    if (3 <= time_to_end <= 7 and 
                        (pre_alert_key_5min not in self.pre_candle_alerts or 
                         self.pre_candle_alerts[pre_alert_key_5min] != next_candle_end)):
                        
                        await self.send_alert(
                            symbol, 
                            timeframe_hours, 
                            'pre_candle', 
                            {
                                'minutes_before': 5,
                                'next_candle_end': next_candle_end,
                                'price': last_two['close'].iloc[-1]
                            }
                        )
                        self.pre_candle_alerts[pre_alert_key_5min] = next_candle_end
                        
        except Exception as e:
            logger.error(f"{symbol} {timeframe_hours}시간봉 패턴 확인 중 오류 발생: {str(e)}")
            
            # API 요율 제한 감지
            if "rate limit" in str(e).lower():
                self.error_wait_time = max(15, self.error_wait_time * 2)  # 지수 백오프
                try:
                    await self.bot.send_message(
                        chat_id=self.chat_id, 
                        text=f"⚠️ API 요율 제한 감지! {self.error_wait_time}분 대기 후 재시도합니다."
                    )
                except Exception as telegram_error:
                    logger.error(f"텔레그램 오류 메시지 전송 실패: {str(telegram_error)}")

    async def run(self):
        """
        메인 실행 루프
        """
        # 감시할 암호화폐 및 타임프레임
        symbols = ['BTC', 'ETH', 'XRP']
        timeframes = [2, 4]  # 시간 단위
        check_interval = 2 * 60  # 체크 간격 (초)
        
        logger.info("암호화폐 패턴 감시 시작")
        
        # 시작 메시지 전송
        try:
            await self.bot.send_message(
                chat_id=self.chat_id, 
                text="🤖 암호화폐 패턴 감시를 시작합니다!\n"
                "모니터링 중: BTC, ETH, XRP\n"
                "타임프레임: 2시간봉, 4시간봉\n"
                "알림 유형:\n"
                "1. 3,4,5연속 하락 패턴 (캔들 완료 확인 후 알림, 2시간 간격)\n"
                "2. 2연속 하락 후 다음 캔들 종료 1시간 전 알림 (55~65분 범위)\n"
                "3. 2연속 하락 후 다음 캔들 종료 5분 전 알림 (3~7분 범위)\n"
                "체크 간격: 2분 (알림 정확도 향상)\n"
                f"현재 시간: {datetime.now(pytz.UTC).strftime('%Y-%m-%d %H:%M:%S %Z')}"
            )
        except Exception as e:
            logger.error(f"시작 메시지 전송 실패: {str(e)}")
        
        # 메인 루프
        while True:
            try:
                for symbol in symbols:
                    for timeframe in timeframes:
                        await self.check_patterns(symbol, timeframe)
                        await asyncio.sleep(1)  # API 요청 간 짧은 대기
                
                # 다음 체크까지 대기
                wait_time = check_interval
                if self.error_wait_time > 0:
                    wait_time = self.error_wait_time * 60  # 분을 초로 변환
                    logger.info(f"요율 제한으로 인해 {self.error_wait_time}분 대기 중...")
                    self.error_wait_time = 0  # 대기 후 초기화
                
                logger.info(f"다음 체크는 {wait_time/60:.1f}분 후 ({(datetime.now(pytz.UTC) + timedelta(seconds=wait_time)).strftime('%H:%M:%S')})에 수행")
                await asyncio.sleep(wait_time)
                
            except Exception as e:
                logger.error(f"메인 루프 실행 중 오류 발생: {str(e)}")
                await asyncio.sleep(check_interval)  # 오류 발생 시 기본 대기 시간 사용

def main():
    """
    메인 함수
    """
    try:
        logger.info("CryptoAlert 봇 시작")
        alert_bot = CryptoAlert()
        asyncio.run(alert_bot.run())
    except Exception as e:
        logger.error(f"프로그램 실행 중 치명적 오류 발생: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
