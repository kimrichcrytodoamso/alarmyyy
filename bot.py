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
        CryptoCompare API를 사용하여 바이낸스의 암호화폐 캔들 데이터를 가져옵니다.
        일봉(24시간)의 경우 별도의 API 엔드포인트를 사용합니다.
        
        Args:
            symbol (str): 암호화폐 심볼 (BTC, ETH 등)
            timeframe_hours (int): 타임프레임 (시간 단위)
            
        Returns:
            DataFrame: 캔들 데이터가 포함된 데이터프레임
        """
        if timeframe_hours == 24:
            url = "https://min-api.cryptocompare.com/data/v2/histoday"
            params = {
                "fsym": symbol,
                "tsym": "USDT",
                "limit": 20,
                "api_key": self.crypto_api_key,
                "e": "Binance"
            }
            timeframe_str = "일봉"
        else:
            url = "https://min-api.cryptocompare.com/data/v2/histohour"
            params = {
                "fsym": symbol,
                "tsym": "USDT",
                "limit": 20,
                "api_key": self.crypto_api_key,
                "aggregate": timeframe_hours,
                "e": "Binance"
            }
            timeframe_str = f"{timeframe_hours}시간봉"
            
        logger.info(f"{symbol} {timeframe_str} 데이터 요청 중 (바이낸스/CryptoCompare USDT 페어)...")
        
        try:
            response = requests.get(url, params=params, timeout=30)
            data = response.json()
            
            if data['Response'] == 'Success':
                df = pd.DataFrame(data['Data']['Data'])
                df['time'] = pd.to_datetime(df['time'], unit='s').dt.tz_localize('UTC')
                
                df = df[['time', 'open', 'high', 'low', 'close', 'volumefrom', 'volumeto']]
                df = df.rename(columns={'volumefrom': 'volume'})
                df = df.sort_values('time')
                
                df['is_bearish'] = df['close'] < df['open']
                
                logger.info(f"{symbol} {timeframe_str} 데이터 {len(df)}개 가져옴 (바이낸스/CryptoCompare)")
                if not df.empty:
                    logger.info(f"데이터 범위: {df['time'].iloc[0]} ~ {df['time'].iloc[-1]}")
                
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
        CryptoCompare API를 통해 바이낸스의 현재 가격을 가져옵니다.
        
        Args:
            symbol (str): 암호화폐 심볼 (BTC, ETH 등)
            
        Returns:
            float: 현재 가격
        """
        url = "https://min-api.cryptocompare.com/data/price"
        params = {
            "fsym": symbol,
            "tsyms": "USDT",
            "api_key": self.crypto_api_key,
            "e": "Binance"
        }
        
        try:
            response = requests.get(url, params=params, timeout=30)
            data = response.json()
            
            if "USDT" in data:
                return float(data["USDT"])
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
            tuple: (패턴 존재 여부, 시작 캔들 가격, 종료 캔들 가격, 하락률)
        """
        if len(df) < count:
            return False, 0, 0, 0
            
        last_candles = df.tail(count)
        
        all_bearish = all(last_candles['is_bearish'])
        
        if all_bearish:
            start_price = last_candles['open'].iloc[0]
            end_price = last_candles['close'].iloc[-1]
            drop_percent = ((start_price - end_price) / start_price) * 100
            
            return True, start_price, end_price, drop_percent
            
        return False, 0, 0, 0

    def calculate_current_candle_times(self, timeframe_hours):
        """
        현재 진행 중인 캔들의 시작 및 종료 시간을 계산합니다.
        
        Args:
            timeframe_hours (int): 타임프레임 (시간 단위)
            
        Returns:
            tuple: (현재 캔들 시작 시간, 현재 캔들 종료 시간)
        """
        now = datetime.now(pytz.UTC)
        
        hours_since_epoch = int(now.timestamp() / 3600)
        current_candle_start_hour = (hours_since_epoch // timeframe_hours) * timeframe_hours
        
        current_candle_start = datetime.fromtimestamp(current_candle_start_hour * 3600, pytz.UTC)
        current_candle_end = current_candle_start + timedelta(hours=timeframe_hours)
        
        logger.debug(f"현재 캔들: {current_candle_start} ~ {current_candle_end}")
        
        return current_candle_start, current_candle_end

    def find_previous_candle(self, df, current_candle_start, timeframe_hours):
        """
        현재 캔들 이전의 완료된 캔들을 찾습니다.
        
        Args:
            df (DataFrame): 캔들 데이터
            current_candle_start (datetime): 현재 캔들 시작 시간
            timeframe_hours (int): 타임프레임 (시간 단위)
            
        Returns:
            tuple: (이전 캔들 시작 시간, 이전 캔들 종료 시간, 이전 캔들 종가)
        """
        previous_candle_start = current_candle_start - timedelta(hours=timeframe_hours)
        previous_candle_end = current_candle_start
        
        previous_candle = df[(df['time'] >= previous_candle_start) & (df['time'] < current_candle_start)]
        
        if not previous_candle.empty:
            previous_candle_close = previous_candle['close'].iloc[-1]
            return previous_candle_start, previous_candle_end, previous_candle_close
        else:
            logger.warning(f"이전 캔들 데이터를 찾을 수 없습니다. 시간 범위: {previous_candle_start} ~ {current_candle_start}")
            
            if not df.empty:
                last_candle = df.iloc[-1]
                last_candle_time = last_candle['time']
                last_candle_close = last_candle['close']
                return last_candle_time, last_candle_time + timedelta(hours=timeframe_hours), last_candle_close
            else:
                return None, None, None

    async def generate_coin_info(self, symbol, timeframe_hours, df, current_price):
        """
        코인별 정보를 생성합니다.
        
        Args:
            symbol (str): 암호화폐 심볼
            timeframe_hours (int): 타임프레임 (시간 단위)
            df (DataFrame): 캔들 데이터
            current_price (float): 현재 가격
            
        Returns:
            dict: 코인 정보
        """
        current_candle_start, current_candle_end = self.calculate_current_candle_times(timeframe_hours)
        
        prev_candle_start, prev_candle_end, prev_candle_close = self.find_previous_candle(
            df, current_candle_start, timeframe_hours
        )
        
        if prev_candle_close is None:
            price_change = 0
            price_change_percent = 0
            prev_candle_time_str = "이전 캔들 정보 없음"

        else:
            price_change = current_price - prev_candle_close
            price_change_percent = (price_change / prev_candle_close) * 100
    
            prev_start_utc1 = prev_candle_start + timedelta(hours=1)
            prev_end_utc1 = prev_candle_end + timedelta(hours=1)
            prev_candle_time_str = f"{prev_start_utc1.strftime('%H:%M')}-{prev_end_utc1.strftime('%H:%M')} (UTC+1)"
        
        bearish_3, start_price_3, end_price_3, drop_percent_3 = self.check_consecutive_bearish(df, 3)
        bearish_4, start_price_4, end_price_4, drop_percent_4 = self.check_consecutive_bearish(df, 4)
        bearish_5, start_price_5, end_price_5, drop_percent_5 = self.check_consecutive_bearish(df, 5)
        bearish_6, start_price_6, end_price_6, drop_percent_6 = self.check_consecutive_bearish(df, 6)
        bearish_7, start_price_7, end_price_7, drop_percent_7 = self.check_consecutive_bearish(df, 7)
        bearish_8, start_price_8, end_price_8, drop_percent_8 = self.check_consecutive_bearish(df, 8)
        bearish_9, start_price_9, end_price_9, drop_percent_9 = self.check_consecutive_bearish(df, 9)

        patterns = []
        pattern_details = []

        if bearish_9:
            patterns.append("9연속 하락")
            pattern_details.append(f"9연속 하락: {drop_percent_9:.2f}% (${start_price_9:,.2f} → ${end_price_9:,.2f})")
        elif bearish_8:
            patterns.append("8연속 하락")
            pattern_details.append(f"8연속 하락: {drop_percent_8:.2f}% (${start_price_8:,.2f} → ${end_price_8:,.2f})")
        elif bearish_7:
            patterns.append("7연속 하락")
            pattern_details.append(f"7연속 하락: {drop_percent_7:.2f}% (${start_price_7:,.2f} → ${end_price_7:,.2f})")
        elif bearish_6:
            patterns.append("6연속 하락")
            pattern_details.append(f"6연속 하락: {drop_percent_6:.2f}% (${start_price_6:,.2f} → ${end_price_6:,.2f})")
        elif bearish_5:
            patterns.append("5연속 하락")
            pattern_details.append(f"5연속 하락: {drop_percent_5:.2f}% (${start_price_5:,.2f} → ${end_price_5:,.2f})")
        elif bearish_4:
            patterns.append("4연속 하락")
            pattern_details.append(f"4연속 하락: {drop_percent_4:.2f}% (${start_price_4:,.2f} → ${end_price_4:,.2f})")
        elif bearish_3:
            patterns.append("3연속 하락")
            pattern_details.append(f"3연속 하락: {drop_percent_3:.2f}% (${start_price_3:,.2f} → ${end_price_3:,.2f})")
        
        return {
            "symbol": symbol,
            "timeframe_hours": timeframe_hours,
            "current_price": current_price,
            "prev_candle_close": prev_candle_close,
            "prev_candle_time_str": prev_candle_time_str,
            "price_change": price_change,
            "price_change_percent": price_change_percent,
            "patterns": patterns,
            "pattern_details": pattern_details
        }

    async def send_unified_alert(self, timeframe_hours, coins_info):
        """
        통합된 알림 메시지를 전송합니다.
        
        Args:
            timeframe_hours (int): 타임프레임 (시간 단위)
            coins_info (list): 코인별 정보 목록
        """
        if timeframe_hours == 24:
            timeframe_str = "일봉"
        else:
            timeframe_str = f"{timeframe_hours}시간봉"
            
        current_time = datetime.now(pytz.UTC)
        
        current_time_utc1 = current_time + timedelta(hours=1)
        message_parts = [
            f"🔔 {timeframe_str} 종료 5분 전 알림 🔔",
            f"시간: {current_time_utc1.strftime('%Y-%m-%d %H:%M:%S')} (UTC+1)",
            f"타임프레임: {timeframe_str}",
            ""
        ]
        
        for info in coins_info:
            symbol = info["symbol"]
            current_price = info["current_price"]
            
            if symbol == 'BTC':
                price_format = f"${current_price:,.2f}"
                change_format = f"{info['price_change_percent']:.2f}% ({info['price_change']:+,.2f}$)"
            elif symbol == 'ETH':
                price_format = f"${current_price:,.2f}"
                change_format = f"{info['price_change_percent']:.2f}% ({info['price_change']:+,.2f}$)"
            else:
                price_format = f"${current_price:,.4f}"
                change_format = f"{info['price_change_percent']:.4f}% ({info['price_change']:+,.4f}$)"
            
            coin_part = [
                f"📊 {symbol}:",
                f"현재 가격: {price_format}",
                f"전 캔들({info['prev_candle_time_str']}) 대비: {change_format}"
            ]
            
            if info["pattern_details"]:
                coin_part.append("감지된 패턴:")
                coin_part.extend([f"- {detail}" for detail in info["pattern_details"]])
            else:
                coin_part.append("감지된 패턴: 없음")
            
            message_parts.append("\n".join(coin_part))
            message_parts.append("")
        
        message = "\n".join(message_parts)
        
        try:
            logger.info(f"{timeframe_str} 통합 알림 전송 중...")
            await self.bot.send_message(chat_id=self.chat_id, text=message)
            logger.info(f"{timeframe_str} 통합 알림 전송 완료")
        except Exception as e:
            logger.error(f"알림 전송 중 오류 발생: {str(e)}")

    async def check_timeframe_alerts(self, timeframe_hours, symbols):
        """
        특정 타임프레임에 대한 모든 코인의 알림을 확인합니다.
        """
        if timeframe_hours == 24:
            timeframe_str = "일봉"
        else:
            timeframe_str = f"{timeframe_hours}시간봉"

        try:
            _, current_candle_end = self.calculate_current_candle_times(timeframe_hours)
            
            current_time = datetime.now(pytz.UTC)
            
            minutes_to_end = (current_candle_end - current_time).total_seconds() / 60
            
            logger.info(f"{timeframe_str} 현재 시간: {current_time}, 캔들 종료 시간: {current_candle_end}")
            logger.info(f"캔들 종료까지 남은 시간: {minutes_to_end:.1f} 분")
            
            if 3 <= minutes_to_end <= 7:
                alert_key = f"timeframe_{timeframe_hours}_{current_candle_end.strftime('%Y%m%d%H%M')}"
                
                if alert_key not in self.candle_end_alerts:
                    logger.info(f"{timeframe_str} 종료 {minutes_to_end:.1f}분 전")
                    
                    coins_info = []
                    
                    for symbol in symbols:
                        try:
                            df = await self.fetch_candlestick_data(symbol, timeframe_hours)
                            current_price = await self.get_current_price(symbol)
                            coin_info = await self.generate_coin_info(symbol, timeframe_hours, df, current_price)
                            coins_info.append(coin_info)
                            
                        except Exception as e:
                            logger.error(f"{symbol} 정보 수집 중 오류 발생: {str(e)}")
                    
                    if coins_info:
                        await self.send_unified_alert(timeframe_hours, coins_info)
                        self.candle_end_alerts[alert_key] = current_time
                    
                    if current_time.minute == 0:
                        self._clean_old_alerts()
        
        except Exception as e:
            logger.error(f"{timeframe_str} 알림 확인 중 오류 발생: {str(e)}")
            
            if "rate limit" in str(e).lower():
                self.error_wait_time = max(15, self.error_wait_time * 2)
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
            if (current_time - alert_time).total_seconds() > 86400:
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
        
        minutes = now.minute
        remainder = minutes % 5
        
        if remainder == 0:
            next_minutes = minutes + 5
        else:
            next_minutes = minutes + (5 - remainder)
        
        next_check = now.replace(minute=next_minutes % 60, second=0, microsecond=0)
        
        if next_minutes >= 60:
            next_check = next_check + timedelta(hours=1)
            
        return next_check

    async def run(self):
        """
        메인 실행 루프
        """
        symbols = ['BTC', 'ETH', 'XRP', 'SOL']
        # <--- CHANGED: 8시간봉 추가 --->
        timeframes = [2, 4, 6, 8, 12, 24] 
        
        logger.info("암호화폐 캔들 종료 알림 시작")
        
        try:
            # <--- CHANGED: 시작 메시지에 8시간봉 추가 --->
            await self.bot.send_message(
                chat_id=self.chat_id, 
                text="🤖 암호화폐 캔들 종료 알림 봇이 시작되었습니다!\n"
                     "모니터링 중: BTC, ETH, XRP, SOL\n"
                     "타임프레임: 2시간봉, 4시간봉, 6시간봉, 8시간봉, 12시간봉, 일봉\n"
                     "알림 기능:\n"
                     "- 캔들 종료 5분 전 통합 알림\n"
                     "- 연속 하락 패턴 감지 (3-9연속) 및 총 하락률 계산\n"
                     "- 전 캔들 대비 가격 변화 정보 (정확한 시간 표시)\n"
                     "체크 간격: 5분\n"
                     "데이터 소스: CryptoCompare (바이낸스 거래소 USDT 페어)\n"
                     f"현재 시간: {datetime.now(pytz.UTC).strftime('%Y-%m-%d %H:%M:%S %Z')}"
            )
        except Exception as e:
            logger.error(f"시작 메시지 전송 실패: {str(e)}")
        
        while True:
            try:
                # 각 타임프레임 리스트를 정렬하여 순서대로 확인
                for timeframe in sorted(timeframes):
                    await self.check_timeframe_alerts(timeframe, symbols)
                    await asyncio.sleep(1) # API 호출 간 짧은 대기
                
                next_check = self._calculate_next_check_time()
                current_time = datetime.now(pytz.UTC)
                wait_seconds = (next_check - current_time).total_seconds()
                
                if self.error_wait_time > 0:
                    wait_minutes = self.error_wait_time
                    wait_seconds = wait_minutes * 60
                    logger.info(f"요율 제한으로 인해 {wait_minutes}분 대기 중...")
                    self.error_wait_time = 0
                else:
                    logger.info(f"다음 체크는 {next_check.strftime('%H:%M:%S')}에 수행합니다. ({wait_seconds:.1f}초 후)")
                
                wait_seconds = max(10, wait_seconds)
                await asyncio.sleep(wait_seconds)
                
            except Exception as e:
                logger.error(f"메인 루프 실행 중 오류 발생: {str(e)}")
                await asyncio.sleep(300)

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
