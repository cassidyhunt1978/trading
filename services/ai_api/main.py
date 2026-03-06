"""AI API - Intelligent Insights & Strategy Suggestions"""
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict, Optional
import sys
import os
from anthropic import Anthropic

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.database import get_connection
from shared.config import get_settings
from shared.logging_config import setup_logging

settings = get_settings()
logger = setup_logging('ai_api', settings.log_level)

app = FastAPI(title="AI API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize AI client
anthropic_client = None
if settings.anthropic_api_key:
    anthropic_client = Anthropic(api_key=settings.anthropic_api_key)
    logger.info("anthropic_initialized")
else:
    logger.warning("anthropic_key_missing", msg="AI features limited")

class SignalValidationRequest(BaseModel):
    signal_id: int
    include_reasoning: bool = True

class SignalVoteRequest(BaseModel):
    """Request for AI to vote on a signal"""
    symbol: str
    signal: str  # BUY or SELL
    quality_score: float
    strategy_name: Optional[str] = None
    technical_indicators: Optional[Dict] = None

class IndicatorSuggestionRequest(BaseModel):
    symbol: str
    timeframe: str = "1h"
    recent_performance: Optional[Dict] = None

@app.get("/")
def root():
    return {"service": "AI API", "status": "running", "version": "1.0.0"}

@app.get("/health")
def health():
    return {
        "status": "healthy",
        "ai_enabled": anthropic_client is not None
    }

@app.post("/validate-signal")
async def validate_signal(request: SignalValidationRequest):
    """Use AI to validate a signal and provide intuition boost"""
    try:
        if not anthropic_client:
            raise HTTPException(status_code=503, detail="AI features not available (missing API key)")
        
        # Get signal details
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM signals WHERE id = %s", (request.signal_id,))
                signal = cur.fetchone()
                
                if not signal:
                    raise HTTPException(status_code=404, detail="Signal not found")
                
                signal = dict(signal)
                
                # Get recent candles for context
                cur.execute("""
                    SELECT * FROM ohlcv_candles
                    WHERE symbol = %s
                    ORDER BY timestamp DESC
                    LIMIT 20
                """, (signal['symbol'],))
                
                candles = [dict(row) for row in cur.fetchall()]
        
        # Build context for AI
        prompt = build_signal_validation_prompt(signal, candles)
        
        # Call Claude
        logger.info("calling_claude", signal_id=request.signal_id)
        
        response = anthropic_client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=1000,
            messages=[{
                "role": "user",
                "content": prompt
            }]
        )
        
        ai_response = response.content[0].text
        
        # Parse AI response to extract validation and reasoning
        validation = parse_ai_validation(ai_response)
        
        logger.info("signal_validated", signal_id=request.signal_id, ai_score=validation['score'])
        
        return {
            "status": "success",
            "signal_id": request.signal_id,
            "original_quality": signal['quality_score'],
            "ai_validation": validation,
            "adjusted_quality": min(100, signal['quality_score'] + validation['score']),
            "reasoning": ai_response if request.include_reasoning else None
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error("signal_validation_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

def build_signal_validation_prompt(signal: dict, candles: List[dict]) -> str:
    """Build prompt for AI signal validation"""
    
    recent_prices = [c['close'] for c in candles[:5]]
    avg_price = sum(recent_prices) / len(recent_prices)
    
    prompt = f"""Analyze this trading signal and provide your assessment:

Signal: {signal['signal'].upper()} {signal['symbol']}
Generated: {signal['generated_at']}
Current Quality Score: {signal['quality_score']}/100
Strategy: ID {signal['strategy_id']}

Recent Price Action:
- Current: ${candles[0]['close']}
- 5-candle average: ${avg_price:.2f}
- High: ${max(c['high'] for c in candles[:10])}
- Low: ${min(c['low'] for c in candles[:10])}

Context:
- Projected timeframe: {signal.get('projected_timeframe_minutes', 'unknown')} minutes
- Quality breakdown: {signal.get('quality_breakdown', 'N/A')}

Please provide:
1. Your intuition score (-10 to +10) where:
   - Positive = signal looks good, add confidence
   - Negative = signal looks questionable, reduce confidence
   - 0 = neutral

2. Brief reasoning (2-3 sentences)

Format your response as:
SCORE: [your score]
REASONING: [your analysis]
"""
    
    return prompt

def parse_ai_validation(ai_response: str) -> dict:
    """Parse AI validation response"""
    try:
        lines = ai_response.split('\n')
        score = 0
        reasoning = ""
        
        for line in lines:
            if line.startswith('SCORE:'):
                score_text = line.replace('SCORE:', '').strip()
                # Extract number from text
                import re
                match = re.search(r'[-+]?\d+', score_text)
                if match:
                    score = int(match.group())
                    score = max(-10, min(10, score))  # Clamp to [-10, 10]
            
            elif line.startswith('REASONING:'):
                reasoning = line.replace('REASONING:', '').strip()
        
        return {
            'score': score,
            'reasoning': reasoning or ai_response[:200]
        }
    
    except Exception as e:
        logger.error("parse_error", error=str(e))
        return {
            'score': 0,
            'reasoning': "Unable to parse AI response"
        }

@app.post("/vote-signal")
async def vote_on_signal(request: SignalVoteRequest):
    """AI votes on whether to take a trading signal"""
    try:
        if not anthropic_client:
            # Return neutral vote if AI not available
            return {
                "status": "success",
                "vote": "ABSTAIN",
                "vote_weight": 0.0,
                "confidence": 0,
                "reasoning": "AI not available (missing API key)",
                "ai_enabled": False
            }
        
        # Get recent price data for context
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT * FROM ohlcv_candles
                    WHERE symbol = %s
                    ORDER BY timestamp DESC
                    LIMIT 50
                """, (request.symbol,))
                
                candles = [dict(row) for row in cur.fetchall()]
        
        if not candles:
            logger.warning("no_candles_for_vote", symbol=request.symbol)
            return {
                "status": "success",
                "vote": "ABSTAIN",
                "vote_weight": 0.0,
                "confidence": 0,
                "reasoning": "Insufficient price data",
                "ai_enabled": True
            }
        
        # Get sentiment for this symbol
        sentiment_response = await get_sentiment(request.symbol)
        sentiment = sentiment_response.get('sentiment', {})
        
        # Build voting prompt
        prices = [c['close'] for c in candles[:20]]
        avg_price = sum(prices) / len(prices)
        trend = (prices[0] - prices[9]) / prices[9] * 100
        volatility = (max(prices[:10]) - min(prices[:10])) / min(prices[:10]) * 100
        
        prompt = f"""You are an AI trading advisor voting on whether to execute this signal:

Signal: {request.signal.upper()} {request.symbol}
Quality Score: {request.quality_score}/100
Strategy: {request.strategy_name or 'Unknown'}

Recent Market Data:
- Current Price: ${candles[0]['close']}
- 20-candle Average: ${avg_price:.2f}
- Recent Trend (10 candles): {trend:+.2f}%
- Volatility: {volatility:.2f}%

News Sentiment:
- Score: {sentiment.get('overall_score', 50)}/100
- Recommendation: {sentiment.get('recommendation', 'neutral').upper()}
- Sources: {sentiment.get('sources_analyzed', 0)} news items

"""
        
        if request.technical_indicators:
            prompt += f"\nTechnical Indicators:\n"
            for indicator, value in request.technical_indicators.items():
                prompt += f"- {indicator}: {value}\n"
        
        prompt += """
Please vote on this signal. Consider:
1. Does the price action support this signal?
2. Does the news sentiment align with the trade direction?
3. Is the timing good given volatility and trend?
4. What is your confidence level?

Respond with:
VOTE: [BUY/SELL/ABSTAIN]
CONFIDENCE: [0-100]
WEIGHT: [-1.0 to +1.0] (negative = vote against, positive = vote for)
REASONING: [2-3 sentence explanation]

Note: ABSTAIN if uncertain or if signal is questionable.
"""
        
        logger.info("requesting_ai_vote", symbol=request.symbol, signal=request.signal)
        
        response = anthropic_client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}]
        )
        
        ai_response = response.content[0].text
        parsed = parse_vote_response(ai_response, request.signal)
        
        logger.info("ai_vote_received", symbol=request.symbol, vote=parsed['vote'], 
                   weight=parsed['vote_weight'], confidence=parsed['confidence'])
        
        return {
            "status": "success",
            "vote": parsed['vote'],
            "vote_weight": parsed['vote_weight'],
            "confidence": parsed['confidence'],
            "reasoning": parsed['reasoning'],
            "ai_enabled": True,
            "sentiment_considered": sentiment.get('overall_score', 50)
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error("vote_error", error=str(e), symbol=request.symbol)
        raise HTTPException(status_code=500, detail=str(e))

def parse_vote_response(ai_response: str, original_signal: str) -> dict:
    """Parse AI voting response"""
    import re
    
    try:
        vote = "ABSTAIN"
        confidence = 0
        vote_weight = 0.0
        reasoning = ""
        
        lines = ai_response.split('\n')
        for line in lines:
            if line.startswith('VOTE:'):
                vote_text = line.replace('VOTE:', '').strip().upper()
                if 'BUY' in vote_text:
                    vote = 'BUY'
                elif 'SELL' in vote_text:
                    vote = 'SELL'
                else:
                    vote = 'ABSTAIN'
            
            elif line.startswith('CONFIDENCE:'):
                match = re.search(r'\d+', line)
                if match:
                    confidence = int(match.group())
                    confidence = max(0, min(100, confidence))
            
            elif line.startswith('WEIGHT:'):
                match = re.search(r'[-+]?\d*\.?\d+', line)
                if match:
                    vote_weight = float(match.group())
                    vote_weight = max(-1.0, min(1.0, vote_weight))
            
            elif line.startswith('REASONING:'):
                reasoning = line.replace('REASONING:', '').strip()
        
        # Adjust weight based on vote alignment
        if vote == 'ABSTAIN':
            vote_weight = 0.0
        elif vote != original_signal.upper():
            # AI disagrees with signal
            vote_weight = abs(vote_weight) * -1  # Make negative
        else:
            # AI agrees with signal
            vote_weight = abs(vote_weight)  # Make positive
        
        # Extract reasoning if not found in structured format
        if not reasoning:
            # Get last few lines as reasoning
            reasoning = ' '.join(lines[-3:])[:200]
        
        return {
            'vote': vote,
            'confidence': confidence,
            'vote_weight': vote_weight,
            'reasoning': reasoning
        }
    
    except Exception as e:
        logger.error("vote_parse_error", error=str(e))
        return {
            'vote': 'ABSTAIN',
            'confidence': 0,
            'vote_weight': 0.0,
            'reasoning': 'Failed to parse AI response'
        }

@app.post("/suggest-indicators")
async def suggest_indicators(request: IndicatorSuggestionRequest):
    """Get AI suggestions for which indicators to use"""
    try:
        if not anthropic_client:
            raise HTTPException(status_code=503, detail="AI features not available")
        
        # Get recent price data
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT * FROM ohlcv_candles
                    WHERE symbol = %s
                    ORDER BY timestamp DESC
                    LIMIT 100
                """, (request.symbol,))
                
                candles = [dict(row) for row in cur.fetchall()]
        
        if not candles:
            raise HTTPException(status_code=404, detail="No price data found for symbol")
        
        # Build prompt
        prompt = build_indicator_suggestion_prompt(request.symbol, candles, request.recent_performance)
        
        logger.info("requesting_indicator_suggestions", symbol=request.symbol)
        
        response = anthropic_client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=1500,
            messages=[{
                "role": "user",
                "content": prompt
            }]
        )
        
        suggestions = response.content[0].text
        
        return {
            "status": "success",
            "symbol": request.symbol,
            "suggestions": suggestions,
            "timestamp": "now"
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error("indicator_suggestion_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

def build_indicator_suggestion_prompt(symbol: str, candles: List[dict], performance: Optional[Dict]) -> str:
    """Build prompt for indicator suggestions"""
    
    prices = [c['close'] for c in candles]
    volatility = (max(prices) - min(prices)) / min(prices) * 100
    
    prompt = f"""Analyze {symbol} and suggest optimal technical indicators:

Price Statistics (last 100 candles):
- Current: ${candles[0]['close']}
- High: ${max(prices)}
- Low: ${min(prices)}
- Volatility: {volatility:.2f}%
- Trend: {('up' if prices[0] > prices[-1] else 'down')} {abs((prices[0] - prices[-1]) / prices[-1] * 100):.2f}%

"""
    
    if performance:
        prompt += f"""
Recent Strategy Performance:
- Win rate: {performance.get('win_rate', 'N/A')}%
- Avg P&L: {performance.get('avg_pnl', 'N/A')}%
"""
    
    prompt += """
Please suggest:
1. Top 3-5 technical indicators that would work best for this asset's current behavior
2. Specific parameter recommendations (e.g., "RSI(14)" or "RSI(21)")
3. Why each indicator is suitable
4. Any combination strategies (e.g., "RSI + MACD crossover")

Focus on indicators we support: RSI, MACD, Bollinger Bands, SMA, EMA, Volume
"""
    
    return prompt

@app.post("/discover-symbols")
async def discover_symbols(
    min_volume_usd: float = Query(1000000, description="Minimum 24h volume in USD"),
    max_results: int = Query(10, ge=1, le=50)
):
    """Use AI to discover promising trading symbols"""
    try:
        logger.info("discovering_symbols", min_volume=min_volume_usd)
        
        # Get all available symbols from database
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM symbols WHERE active = TRUE")
                known_symbols = [dict(row) for row in cur.fetchall()]
        
        # For now, return a curated list based on market analysis
        # In production, this would use real-time social media scraping
        
        discovered = [
            {
                "symbol": "SOL/USDT",
                "reason": "Strong L1 blockchain with growing ecosystem",
                "volume_24h_usd": 5000000000,
                "social_score": 85,
                "recommendation": "add"
            },
            {
                "symbol": "AVAX/USDT", 
                "reason": "Enterprise adoption increasing, subnet activity growing",
                "volume_24h_usd": 800000000,
                "social_score": 72,
                "recommendation": "monitor"
            },
            {
                "symbol": "MATIC/USDT",
                "reason": "Polygon zkEVM gaining traction, institutional interest",
                "volume_24h_usd": 600000000,
                "social_score": 68,
                "recommendation": "monitor"
            }
        ]
        
        # Filter by volume
        filtered = [s for s in discovered if s['volume_24h_usd'] >= min_volume_usd]
        
        return {
            "status": "success",
            "discovered": filtered[:max_results],
            "count": len(filtered)
        }
    
    except Exception as e:
        logger.error("symbol_discovery_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/explain-trade")
async def explain_trade(
    position_id: int = Query(..., description="Position ID to explain")
):
    """Get AI explanation of why a trade was taken and outcome"""
    try:
        if not anthropic_client:
            raise HTTPException(status_code=503, detail="AI features not available")
        
        # Get position details
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT p.*, s.name as strategy_name, sig.*
                    FROM positions p
                    LEFT JOIN strategies s ON p.strategy_id = s.id
                    LEFT JOIN signals sig ON p.signal_id = sig.id
                    WHERE p.id = %s
                """, (position_id,))
                
                position = cur.fetchone()
                
                if not position:
                    raise HTTPException(status_code=404, detail="Position not found")
                
                position = dict(position)
        
        # Build explanation prompt
        prompt = f"""Explain this trade in simple terms:

Entry: {position['side'].upper()} {position['symbol']} at ${position['entry_price']}
Exit: ${position.get('exit_price', 'still open')}
Result: {position.get('realized_pnl_pct', 'N/A')}% {'profit' if position.get('realized_pnl', 0) > 0 else 'loss'}

Strategy: {position.get('strategy_name', 'Unknown')}
Signal Quality: {position.get('quality_score', 'N/A')}/100

Please explain:
1. Why this trade was taken (what the strategy saw)
2. What happened during the trade
3. Why it resulted in a {position.get('trade_result', 'N/A')}
4. What could be learned for future trades

Write in concise, clear language a trader would understand.
"""
        
        response = anthropic_client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=800,
            messages=[{
                "role": "user",
                "content": prompt
            }]
        )
        
        explanation = response.content[0].text
        
        return {
            "status": "success",
            "position_id": position_id,
            "explanation": explanation
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error("explain_trade_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/sentiment/{symbol}")
async def get_sentiment(symbol: str):
    """Get AI-powered market sentiment for a symbol"""
    try:
        if not anthropic_client:
            # Return basic sentiment without AI
            sentiment = {
                "symbol": symbol,
                "overall_score": 50,
                "breakdown": {"news": 50, "ai_analysis": 0},
                "trending": False,
                "recommendation": "neutral",
                "sources_analyzed": 0,
                "ai_enabled": False
            }
            return {"status": "success", "sentiment": sentiment}
        
        # Get recent news for this symbol
        base_symbol = symbol.split('/')[0]
        news_items = await fetch_crypto_news(base_symbol)
        
        if not news_items:
            logger.warning("no_news_found", symbol=symbol)
            return {
                "status": "success",
                "sentiment": {
                    "symbol": symbol,
                    "overall_score": 50,
                    "breakdown": {"news": 50},
                    "trending": False,
                    "recommendation": "neutral",
                    "sources_analyzed": 0,
                    "ai_enabled": True,
                    "note": "No recent news found"
                }
            }
        
        # Build AI prompt to analyze sentiment
        news_text = "\n\n".join([
            f"Title: {item['title']}\nSource: {item['source']}\nDate: {item.get('published', 'unknown')}"
            for item in news_items[:5]
        ])
        
        prompt = f"""Analyze the sentiment for {base_symbol} based on these recent news headlines:

{news_text}

Provide:
1. Overall sentiment score (0-100, where 0=very bearish, 50=neutral, 100=very bullish)
2. Key themes mentioned (positive and negative)
3. Trading recommendation (BUY/SELL/HOLD)
4. Confidence level (0-100)

Format:
SCORE: [0-100]
THEMES: [key themes]
RECOMMENDATION: [BUY/SELL/HOLD]
CONFIDENCE: [0-100]
"""
        
        logger.info("analyzing_sentiment", symbol=symbol, news_count=len(news_items))
        
        response = anthropic_client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}]
        )
        
        ai_analysis = response.content[0].text
        parsed = parse_sentiment_response(ai_analysis)
        
        sentiment = {
            "symbol": symbol,
            "overall_score": parsed['score'],
            "breakdown": {
                "news": parsed['score'],
                "ai_analysis": parsed['confidence']
            },
            "trending": parsed['score'] > 70 or parsed['score'] < 30,
            "recommendation": parsed['recommendation'].lower(),
            "themes": parsed['themes'],
            "sources_analyzed": len(news_items),
            "ai_enabled": True
        }
        
        logger.info("sentiment_analyzed", symbol=symbol, score=parsed['score'], 
                   recommendation=parsed['recommendation'])
        
        return {
            "status": "success",
            "sentiment": sentiment
        }
    
    except Exception as e:
        logger.error("sentiment_error", error=str(e), symbol=symbol)
        raise HTTPException(status_code=500, detail=str(e))

async def fetch_crypto_news(symbol: str) -> List[dict]:
    """Fetch recent crypto news for a symbol"""
    import aiohttp
    import feedparser
    from datetime import datetime
    
    news_items = []
    
    # RSS feeds for crypto news
    feeds = [
        f"https://cointelegraph.com/rss/tag/{symbol.lower()}",
        f"https://cryptonews.com/news/{symbol.lower()}/feed/",
        "https://decrypt.co/feed"
    ]
    
    try:
        for feed_url in feeds:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(feed_url, timeout=aiohttp.ClientTimeout(total=5)) as response:
                        if response.status == 200:
                            content = await response.text()
                            feed = feedparser.parse(content)
                            
                            for entry in feed.entries[:5]:
                                # Filter for symbol mentions
                                if symbol.lower() in entry.title.lower() or symbol.lower() in entry.get('summary', '').lower():
                                    news_items.append({
                                        'title': entry.title,
                                        'source': feed.feed.get('title', 'Unknown'),
                                        'published': entry.get('published', 'unknown'),
                                        'link': entry.get('link', '')
                                    })
            except Exception as e:
                logger.warning("feed_fetch_error", feed=feed_url, error=str(e))
                continue
        
        # Fallback: Use general crypto news if no symbol-specific found
        if not news_items:
            general_feeds = [
                "https://cointelegraph.com/rss",
                "https://cryptonews.com/news/feed/"
            ]
            
            for feed_url in general_feeds[:1]:  # Just one general feed
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(feed_url, timeout=aiohttp.ClientTimeout(total=5)) as response:
                            if response.status == 200:
                                content = await response.text()
                                feed = feedparser.parse(content)
                                
                                for entry in feed.entries[:3]:
                                    news_items.append({
                                        'title': entry.title,
                                        'source': feed.feed.get('title', 'Crypto News'),
                                        'published': entry.get('published', 'unknown'),
                                        'link': entry.get('link', '')
                                    })
                                break  # Stop after first successful general feed
                except Exception as e:
                    logger.warning("general_feed_error", feed=feed_url, error=str(e))
                    continue
    
    except Exception as e:
        logger.error("news_fetch_error", error=str(e))
    
    return news_items

def parse_sentiment_response(ai_response: str) -> dict:
    """Parse AI sentiment response"""
    import re
    
    try:
        score = 50
        confidence = 50
        recommendation = "HOLD"
        themes = []
        
        lines = ai_response.split('\n')
        for line in lines:
            if line.startswith('SCORE:'):
                match = re.search(r'\d+', line)
                if match:
                    score = int(match.group())
                    score = max(0, min(100, score))
            
            elif line.startswith('CONFIDENCE:'):
                match = re.search(r'\d+', line)
                if match:
                    confidence = int(match.group())
                    confidence = max(0, min(100, confidence))
            
            elif line.startswith('RECOMMENDATION:'):
                rec_text = line.replace('RECOMMENDATION:', '').strip().upper()
                if 'BUY' in rec_text:
                    recommendation = 'BUY'
                elif 'SELL' in rec_text:
                    recommendation = 'SELL'
                else:
                    recommendation = 'HOLD'
            
            elif line.startswith('THEMES:'):
                themes_text = line.replace('THEMES:', '').strip()
                themes = [t.strip() for t in themes_text.split(',')]
        
        return {
            'score': score,
            'confidence': confidence,
            'recommendation': recommendation,
            'themes': themes
        }
    
    except Exception as e:
        logger.error("sentiment_parse_error", error=str(e))
        return {
            'score': 50,
            'confidence': 0,
            'recommendation': 'HOLD',
            'themes': []
        }

@app.get("/market-regime")
async def get_market_regime():
    """Get AI assessment of current market regime"""
    try:
        # Get recent BTC price action as market proxy
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT * FROM ohlcv_candles
                    WHERE symbol = 'BTC/USDT'
                    ORDER BY timestamp DESC
                    LIMIT 100
                """, ())
                
                candles = [dict(row) for row in cur.fetchall()]
        
        if not candles:
            raise HTTPException(status_code=404, detail="No market data available")
        
        prices = [c['close'] for c in candles]
        
        # Calculate metrics
        volatility = (max(prices[:20]) - min(prices[:20])) / min(prices[:20]) * 100
        trend = (prices[0] - prices[19]) / prices[19] * 100
        
        # Classify regime
        if volatility > 5:
            regime = "high_volatility"
            confidence = 85
        elif abs(trend) > 10:
            regime = f"strong_trend_{'up' if trend > 0 else 'down'}"
            confidence = 80
        elif abs(trend) < 2:
            regime = "ranging"
            confidence = 75
        else:
            regime = "normal"
            confidence = 70
        
        return {
            "status": "success",
            "regime": regime,
            "confidence": confidence,
            "metrics": {
                "volatility_pct": round(volatility, 2),
                "trend_pct": round(trend, 2)
            }
        }
    
    except Exception as e:
        logger.error("market_regime_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/stats")
def get_stats():
    """Get AI API statistics"""
    return {
        "status": "success",
        "ai_enabled": anthropic_client is not None,
        "features": {
            "signal_validation": anthropic_client is not None,
            "indicator_suggestions": anthropic_client is not None,
            "trade_explanations": anthropic_client is not None,
            "symbol_discovery": True,
            "sentiment_analysis": False,  # Needs social media APIs
            "autonomous_agent": anthropic_client is not None,  # Phase 6
        }
    }

# ==================== PHASE 6: AI AGENT ENDPOINTS ====================

@app.get("/agent/config")
def get_agent_config():
    """Get AI agent configuration"""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM agent_config ORDER BY id DESC LIMIT 1")
                config = cur.fetchone()
                
                if not config:
                    raise HTTPException(status_code=404, detail="No agent config found")
                
                return {
                    "status": "success",
                    "config": dict(config)
                }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error("agent_config_fetch_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

class AgentConfigUpdate(BaseModel):
    enabled: Optional[bool] = None
    mode: Optional[str] = None
    max_trades_per_day: Optional[int] = None
    max_position_size_pct: Optional[float] = None
    max_daily_loss_pct: Optional[float] = None
    min_confidence_threshold: Optional[float] = None

@app.put("/agent/config")
def update_agent_config(update: AgentConfigUpdate):
    """Update AI agent configuration"""
    try:
        updates = update.dict(exclude_none=True)
        
        if not updates:
            raise HTTPException(status_code=400, detail="No updates provided")
        
        # Validate mode
        if 'mode' in updates and updates['mode'] not in ['dry_run', 'live']:
            raise HTTPException(status_code=400, detail="Mode must be 'dry_run' or 'live'")
        
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Build update query
                set_clauses = [f"{key} = %s" for key in updates.keys()]
                set_clauses.append("updated_at = NOW()")
                values = list(updates.values())
                
                cur.execute(f"""
                    UPDATE agent_config
                    SET {', '.join(set_clauses)}
                    WHERE id = (SELECT id FROM agent_config ORDER BY id DESC LIMIT 1)
                    RETURNING *
                """, values)
                
                updated_config = cur.fetchone()
                
                if not updated_config:
                    raise HTTPException(status_code=404, detail="No config to update")
                
                logger.info("agent_config_updated", updates=updates)
                
                return {
                    "status": "success",
                    "config": dict(updated_config)
                }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error("agent_config_update_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/agent/decisions")
def get_agent_decisions(limit: int = Query(default=20, ge=1, le=100)):
    """Get AI agent decision history"""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT 
                        id,
                        cycle_timestamp,
                        reasoning,
                        decisions,
                        execution_results,
                        portfolio_value_before,
                        portfolio_value_after,
                        mode,
                        created_at
                    FROM agent_decisions
                    ORDER BY cycle_timestamp DESC
                    LIMIT %s
                """, (limit,))
                
                decisions = [dict(row) for row in cur.fetchall()]
                
                return {
                    "status": "success",
                    "decisions": decisions,
                    "count": len(decisions)
                }
    
    except Exception as e:
        logger.error("agent_decisions_fetch_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/agent/decisions/{decision_id}")
def get_agent_decision_detail(decision_id: int):
    """Get detailed information about a specific agent decision"""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT * FROM agent_decisions WHERE id = %s
                """, (decision_id,))
                
                decision = cur.fetchone()
                
                if not decision:
                    raise HTTPException(status_code=404, detail="Decision not found")
                
                return {
                    "status": "success",
                    "decision": dict(decision)
                }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error("agent_decision_detail_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/agent/run")
async def trigger_agent_cycle():
    """Manually trigger an AI agent decision cycle"""
    try:
        if not anthropic_client:
            raise HTTPException(status_code=503, detail="AI features not available (missing API key)")
        
        # Import agent
        from agent import TradingAgent
        
        # Create agent instance
        agent = TradingAgent(mode='dry_run')
        
        # Run decision cycle
        logger.info("manual_agent_trigger")
        result = await agent.run_decision_cycle()
        
        return {
            "status": "success",
            "result": result
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error("agent_trigger_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/agent/status")
def get_agent_status():
    """Get current AI agent status and recent performance"""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Get config
                cur.execute("SELECT * FROM agent_config ORDER BY id DESC LIMIT 1")
                config = cur.fetchone()
                
                if not config:
                    return {
                        "status": "not_configured",
                        "message": "Agent not configured"
                    }
                
                config = dict(config)
                
                # Get recent decision stats
                cur.execute("""
                    SELECT 
                        COUNT(*) as total_cycles,
                        COUNT(*) FILTER (WHERE error IS NULL) as successful_cycles,
                        COUNT(*) FILTER (WHERE error IS NOT NULL) as failed_cycles,
                        MAX(cycle_timestamp) as last_cycle,
                        AVG(portfolio_value_after - portfolio_value_before) as avg_portfolio_change
                    FROM agent_decisions
                    WHERE cycle_timestamp > NOW() - INTERVAL '7 days'
                """)
                
                stats = dict(cur.fetchone())
                
                # Get recent actions
                cur.execute("""
                    SELECT decisions
                    FROM agent_decisions
                    WHERE error IS NULL
                    ORDER BY cycle_timestamp DESC
                    LIMIT 10
                """)
                
                recent_decisions = [dict(row) for row in cur.fetchall()]
                
                # Count action types
                action_counts = {}
                for decision in recent_decisions:
                    actions = decision.get('decisions', {}).get('actions', [])
                    for action in actions:
                        action_type = action.get('type', 'UNKNOWN')
                        action_counts[action_type] = action_counts.get(action_type, 0) + 1
                
                return {
                    "status": "success",
                    "agent": {
                        "enabled": config['enabled'],
                        "mode": config['mode'],
                        "last_cycle": stats['last_cycle'],
                    },
                    "performance": {
                        "total_cycles": stats['total_cycles'],
                        "successful_cycles": stats['successful_cycles'],
                        "failed_cycles": stats['failed_cycles'],
                        "avg_portfolio_change": float(stats['avg_portfolio_change']) if stats['avg_portfolio_change'] else 0
                    },
                    "recent_actions": action_counts
                }
    
    except Exception as e:
        logger.error("agent_status_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

# PHASE 2: AI as Risk Manager (Not Signal Voter)
# Professional quant firms use AI for exits, sizing, and risk - not signal decisions

class ExitOptimizationRequest(BaseModel):
    """Request for AI to optimize exit parameters per symbol"""
    symbol: str
    entry_price: float
    signal_quality: float
    timeframe_minutes: Optional[int] = 240
    recent_volatility: Optional[float] = None  # ATR as % of price
    market_regime: Optional[str] = None
    strategy_win_rate: Optional[float] = None

class PositionGuardrailAdjustment(BaseModel):
    """Request for AI to adjust guardrails on open position"""
    position_id: int
    symbol: str
    entry_price: float
    current_price: float
    unrealized_pnl_pct: float
    minutes_held: int
    current_volatility: Optional[float] = None
    current_momentum: Optional[str] = None

@app.post("/optimize-exit")
def optimize_exit_parameters(request: ExitOptimizationRequest):
    """AI determines optimal stop-loss and take-profit for a symbol"""
    try:
        if not anthropic_client:
            return {
                "stop_loss_pct": 2.0,
                "take_profit_pct": 5.0,
                "trailing_stop_pct": 1.0,
                "max_hold_minutes": 240,
                "confidence": 0.5,
                "reasoning": "AI not available - using defaults"
            }
        
        prompt = f"""You are a risk management AI for crypto trading. Set intelligent GUARDRAILS (stops/targets) for a position based on symbol characteristics.

Position Setup:
- Symbol: {request.symbol}
- Entry: ${request.entry_price:.4f}
- Quality: {request.signal_quality:.0f}/100
- Timeframe: {request.timeframe_minutes}min
- Volatility: {f"{request.recent_volatility:.2%}" if request.recent_volatility else "Unknown"}
- Regime: {request.market_regime or "Unknown"}
- Win Rate: {f"{request.strategy_win_rate:.1%}" if request.strategy_win_rate else "Unknown"}

Rules:
- High volatility → Tight stop (1.5-2%), wider target (4-6%)
- Low volatility → Normal stop (2-2.5%), normal target (3-5%)
- Trending → Wider stop, enable trailing after +2%
- Ranging/choppy → Tight stop and target
- Short timeframe → Tighter parameters
- Low win rate → Conservative (tight stop, quick target)

Return ONLY JSON:
{{"stop_loss_pct": 2.0, "take_profit_pct": 5.0, "trailing_stop_pct": 1.0, "max_hold_minutes": 240, "confidence": 0.85, "reasoning": "Brief explanation"}}"""

        response = anthropic_client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}]
        )
        
        ai_text = response.content[0].text.strip()
        if "```" in ai_text:
            ai_text = ai_text.split("```")[1].replace("json", "").strip()
        
        import json
        result = json.loads(ai_text)
        
        # Constrain values
        result['stop_loss_pct'] = max(1.0, min(3.0, result.get('stop_loss_pct', 2.0)))
        result['take_profit_pct'] = max(2.0, min(10.0, result.get('take_profit_pct', 5.0)))
        result['trailing_stop_pct'] = max(0.5, min(2.0, result.get('trailing_stop_pct', 1.0)))
        result['max_hold_minutes'] = max(30, min(720, result.get('max_hold_minutes', 240)))
        
        logger.info("ai_exit_optimized", symbol=request.symbol, stop=result['stop_loss_pct'], target=result['take_profit_pct'])
        return result
        
    except Exception as e:
        logger.error("exit_optimization_error", error=str(e))
        return {
            "stop_loss_pct": 2.0,
            "take_profit_pct": 5.0,
            "trailing_stop_pct": 1.0,
            "max_hold_minutes": 240,
            "confidence": 0.5,
            "reasoning": f"Error: {str(e)[:50]}"
        }

