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

# 로깅 설정 - 더 상세한 로그
logging.basicConfig(
    level=logging.DEBUG,  # DEBUG 레벨로 설정
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("CryptoDebug")

class CryptoAlert:
    def __init__(self):
        # 환경 변수 확인 및 로깅
        self.crypto_api_key = os.environ.get('CRYPTO_API_KEY')
        self.telegram_token = os.environ.get('TELEGRAM_TOKEN')
        self.chat_id = os.environ.get('CHAT_ID')
        
        logger.info(f"CRYPTO_API_KEY: {'설정됨' if self.crypto_api_key else '누락됨'}")
        logger.info(f"TELEGRAM_TOKEN: {'설정됨' if self.telegram_token else '누락됨'}")
        logger.info(f"CHAT_ID: {'설정됨' if self.chat_id else '누락됨'}")
        
        # 필수 환경 변수 확인
        if not self.crypto_api_key or not self.telegram_token or not self.chat_id:
            logger.error("필수 환경 변수가 누락되었습니다. 프로그램을 종료합니다.")
            sys.exit(1)
            
        self.bot = Bot(token=self.telegram_token)
        self.last_alert_times = {}
        
        logger.info("CryptoAlert 초기화 완료")
        
    async def test_api_connection(self):
        """API 연결 테스트"""
        url = "https://min-api.cryptocompare.com/data/v2/histohour"
        params = {
            "fsym": "BTC",
            "tsym": "USD",
            "limit": 1,
            "api_key": self.crypto_api_key
        }
        
        try:
            logger.info("CryptoCompare API 연결 테스트 중...")
            response = requests.get(url, params=params, timeout=30)
            data = response.json()
            
            if data['Response'] == 'Success':
                logger.info("API 연결 성공!")
                logger.debug(f"API 응답: {data['Data']['Data'][0]}")
                return True
            else:
                logger.error(f"API 응답 오류: {data.get('Message', '알 수 없는 오류')}")
                return False
        except Exception as e:
            logger.error(f"API 연결 테스트 중 오류 발생: {str(e)}")
            return False
            
    async def test_telegram_connection(self):
        """텔레그램 연결 테스트"""
        try:
            logger.info("텔레그램 연결 테스트 중...")
            await self.bot.send_message(
                chat_id=self.chat_id, 
                text=f"🔍 디버깅 테스트 메시지\n시간: {datetime.now(pytz.UTC).strftime('%Y-%m-%d %H:%M:%S %Z')}"
            )
            logger.info("텔레그램 메시지 전송 성공!")
            return True
        except Exception as e:
            logger.error(f"텔레그램 연결 테스트 중 오류 발생: {str(e)}")
            return False
            
    async def fetch_and_analyze_btc(self):
        """BTC 데이터 가져오기 및 간단한 분석"""
        url = "https://min-api.cryptocompare.com/data/v2/histohour"
        params = {
            "fsym": "BTC",
            "tsym": "USD",
            "limit": 5,
            "api_key": self.crypto_api_key,
            "aggregate": 2  # 2시간 타임프레임
        }
        
        try:
            logger.info("BTC 2시간봉 데이터 요청 중...")
            response = requests.get(url, params=params, timeout=30)
            data = response.json()
            
            if data['Response'] == 'Success':
                # 데이터 변환
                df = pd.DataFrame(data['Data']['Data'])
                df['time'] = pd.to_datetime(df['time'], unit='s').dt.tz_localize('UTC')
                df = df[['time', 'open', 'high', 'low', 'close']]
                
                # 하락 캔들 표시
                df['is_bearish'] = df['close'] < df['open']
                
                # 결과 출력
                logger.info(f"가져온 캔들 수: {len(df)}")
                logger.info(f"캔들 정보:\n{df[['time', 'open', 'close', 'is_bearish']]}")
                
                # 하락 캔들 확인
                bearish_count = df['is_bearish'].sum()
                logger.info(f"하락 캔들 수: {bearish_count}")
                
                # 2연속 하락 확인
                has_two_consecutive = False
                for i in range(len(df) - 1):
                    if df['is_bearish'].iloc[i] and df['is_bearish'].iloc[i+1]:
                        logger.info(f"2연속 하락 발견: {df['time'].iloc[i]} 및 {df['time'].iloc[i+1]}")
                        has_two_consecutive = True
                
                if not has_two_consecutive:
                    logger.info("2연속 하락 패턴 없음")
                
                # 현재 시간 및 캔들 시간 확인
                now = datetime.now(pytz.UTC)
                last_candle_time = df['time'].iloc[-1]
                last_candle_end = last_candle_time + timedelta(hours=2)
                
                logger.info(f"현재 시간: {now}")
                logger.info(f"마지막 캔들 시간: {last_candle_time}")
                logger.info(f"마지막 캔들 종료: {last_candle_end}")
                logger.info(f"마지막 캔들 완료 여부: {now >= last_candle_end}")
                
                # 전송 테스트
                message = (
                    f"📊 BTC 2시간봉 분석 결과\n"
                    f"시간: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}\n"
                    f"마지막 캔들: {last_candle_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"하락 캔들 수: {bearish_count}\n"
                    f"2연속 하락: {'있음' if has_two_consecutive else '없음'}\n"
                    f"현재 가격: ${df['close'].iloc[-1]:,.2f}"
                )
                
                await self.bot.send_message(chat_id=self.chat_id, text=message)
                logger.info("분석 결과 메시지 전송 완료")
                
                return True
            else:
                logger.error(f"API 응답 오류: {data.get('Message', '알 수 없는 오류')}")
                return False
        except Exception as e:
            logger.error(f"데이터 분석 중 오류 발생: {str(e)}")
            return False
            
    async def run(self):
        """디버깅 테스트 실행"""
        logger.info("디버깅 테스트 시작")
        
        # 시작 메시지
        try:
            await self.bot.send_message(
                chat_id=self.chat_id, 
                text="🔍 암호화폐 알림 봇 디버깅 테스트 시작\n"
                f"현재 시간: {datetime.now(pytz.UTC).strftime('%Y-%m-%d %H:%M:%S %Z')}"
            )
            logger.info("시작 메시지 전송 완료")
        except Exception as e:
            logger.error(f"시작 메시지 전송 실패: {str(e)}")
        
        # API 연결 테스트
        api_ok = await self.test_api_connection()
        
        # 텔레그램 연결 테스트
        telegram_ok = await self.test_telegram_connection()
        
        # 연결 상태 보고
        status_message = (
            f"🔍 연결 상태 보고:\n"
            f"API 연결: {'✅ 성공' if api_ok else '❌ 실패'}\n"
            f"텔레그램 연결: {'✅ 성공' if telegram_ok else '❌ 실패'}\n"
            f"시간: {datetime.now(pytz.UTC).strftime('%Y-%m-%d %H:%M:%S %Z')}"
        )
        
        try:
            await self.bot.send_message(chat_id=self.chat_id, text=status_message)
        except Exception as e:
            logger.error(f"상태 메시지 전송 실패: {str(e)}")
        
        # 모든 연결이 정상이면 데이터 분석 테스트
        if api_ok and telegram_ok:
            logger.info("연결 테스트 성공, 데이터 분석 테스트 시작")
            await self.fetch_and_analyze_btc()
        
        logger.info("디버깅 테스트 완료")

def main():
    """메인 함수"""
    try:
        logger.info("디버깅 스크립트 시작")
        alert_bot = CryptoAlert()
        asyncio.run(alert_bot.run())
    except Exception as e:
        logger.error(f"프로그램 실행 중 치명적 오류 발생: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
