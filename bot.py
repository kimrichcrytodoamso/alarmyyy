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
        self.candle_end_alerts = {}  # 캔들 종료 알림 기록
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
            
    async def get_current_price(self, symbol):
        """
        암호화폐의 현재 가격을 가져옵니다.
        
        Args:
            symbol (str): 암호화폐 심볼 (BTC, ETH 등)
            
        Returns:
            float: 현재 가격
        """
        url = "https://min-api.cryptocompare.com/data/price"
        params = {
            "fsym": symbol,
            "tsyms": "USD",
            "api_key": self.crypto_api_key
        }
        
        try:
            response = requests.get(url, params=params, timeout=30)
            data = response.json()
            
            if "USD" in data:
                return data["USD"]
            else:
                logger.error(f"현재 가격 요청 실패: {data}")
                raise Exception("현재 가격을 가져올 수 없습니다.")
        except Exception as e:
            logger.error(f"현재 가격 요청 중 오류 발생: {str(e)}")
            raise

    def check_consecutive_bearish(self, df, count):
        """
        연속적인 하락 캔들 패턴을 확인합니다.
        
        Args:
            df (DataFrame): 캔들 데이터
            count (int): 확인할 연속 하락 캔들 수
            
        Returns:
            bool: 패턴이 있으면 True, 없으면 False
        """
        if len(df) < count:
            return False
            
        # 마지막 N개 캔들 선택
        last_candles = df.tail(count)
        
        # 모든 캔들이 하락 캔들인지 확인
        return all(last_candles['is_bearish'])

    def calculate_current_candle_times(self, timeframe_hours):
        """
        현재 진행 중인 캔들의 시작 및 종료 시간을 계산합니다.
        
        Args:
            timeframe_hours (int): 타임프레임 (시간 단위)
            
        Returns:
            tuple: (현재 캔들 시작 시간, 현재 캔들 종료 시간)
        """
        now = datetime.now(pytz.UTC)
        
        # 타임프레임에 맞게 현재 캔들의 시작 시간 계산
        hours_since_epoch = int(now.timestamp() / 3600)  # 1970년부터 현재까지의 시간 (시간 단위)
        current_candle_start_hour = (hours_since_epoch // timeframe_hours) * timeframe_hours
        
        current_candle_start = datetime.fromtimestamp(current_candle_start_hour * 3600, pytz.UTC)
        current_candle_end = current_candle_start + timedelta(hours=timeframe_hours)
        
        logger.debug(f"현재 캔들: {current_candle_start} ~ {current_candle_end}")
        
        return current_candle_start, current_candle_end

    async def send_candle_end_alert(self, symbol, timeframe_hours, patterns, last_candle_close, current_price):
        """
        캔들 종료 5분 전 알림을 전송합니다.
        
        Args:
            symbol (str): 암호화폐 심볼
            timeframe_hours (int): 타임프레임 (시간 단위)
            patterns (dict): 감지된 패턴 정보
            last_candle_close (float): 마지막 캔들의 종가
            current_price (float): 현재 가격
        """
        timeframe_str = f"{timeframe_hours}시간"
        current_time = datetime.now(pytz.UTC)
        
        # 변화율 및 변화폭 계산
        price_change = current_price - last_candle_close
        price_change_percent = (price_change / last_candle_close) * 100
        
        # 패턴 문자열 생성
        pattern_strs = []
        if patterns.get('bearish_3', False):
            pattern_strs.append("3연속 하락")
        if patterns.get('bearish_4', False):
            pattern_strs.append("4연속 하락")
        if patterns.get('bearish_5', False):
            pattern_strs.append("5연속 하락")
            
        pattern_text = "패턴 감지 없음"
        if pattern_strs:
            pattern_text = ", ".join(pattern_strs) + " 패턴 감지됨"
        
        # 알림 메시지 작성
        message = (
            f"🔔 {symbol} {timeframe_str}봉 종료 5분 전 알림 🔔\n"
            f"시간: {current_time.strftime('%Y-%m-%d %H:%M:%S %Z')}\n"
            f"1) {pattern_text}\n"
            f"2) 전 캔들 대비 가격 변화: {price_change_percent:.2f}%, {price_change:.2f}$\n"
            f"   - 전 캔들 종가: ${last_candle_close:,.2f}\n"
            f"   - 현재 가격: ${current_price:,.2f}\n"
            f"타임프레임: {timeframe_str}"
        )
        
        try:
            logger.info(f"캔들 종료 알림 전송 중: {symbol} {timeframe_str}봉")
            await self.bot.send_message(chat_id=self.chat_id, text=message)
            logger.info(f"캔들 종료 알림 전송 완료: {symbol} {timeframe_str}봉")
        except Exception as e:
            logger.error(f"알림 전송 중 오류 발생: {str(e)}")

    async def check_candle_end_alerts(self, symbol, timeframe_hours):
        """
        특정 심볼 및 타임프레임에 대한 캔들 종료 5분 전 알림을 확인합니다.
        """
        try:
            # 현재 캔들 시간 계산
            _, current_candle_end = self.calculate_current_candle_times(timeframe_hours)
            
            # 현재 시간
            current_time = datetime.now(pytz.UTC)
            
            # 캔들 종료까지 남은 시간 (분)
            minutes_to_end = (current_candle_end - current_time).total_seconds() / 60
            
            # 캔들 종료 5분 전인지 확인 (3-7분 범위)
            if 3 <= minutes_to_end <= 7:
                # 이미 알림을 보냈는지 확인
                alert_key = f"{symbol}_{timeframe_hours}_{current_candle_end.strftime('%Y%m%d%H%M')}"
                
                if alert_key not in self.candle_end_alerts:
                    logger.info(f"{symbol} {timeframe_hours}시간봉 종료 {minutes_to_end:.1f}분 전")
                    
                    # 캔들스틱 데이터 가져오기
                    df = await self.fetch_candlestick_data(symbol, timeframe_hours)
                    
                    # 마지막 캔들의 종가
                    last_candle_close = df['close'].iloc[-1]
                    
                    # 현재 가격 가져오기
                    current_price = await self.get_current_price(symbol)
                    
                    # 연속 하락 패턴 확인
                    patterns = {
                        'bearish_3': self.check_consecutive_bearish(df, 3),
                        'bearish_4': self.check_consecutive_bearish(df, 4),
                        'bearish_5': self.check_consecutive_bearish(df, 5)
                    }
                    
                    # 캔들 종료 알림 전송
                    await self.send_candle_end_alert(
                        symbol, 
                        timeframe_hours, 
                        patterns, 
                        last_candle_close, 
                        current_price
                    )
                    
                    # 알림 기록
                    self.candle_end_alerts[alert_key] = current_time
                    
                    # 매시간 정각에 오래된 알림 기록 정리
                    if current_time.minute == 0:
                        self._clean_old_alerts()
        
        except Exception as e:
            logger.error(f"{symbol} {timeframe_hours}시간봉 알림 확인 중 오류 발생: {str(e)}")
            
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
    
    def _clean_old_alerts(self):
        """
        24시간 이상 지난 알림 기록을 정리합니다.
        """
        current_time = datetime.now(pytz.UTC)
        old_keys = []
        
        for key, alert_time in self.candle_end_alerts.items():
            if (current_time - alert_time).total_seconds() > 86400:  # 24시간 (초)
                old_keys.append(key)
                
        for key in old_keys:
            del self.candle_end_alerts[key]
            
        if old_keys:
            logger.info(f"{len(old_keys)}개의 오래된 알림 기록이 정리되었습니다.")

    def _calculate_next_check_time(self):
        """
        다음 체크 시간을 계산합니다.
        현재 시간에서 가장 가까운 5분 단위 시간으로 설정합니다.
        """
        now = datetime.now(pytz.UTC)
        
        # 다음 5분 단위 시간 계산
        minutes = now.minute
        remainder = minutes % 5
        
        if remainder == 0:
            # 현재가 정확히 5분 단위라면, 다음 5분으로
            next_minutes = minutes + 5
        else:
            # 다음 5분 단위로
            next_minutes = minutes + (5 - remainder)
        
        # 다음 체크 시간 설정
        next_check = now.replace(minute=next_minutes % 60, second=0, microsecond=0)
        
        # 만약 다음 분이 60 이상이면 시간을 +1
        if next_minutes >= 60:
            next_check = next_check + timedelta(hours=1)
            
        return next_check

    async def run(self):
        """
        메인 실행 루프
        """
        # 감시할 암호화폐 및 타임프레임
        symbols = ['BTC', 'ETH', 'XRP']
        timeframes = [2, 4]  # 시간 단위
        
        logger.info("암호화폐 캔들 종료 알림 시작")
        
        # 시작 메시지 전송
        try:
            await self.bot.send_message(
                chat_id=self.chat_id, 
                text="🤖 암호화폐 캔들 종료 알림 봇이 시작되었습니다!\n"
                "모니터링 중: BTC, ETH, XRP\n"
                "타임프레임: 2시간봉, 4시간봉\n"
                "알림 기능:\n"
                "- 캔들 종료 5분 전 알림\n"
                "- 연속 하락 패턴 감지 (3, 4, 5연속)\n"
                "- 전 캔들 대비 가격 변화 정보\n"
                "체크 간격: 5분\n"
                f"현재 시간: {datetime.now(pytz.UTC).strftime('%Y-%m-%d %H:%M:%S %Z')}"
            )
        except Exception as e:
            logger.error(f"시작 메시지 전송 실패: {str(e)}")
        
        # 메인 루프
        while True:
            try:
                # 모든 암호화폐 및 타임프레임 확인
                for symbol in symbols:
                    for timeframe in timeframes:
                        await self.check_candle_end_alerts(symbol, timeframe)
                        await asyncio.sleep(1)  # API 요청 간 짧은 대기
                
                # 다음 체크 시간 계산 (5분 단위)
                next_check = self._calculate_next_check_time()
                current_time = datetime.now(pytz.UTC)
                wait_seconds = (next_check - current_time).total_seconds()
                
                # API 요율 제한이 있으면 대기 시간 조정
                if self.error_wait_time > 0:
                    wait_minutes = self.error_wait_time
                    wait_seconds = wait_minutes * 60
                    logger.info(f"요율 제한으로 인해 {wait_minutes}분 대기 중...")
                    self.error_wait_time = 0  # 대기 후 초기화
                else:
                    logger.info(f"다음 체크는 {next_check.strftime('%H:%M:%S')}에 수행합니다. ({wait_seconds:.1f}초 후)")
                
                # 최소 10초는 대기
                wait_seconds = max(10, wait_seconds)
                await asyncio.sleep(wait_seconds)
                
            except Exception as e:
                logger.error(f"메인 루프 실행 중 오류 발생: {str(e)}")
                await asyncio.sleep(300)  # 오류 발생 시 5분 대기

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