@app.post("/adjust-guardrails")
def adjust_position_guardrails(request: PositionGuardrailAdjustment):
    """AI dynamically adjusts stop-loss/take-profit on open positions"""
    try:
        if not anthropic_client:
            return {"action": "hold", "new_stop_loss_pct": None, "reasoning": "AI not available"}
        
        prompt = f"""Monitor an OPEN position and decide if we should adjust guardrails.

Position:
- Symbol: {request.symbol}
- Entry: ${request.entry_price:.4f} → Now: ${request.current_price:.4f}
- P&L: {request.unrealized_pnl_pct:+.2f}%
- Held: {request.minutes_held}min ({request.minutes_held/60:.1f}hrs)
- Volatility: {f"{request.current_volatility:.2%}" if request.current_volatility else "Unknown"}
- Momentum: {request.current_momentum or "Unknown"}

Actions:
- Hitting target + strong momentum → raise_stop (to breakeven, let it run)
- Hitting target + weak momentum → take_profit
- Near breakeven + high volatility → tighten_stop
- In profit + held long → raise_stop (trail it)
- Small loss + reversing → exit_now

Return ONLY JSON:
{{"action": "hold|tighten_stop|raise_stop|exit_now|take_profit", "new_stop_loss_pct": 1.5, "new_take_profit_pct": 7.0, "reasoning": "Brief"}}"""

        response = anthropic_client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}]
        )
        
        ai_text = response.content[0].text.strip()
        if "```" in ai_text:
            ai_text = ai_text.split("```")[1].replace("json", "").strip()
        
        import json
        result = json.loads(ai_text)
        
        logger.info("ai_guardrail_adjusted", position=request.position_id, action=result.get('action'))
        return result
        
    except Exception as e:
        logger.error("guardrail_adjustment_error", error=str(e))
        return {"action": "hold", "reasoning": f"Error: {str(e)[:50]}"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("services.ai_api.main:app", host="0.0.0.0", port=settings.port_ai_api, workers=4)
