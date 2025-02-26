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
        print(f"가져온 캔들 시간: {', '.join([t.strftime('%Y-%m-%d %H:%M:%S') for t in df['time']])}")
        
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
            await self.bot.send_message(
                chat_id=self.chat_id, 
                text=f"⚠️ API 요율 제한 감지! {self.error_wait_time}분 대기 후 재시도합니다."
            )
        print(f"오류 발생: {error_msg}")
        raise Exception(error_msg)
