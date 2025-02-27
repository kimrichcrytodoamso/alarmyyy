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
                
                # 현재 진행 중인 캔들 계산 (마지막으로 받은 캔들 이후)
                last_candle_time = df['time'].iloc[-1]
                current_candle_start = last_candle_time + timedelta(hours=timeframe_hours)
                current_candle_end = current_candle_start + timedelta(hours=timeframe_hours)
                
                # 다음 캔들 종료까지 남은 시간 (분)
                time_to_end = (current_candle_end - current_time).total_seconds() / 60
                logger.info(f"현재 캔들 종료까지 남은 시간: {time_to_end:.1f}분")
                
                # 현재 캔들이 아직 진행 중인지 확인
                if current_time < current_candle_end:
                    # 1시간 전 알림 (55~65분 범위)
                    pre_alert_key_1hour = f"pre_1hour_{symbol}_{timeframe_hours}"
                    if (55 <= time_to_end <= 65 and 
                        (pre_alert_key_1hour not in self.pre_candle_alerts or 
                         self.pre_candle_alerts[pre_alert_key_1hour] != current_candle_end)):
                        
                        await self.send_alert(
                            symbol, 
                            timeframe_hours, 
                            'pre_candle', 
                            {
                                'minutes_before': 60,
                                'next_candle_end': current_candle_end,
                                'price': last_two['close'].iloc[-1]
                            }
                        )
                        self.pre_candle_alerts[pre_alert_key_1hour] = current_candle_end
                        logger.info(f"1시간 전 알림 전송 완료: {symbol} {timeframe_hours}시간봉")
                    
                    # 5분 전 알림 (3~7분 범위)
                    pre_alert_key_5min = f"pre_5min_{symbol}_{timeframe_hours}"
                    if (3 <= time_to_end <= 7 and 
                        (pre_alert_key_5min not in self.pre_candle_alerts or 
                         self.pre_candle_alerts[pre_alert_key_5min] != current_candle_end)):
                        
                        await self.send_alert(
                            symbol, 
                            timeframe_hours, 
                            'pre_candle', 
                            {
                                'minutes_before': 5,
                                'next_candle_end': current_candle_end,
                                'price': last_two['close'].iloc[-1]
                            }
                        )
                        self.pre_candle_alerts[pre_alert_key_5min] = current_candle_end
                        logger.info(f"5분 전 알림 전송 완료: {symbol} {timeframe_hours}시간봉")
                    
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
