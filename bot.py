import pandas as pd
import requests
import time
from datetime import datetime, timedelta
from telegram import Bot
import asyncio
import os
import sys
import pytz

class CryptoAlert:
    def __init__(self):
        # 환경 변수 확인 및 로깅
        self.crypto_api_key = os.environ.get('CRYPTO_API_KEY')
        self.telegram_token = os.environ.get('TELEGRAM_TOKEN')
        self.chat_id = os.environ.get('CHAT_ID')
        
        # 환경 변수가 없을 경우 오류 기록 및 종료
        if not self.crypto_api_key:
            print("오류: CRYPTO_API_KEY 환경 변수가 설정되지 않았습니다.")
            sys.exit(1)
        if not self.telegram_token:
            print("오류: TELEGRAM_TOKEN 환경 변수가 설정되지 않았습니다.")
            sys.exit(1)
        if not self.chat_id:
            print("오류: CHAT_ID 환경 변수가 설정되지 않았습니다.")
            sys.exit(1)
            
        self.bot = Bot(token=self.telegram_token)
        self.last_alert_times = {}
        self.pre_candle_alerts = {}
        self.error_wait_time = 0  # 에러 발생 시 대기 시간 추적
        
        print("CryptoAlert 초기화 완료.")
        
    def get_candlestick_data(self, symbol, timeframe):
        url = f"https://min-api.cryptocompare.com/data/v2/histohour"
        params = {
            "fsym": symbol,
            "tsym": "USD",
            "limit": 5,
            "api_key": self.crypto_api_key,
            "aggregate": timeframe
        }
        
        print(f"{symbol} {timeframe}시간봉 데이터 요청 중...")
        response = requests.get(url, params=params)
        data = response.json()
        
        if data['Response'] == 'Success':
            df = pd.DataFrame(data['Data']['Data'])
            # API 응답의 시간은 UTC로 가정하고 명시적으로 타임존 설정
            df['time'] = pd.to_datetime(df['time'], unit='s').dt.tz_localize('UTC')
            print(f"{symbol} {timeframe}시간봉 데이터 {len(df)}개 받음.")
            return df
        else:
            error_msg = f"API 요청 실패: {data.get('Message', '알 수 없는 오류')}"
            print(error_msg)
            raise Exception(error_msg)

    def get_next_candle_end_time(self, current_candle_time, timeframe):
        # 다음 캔들 시작 시간 = 현재 캔들 시간 + timeframe
        next_candle_start = current_candle_time + timedelta(hours=timeframe)
        # 다음 캔들 종료 시간 = 다음 캔들 시작 시간 + timeframe
        next_candle_end = next_candle_start + timedelta(hours=timeframe)
        print(f"다음 캔들 종료 시간 계산: 현재 캔들 시간 {current_candle_time}, 타임프레임 {timeframe}시간, 다음 캔들 종료 시간 {next_candle_end}")
        return next_candle_end

    def is_candle_complete(self, candle_time, timeframe):
        # 현재 시간을 UTC로 가져오기
        current_time = datetime.now(pytz.UTC)
        candle_end = candle_time + timedelta(hours=timeframe)
        print(f"캔들 완료 확인: 현재 시간 {current_time}, 캔들 종료 시간 {candle_end}")
        return current_time >= candle_end

    async def check_pattern(self, symbol, timeframe):
        try:
            df = self.get_candlestick_data(symbol, timeframe)
            timeframe_str = f"{timeframe}시간"
            
            # 현재 시간을 UTC로 가져오기
            current_time = datetime.now(pytz.UTC)
            print(f"{symbol} {timeframe_str}봉 패턴 확인 중... 현재 시간: {current_time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
            
            # 데이터프레임을 시간 순으로 정렬하고 중복 제거
            df = df.sort_values('time').drop_duplicates()
            
            # 디버깅: 가져온 모든 캔들 시간 출력
            candle_times = [t.strftime('%Y-%m-%d %H:%M:%S') for t in df['time']]
            print(f"가져온 캔들 시간: {', '.join(candle_times)}")
            
            # 마지막 캔들이 완료되었는지 확인
            last_candle_time = df['time'].iloc[-1]
            last_candle_end = last_candle_time + timedelta(hours=timeframe)
            is_last_candle_complete = current_time >= last_candle_end
            
            print(f"마지막 캔들 시간: {last_candle_time}, 종료 시간: {last_candle_end}")
            print(f"마지막 캔들 완료 여부: {is_last_candle_complete}")
            
            df.set_index('time', inplace=True)
            
            # 3,4,5연속 하락 패턴 체크
            for consecutive_count in [3, 4, 5]:
                if len(df) >= consecutive_count:
                    last_candles = df.tail(consecutive_count)
                    alert_key = f"{symbol}_{timeframe}_{consecutive_count}"
                    
                    all_down = all(last_candles['close'] < last_candles['open'])
                    
                    if all_down and is_last_candle_complete:
                        print(f"{consecutive_count}연속 하락 패턴 감지: {all_down}, 마지막 캔들 완료: {is_last_candle_complete}")
                        
                        if (alert_key not in self.last_alert_times or 
                            (current_time - self.last_alert_times[alert_key]).total_seconds() > 7200):
                            
                            entry_price = last_candles.iloc[-1]['close']
                            drop_percent = ((last_candles.iloc[0]['open'] - last_candles.iloc[-1]['close']) 
                                          / last_candles.iloc[0]['open'] * 100)
                            
                            message = (
                                f"🚨 {symbol} {timeframe_str}봉 {consecutive_count}연속 하락 패턴 발견! 🚨\n"
                                f"시간: {current_time.strftime('%Y-%m-%d %H:%M:%S %Z')}\n"
                                f"마지막 캔들 종료 시간: {last_candle_end.strftime('%Y-%m-%d %H:%M:%S %Z')}\n"
                                f"현재 가격: ${entry_price:,.2f}\n"
                                f"하락률: {drop_percent:.2f}%\n"
                                f"타임프레임: {timeframe_str}"
                            )
                            
                            await self.bot.send_message(chat_id=self.chat_id, text=message)
                            self.last_alert_times[alert_key] = current_time
                            # 성공적인 요청 후 대기 시간 초기화
                            self.error_wait_time = 0
                            print(f"{symbol} {timeframe_str}봉 {consecutive_count}연속 하락 패턴 알림 전송 완료")

            # 2연속 하락 후 다음 캔들 종료 전 알림 체크
            if len(df) >= 2:
                # 마지막 2개 캔들 선택
                last_two = df.tail(2)
                
                # 마지막 캔들이 현재 진행 중인지 확인
                latest_candle_time = last_two.index[-1]
                latest_candle_end = latest_candle_time + timedelta(hours=timeframe)
                
                # 현재 진행 중인 캔들을 다루는 경우, 다음 캔들 시간 계산
                # 진행 중인 캔들: 현재 시간이 latest_candle_end 보다 이전인 경우
                if current_time < latest_candle_end:
                    next_candle_start = latest_candle_end
                    next_candle_end = next_candle_start + timedelta(hours=timeframe)
                else:
                    # 마지막 캔들이 이미 완료된 경우, 현재 진행 중인 캔들 계산
                    # 타임프레임 간격으로 나눈 나머지를 구해 현재 캔들의 시작 시간 계산
                    hours_since_epoch = current_time.timestamp() / 3600  # 시간 단위로 변환
                    hours_offset = hours_since_epoch % timeframe
                    current_candle_start = current_time - timedelta(hours=hours_offset)
                    current_candle_end = current_candle_start + timedelta(hours=timeframe)
                    next_candle_start = current_candle_end
                    next_candle_end = next_candle_start + timedelta(hours=timeframe)
                
                # 2연속 하락 확인
                if all(last_two['close'] < last_two['open']):
                    print(f"{symbol} {timeframe_str}봉 2연속 하락 발견: {last_two.index[0].strftime('%Y-%m-%d %H:%M')}와 {last_two.index[1].strftime('%Y-%m-%d %H:%M')}")
                    print(f"다음 캔들 시작 시간: {next_candle_start}, 종료 시간: {next_candle_end}")
                    
                    # 다음 캔들 종료까지 남은 시간 (분)
                    time_to_end = (next_candle_end - current_time).total_seconds() / 60
                    print(f"다음 캔들 종료까지 남은 시간: {time_to_end:.1f}분")

                    pre_alert_key_5min = f"pre_5min_{symbol}_{timeframe}"
                    pre_alert_key_1hour = f"pre_1hour_{symbol}_{timeframe}"
                    
                    # 종료 1시간 전 알림 (범위 확장: 55분~65분)
                    if (55 <= time_to_end <= 65 and 
                        (pre_alert_key_1hour not in self.pre_candle_alerts or 
                         self.pre_candle_alerts[pre_alert_key_1hour] != next_candle_end)):
                        
                        entry_price = last_two.iloc[-1]['close']
                        message = (
                            f"⚠️ {symbol} {timeframe_str}봉 주의! ⚠️\n"
                            f"2연속 하락 발생, 다음 캔들 종료 1시간 전\n"
                            f"현재 시간: {current_time.strftime('%Y-%m-%d %H:%M:%S %Z')}\n"
                            f"다음 캔들 종료 시간: {next_candle_end.strftime('%Y-%m-%d %H:%M:%S %Z')}\n"
                            f"현재 가격: ${entry_price:,.2f}\n"
                            f"타임프레임: {timeframe_str}"
                        )
                        
                        await self.bot.send_message(chat_id=self.chat_id, text=message)
                        self.pre_candle_alerts[pre_alert_key_1hour] = next_candle_end
                        print(f"{symbol} {timeframe_str}봉 다음 캔들 종료 1시간 전 알림 전송 완료")
                    
                    # 종료 5분 전 알림 (범위 확장: 3분~7분)
                    if (3 <= time_to_end <= 7 and 
                        (pre_alert_key_5min not in self.pre_candle_alerts or 
                         self.pre_candle_alerts[pre_alert_key_5min] != next_candle_end)):
                        
                        entry_price = last_two.iloc[-1]['close']
                        message = (
                            f"⚠️ {symbol} {timeframe_str}봉 주의! ⚠️\n"
                            f"2연속 하락 발생, 다음 캔들 종료 5분 전\n"
                            f"현재 시간: {current_time.strftime('%Y-%m-%d %H:%M:%S %Z')}\n"
                            f"다음 캔들 종료 시간: {next_candle_end.strftime('%Y-%m-%d %H:%M:%S %Z')}\n"
                            f"현재 가격: ${entry_price:,.2f}\n"
                            f"타임프레임: {timeframe_str}"
                        )
                        
                        await self.bot.send_message(chat_id=self.chat_id, text=message)
                        self.pre_candle_alerts[pre_alert_key_5min] = next_candle_end
                        print(f"{symbol} {timeframe_str}봉 다음 캔들 종료 5분 전 알림 전송 완료")
        
        except Exception as e:
            error_msg = str(e)
            # 요율 제한 에러 감지
            if "rate limit" in error_msg.lower():
                self.error_wait_time = max(15, self.error_wait_time * 2)  # 지수 백오프
                try:
                    await self.bot.send_message(
                        chat_id=self.chat_id, 
                        text=f"⚠️ API 요율 제한 감지! {self.error_wait_time}분 대기 후 재시도합니다."
                    )
                except Exception as telegram_error:
                    print(f"Telegram 메시지 전송 오류: {str(telegram_error)}")
            print(f"오류 발생: {error_msg}")
            raise Exception(error_msg)

    async def run(self):
        symbols = ['BTC', 'ETH', 'XRP']
        timeframes = [2, 4]
        check_interval = 2 * 60  # 체크 간격을 2분으로 변경
        
        print("암호화폐 패턴 감시를 시작합니다...")
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
            print("시작 메시지 전송 완료")
        except Exception as e:
            print(f"시작 메시지 전송 실패: {str(e)}")
            # 메시지 전송 실패해도 계속 진행
        
        while True:
            try:
                for symbol in symbols:
                    for timeframe in timeframes:
                        await self.check_pattern(symbol, timeframe)
                        # 각 호출 사이에 짧은 대기시간 추가
                        await asyncio.sleep(1)
                
                # 다음 체크까지 대기
                wait_time = check_interval
                if self.error_wait_time > 0:
                    wait_time = self.error_wait_time * 60  # 분을 초로 변환
                    print(f"요율 제한 에러로 인해 {self.error_wait_time}분 대기 중...")
                
                current_time = datetime.now(pytz.UTC)
                print(f"다음 체크는 {(current_time + timedelta(seconds=wait_time)).strftime('%Y-%m-%d %H:%M:%S %Z')}에 수행합니다.")
                await asyncio.sleep(wait_time)
            
            except Exception as e:
                print(f"루프 내 오류 발생: {str(e)}")
                # 일반 오류는 기본 대기 시간 사용
                await asyncio.sleep(check_interval)

def main():
    print("프로그램 시작")
    try:
        print("CryptoAlert 인스턴스 생성 중...")
        alert_bot = CryptoAlert()
        print("run() 함수 호출 중...")
        asyncio.run(alert_bot.run())
    except Exception as e:
        print(f"main 함수에서 오류 발생: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    print("스크립트 시작: __name__ == '__main__'")
    main()
