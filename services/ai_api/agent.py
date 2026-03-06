"""Autonomous AI Agent for Trading System Management (Phase 6)"""
import json
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from anthropic import Anthropic
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from shared.database import get_connection
from shared.config import get_settings
from shared.logging_config import setup_logging

settings = get_settings()
logger = setup_logging('ai_agent', settings.log_level)


class TradingAgent:
    """Autonomous AI agent that manages the trading system"""
    
    def __init__(self, mode='dry_run'):
        self.mode = mode  # 'dry_run' or 'live'
        self.anthropic_client = None
        
        if settings.anthropic_api_key:
            self.anthropic_client = Anthropic(api_key=settings.anthropic_api_key)
        else:
            logger.warning("anthropic_key_missing", msg="AI agent disabled")
        
        self.config = self.load_config()
        self.base_urls = {
            'portfolio': f"http://{settings.service_host}:{settings.port_portfolio_api}",
            'signal': f"http://{settings.service_host}:{settings.port_signal_api}",
            'config': f"http://{settings.service_host}:{settings.port_strategy_config_api}",
            'trading': f"http://{settings.service_host}:{settings.port_trading_api}",
            'afteraction': f"http://{settings.service_host}:{settings.port_afteraction_api}",
        }

    @property
    def portfolio_mode(self) -> str:
        """Map agent mode to portfolio API mode (which only accepts 'paper' or 'live').
        dry_run is treated as paper trading for portfolio queries."""
        return 'paper' if self.mode == 'dry_run' else self.mode
    
    def load_config(self) -> Dict:
        """Load agent configuration from database"""
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT * FROM agent_config ORDER BY id DESC LIMIT 1")
                    config = cur.fetchone()
                    
                    if config:
                        return dict(config)
                    
                    # Return defaults if no config found
                    return {
                        'enabled': False,
                        'mode': 'dry_run',
                        'max_trades_per_day': 20,
                        'max_position_size_pct': 50.0,
                        'max_daily_loss_pct': 10.0,
                        'min_confidence_threshold': 70.0,
                        'provider': 'anthropic',
                        'model': 'claude-3-5-sonnet-20241022'
                    }
        except Exception as e:
            logger.error("config_load_error", error=str(e))
            return {'enabled': False}
    
    def gather_system_state(self) -> Dict[str, Any]:
        """Gather comprehensive system state for AI decision-making"""
        logger.info("gathering_system_state")
        
        state = {
            'timestamp': datetime.utcnow().isoformat(),
            'portfolio': self.get_portfolio_state(),
            'open_positions': self.get_open_positions(),
            'pending_signals': self.get_pending_signals(),
            'recent_trades': self.get_recent_trades(),
            'strategy_performance': self.get_strategy_performance(),
            'afteraction_insights': self.get_afteraction_insights(),
            'market_regimes': self.get_market_regimes(),
            'today_stats': self.get_today_stats(),
        }
        
        logger.info("system_state_gathered", 
                   positions=len(state['open_positions']),
                   signals=len(state['pending_signals']))
        
        return state
    
    def get_portfolio_state(self) -> Dict:
        """Get current portfolio value and stats"""
        try:
            response = requests.get(
                f"{self.base_urls['portfolio']}/portfolio",
                params={'mode': self.portfolio_mode},
                timeout=5
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error("portfolio_fetch_error", error=str(e))
            return {'total_value': 0, 'cash': 0, 'error': str(e)}
    
    def get_open_positions(self) -> List[Dict]:
        """Get all open positions"""
        try:
            response = requests.get(
                f"{self.base_urls['portfolio']}/positions",
                params={'mode': self.portfolio_mode, 'status': 'open'},
                timeout=5
            )
            response.raise_for_status()
            data = response.json()
            return data.get('positions', [])
        except Exception as e:
            logger.error("positions_fetch_error", error=str(e))
            return []
    
    def get_pending_signals(self) -> List[Dict]:
        """Get pending high-quality signals"""
        try:
            response = requests.get(
                f"{self.base_urls['signal']}/signals",
                params={'status': 'pending', 'min_quality': 60},
                timeout=5
            )
            response.raise_for_status()
            data = response.json()
            return data.get('signals', [])[:20]  # Top 20 signals
        except Exception as e:
            logger.error("signals_fetch_error", error=str(e))
            return []
    
    def get_recent_trades(self) -> List[Dict]:
        """Get recent closed trades (last 24 hours)"""
        try:
            response = requests.get(
                f"{self.base_urls['portfolio']}/positions",
                params={
                    'mode': self.mode,
                    'status': 'closed',
                    'limit': 50
                },
                timeout=5
            )
            response.raise_for_status()
            data = response.json()
            positions = data.get('positions', [])
            
            # Filter to last 24 hours
            cutoff = datetime.utcnow() - timedelta(hours=24)
            recent = []
            for pos in positions:
                closed_at = datetime.fromisoformat(pos['closed_at'].replace('Z', '+00:00'))
                if closed_at > cutoff:
                    recent.append(pos)
            
            return recent
        except Exception as e:
            logger.error("recent_trades_error", error=str(e))
            return []
    
    def get_strategy_performance(self) -> List[Dict]:
        """Get strategy performance metrics"""
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT 
                            strategy_id,
                            symbol,
                            win_rate,
                            total_trades,
                            avg_profit_pct,
                            updated_at
                        FROM strategy_performance
                        WHERE total_trades >= 10
                        ORDER BY win_rate DESC
                        LIMIT 20
                    """)
                    
                    rows = cur.fetchall()
                    return [dict(row) for row in rows]
        except Exception as e:
            logger.error("strategy_performance_error", error=str(e))
            return []
    
    def get_afteraction_insights(self) -> List[Dict]:
        """Get recent AfterAction analysis insights"""
        try:
            response = requests.get(
                f"{self.base_urls['afteraction']}/afteractions",
                params={'limit': 10},
                timeout=5
            )
            response.raise_for_status()
            data = response.json()
            return data.get('afteractions', [])
        except Exception as e:
            logger.error("afteraction_fetch_error", error=str(e))
            return []
    
    def get_market_regimes(self) -> List[Dict]:
        """Get current market regimes"""
        try:
            response = requests.get(
                f"{self.base_urls['signal']}/regimes",
                timeout=5
            )
            response.raise_for_status()
            data = response.json()
            return data.get('regimes', [])
        except Exception as e:
            logger.error("regimes_fetch_error", error=str(e))
            return []
    
    def get_today_stats(self) -> Dict:
        """Calculate today's trading statistics"""
        try:
            recent_trades = self.get_recent_trades()
            
            if not recent_trades:
                return {
                    'trades_today': 0,
                    'pnl_today': 0,
                    'pnl_pct': 0,
                    'wins': 0,
                    'losses': 0,
                    'win_rate': 0
                }
            
            pnl_today = sum(float(t.get('pnl', 0)) for t in recent_trades)
            wins = sum(1 for t in recent_trades if float(t.get('pnl', 0)) > 0)
            losses = len(recent_trades) - wins
            
            portfolio = self.get_portfolio_state()
            total_value = float(portfolio.get('total_value', 1000))
            pnl_pct = (pnl_today / total_value) * 100 if total_value > 0 else 0
            
            return {
                'trades_today': len(recent_trades),
                'pnl_today': round(pnl_today, 2),
                'pnl_pct': round(pnl_pct, 2),
                'wins': wins,
                'losses': losses,
                'win_rate': round((wins / len(recent_trades)) * 100, 1) if recent_trades else 0
            }
        except Exception as e:
            logger.error("today_stats_error", error=str(e))
            return {
                'trades_today': 0,
                'pnl_today': 0,
                'pnl_pct': 0,
                'wins': 0,
                'losses': 0,
                'win_rate': 0
            }
    
    def build_decision_prompt(self, state: Dict) -> str:
        """Build comprehensive prompt for AI decision-making"""
        
        portfolio = state['portfolio']
        today = state['today_stats']
        positions = state['open_positions']
        signals = state['pending_signals']
        
        # Format strategy performance (with safe access)
        strategy_perf_list = []
        for s in state['strategy_performance'][:5]:
            try:
                strategy_perf_list.append(
                    f"  - Strategy {s.get('strategy_id', 'N/A')} ({s.get('symbol', 'N/A')}): "
                    f"{float(s.get('win_rate', 0)):.1f}% win rate, {s.get('total_trades', 0)} trades"
                )
            except Exception as e:
                logger.error("strategy_format_error", error=str(e), strategy=s)
        
        strategy_perf = "\n".join(strategy_perf_list) if strategy_perf_list else "  No data yet"
        
        strategy_perf = "\n".join(strategy_perf_list) if strategy_perf_list else "  No data yet"
        
        # Format pending signals (with safe access)
        signals_list = []
        for i, s in enumerate(signals[:10]):
            try:
                signals_list.append(
                    f"  {i+1}. {s.get('signal', 'UNKNOWN')} {s.get('symbol', 'N/A')} - "
                    f"Quality: {s.get('quality_score', 0)}/100 (Strategy {s.get('strategy_id', 'N/A')})"
                )
            except Exception as e:
                logger.error("signal_format_error", error=str(e))
        
        signals_text = "\n".join(signals_list) if signals_list else "  None pending"
        
        # Format open positions (with safe access)
        positions_list = []
        for p in positions:
            try:
                positions_list.append(
                    f"  - {p.get('symbol', 'N/A')}: {p.get('side', 'N/A')} @ "
                    f"${p.get('entry_price', 0)}, PnL: ${p.get('unrealized_pnl', 0):.2f}"
                )
            except Exception as e:
                logger.error("position_format_error", error=str(e))
        
        positions_text = "\n".join(positions_list) if positions_list else "  None"
        
        # Format market regimes (with safe access)
        regimes_list = []
        for r in state['market_regimes'][:5]:
            try:
                regimes_list.append(
                    f"  - {r.get('symbol', 'N/A')}: {r.get('regime', 'unknown')} "
                    f"({r.get('confidence', 0)}% confidence)"
                )
            except Exception as e:
                logger.error("regime_format_error", error=str(e))
        
        regimes_text = "\n".join(regimes_list) if regimes_list else "  Loading..."

        
        prompt = f"""You are an autonomous trading system manager. Analyze the current state and decide what actions to take.

===== CURRENT SYSTEM STATE =====

Portfolio:
- Total Value: ${portfolio.get('total_value', 0):.2f}
- Available Cash: ${portfolio.get('cash', 0):.2f}
- Open Positions: {len(positions)}

Today's Performance:
- Trades Executed: {today['trades_today']}
- P&L: ${today['pnl_today']:.2f} ({today['pnl_pct']:.2f}%)
- Win Rate: {today['win_rate']}%
- Wins/Losses: {today['wins']}/{today['losses']}

Open Positions ({len(positions)}):
{positions_text}

Pending High-Quality Signals ({len(signals)}):
{signals_text}

Top Performing Strategies:
{strategy_perf if strategy_perf else "  No data yet"}

Current Market Regimes:
{regimes_text if regimes_text else "  Loading..."}

===== GUARDRAILS =====
- Max {self.config['max_trades_per_day']} trades per day (used: {today['trades_today']})
- Max {self.config['max_position_size_pct']}% portfolio per position
- Stop trading if daily loss exceeds {self.config['max_daily_loss_pct']}%
- Current mode: {self.config['mode'].upper()}

===== AVAILABLE ACTIONS =====
1. TAKE_SIGNAL: Open position on a pending signal (specify signal_id, position_size_pct)
2. CLOSE_POSITION: Close an open position (specify position_id, reason)
3. ADJUST_STOP: Modify stop loss on position (specify position_id, new_stop_price)
4. DO_NOTHING: Wait for better opportunities (always an option)

===== YOUR TASK =====
Analyze this situation and decide what to do. Consider:
- Are we approaching daily trade limits?
- Is today's P&L concerning? Should we reduce risk?
- Are there high-quality signals worth taking?
- Should any losing positions be cut?
- Should any winning positions be protected with tighter stops?

Respond in VALID JSON format only (no markdown, no code blocks):
{{
  "reasoning": "Your detailed analysis in 3-5 sentences",
  "sentiment": "bullish/neutral/bearish",
  "confidence": 0-100,
  "actions": [
    {{
      "type": "TAKE_SIGNAL|CLOSE_POSITION|ADJUST_STOP|DO_NOTHING",
      "params": {{}},
      "reasoning": "Why this action?"
    }}
  ]
}}

If no good opportunities, return actions with just DO_NOTHING.
"""
        
        return prompt
    
    async def run_decision_cycle(self) -> Dict:
        """Main decision loop - called by Celery task"""
        logger.info("agent_cycle_started", mode=self.config['mode'])
        
        cycle_start = datetime.utcnow()
        
        try:
            # Check if agent is enabled
            if not self.config.get('enabled', False):
                logger.info("agent_disabled")
                return {
                    'status': 'skipped',
                    'reason': 'Agent is disabled in config'
                }
            
            # Check if AI client is available
            if not self.anthropic_client:
                logger.error("anthropic_unavailable")
                return {
                    'status': 'error',
                    'reason': 'Anthropic API key not configured'
                }
            
            # Gather system state
            state = self.gather_system_state()
            
            # Check if we've hit daily loss limit
            if state['today_stats']['pnl_pct'] <= -self.config['max_daily_loss_pct']:
                logger.warning("daily_loss_limit_reached", 
                             pnl_pct=state['today_stats']['pnl_pct'])
                return {
                    'status': 'halted',
                    'reason': f"Daily loss limit reached: {state['today_stats']['pnl_pct']}%"
                }
            
            # Check if we've hit trade limit
            if state['today_stats']['trades_today'] >= self.config['max_trades_per_day']:
                logger.info("trade_limit_reached", 
                           trades=state['today_stats']['trades_today'])
                return {
                    'status': 'halted',
                    'reason': f"Daily trade limit reached: {state['today_stats']['trades_today']}"
                }
            
            # Build prompt for AI
            prompt = self.build_decision_prompt(state)
            
            # Call Claude for decision
            logger.info("calling_claude_for_decision")
            
            response = self.anthropic_client.messages.create(
                model=self.config.get('model', 'claude-3-5-sonnet-20241022'),
                max_tokens=2000,
                messages=[{
                    "role": "user",
                    "content": prompt
                }]
            )
            
            ai_response = response.content[0].text
            logger.info("ai_response_received", length=len(ai_response))
            
            # Parse AI decision
            decision = self.parse_ai_decision(ai_response)
            
            # Execute actions (or log them in dry_run mode)
            execution_results = await self.execute_actions(decision['actions'], state)
            
            # Save to audit trail
            portfolio_before = float(state['portfolio'].get('total_value', 0))
            portfolio_after = float(self.get_portfolio_state().get('total_value', 0))
            
            self.save_decision_to_audit(
                cycle_start,
                state,
                ai_response,
                decision,
                execution_results,
                portfolio_before,
                portfolio_after
            )
            
            logger.info("agent_cycle_completed", 
                       actions=len(decision['actions']),
                       mode=self.config['mode'])
            
            return {
                'status': 'success',
                'cycle_timestamp': cycle_start.isoformat(),
                'decision': decision,
                'execution_results': execution_results,
                'portfolio_change': portfolio_after - portfolio_before
            }
        
        except Exception as e:
            logger.error("agent_cycle_error", error=str(e))
            
            # Save error to audit
            try:
                self.save_error_to_audit(cycle_start, str(e))
            except:
                pass
            
            return {
                'status': 'error',
                'error': str(e)
            }
    
    def parse_ai_decision(self, ai_response: str) -> Dict:
        """Parse AI response into structured decision"""
        try:
            # Try to extract JSON from response
            # Sometimes Claude wraps it in markdown code blocks
            response_clean = ai_response.strip()
            
            if response_clean.startswith('```'):
                # Remove code block markers
                lines = response_clean.split('\n')
                response_clean = '\n'.join(lines[1:-1])
            
            decision = json.loads(response_clean)
            
            # Validate structure
            if 'actions' not in decision:
                decision['actions'] = [{'type': 'DO_NOTHING', 'params': {}, 'reasoning': 'No actions specified'}]
            
            return decision
        
        except json.JSONDecodeError as e:
            logger.error("ai_response_parse_error", error=str(e), response=ai_response[:200])
            
            # Return safe default
            return {
                'reasoning': 'Failed to parse AI response',
                'sentiment': 'neutral',
                'confidence': 0,
                'actions': [{'type': 'DO_NOTHING', 'params': {}, 'reasoning': 'Parse error'}]
            }
    
    async def execute_actions(self, actions: List[Dict], state: Dict) -> List[Dict]:
        """Execute AI's decided actions"""
        results = []
        
        for action in actions:
            action_type = action.get('type', 'DO_NOTHING')
            params = action.get('params', {})
            
            logger.info("executing_action", type=action_type, params=params)
            
            try:
                if action_type == 'DO_NOTHING':
                    results.append({
                        'action': action_type,
                        'status': 'success',
                        'message': 'No action taken',
                        'executed': False
                    })
                
                elif action_type == 'TAKE_SIGNAL':
                    result = await self.execute_take_signal(params)
                    results.append(result)
                
                elif action_type == 'CLOSE_POSITION':
                    result = await self.execute_close_position(params)
                    results.append(result)
                
                elif action_type == 'ADJUST_STOP':
                    result = await self.execute_adjust_stop(params)
                    results.append(result)
                
                else:
                    results.append({
                        'action': action_type,
                        'status': 'error',
                        'message': f'Unknown action type: {action_type}',
                        'executed': False
                    })
            
            except Exception as e:
                logger.error("action_execution_error", action=action_type, error=str(e))
                results.append({
                    'action': action_type,
                    'status': 'error',
                    'message': str(e),
                    'executed': False
                })
        
        return results
    
    async def execute_take_signal(self, params: Dict) -> Dict:
        """Execute taking a signal (opening a position)"""
        
        if self.config['mode'] == 'dry_run':
            return {
                'action': 'TAKE_SIGNAL',
                'status': 'dry_run',
                'message': f"DRY RUN: Would open position on signal {params.get('signal_id')}",
                'params': params,
                'executed': False
            }
        
        # In live mode, actually create the position
        try:
            response = requests.post(
                f"{self.base_urls['trading']}/execute",
                json={
                    'signal_id': params['signal_id'],
                    'position_size_pct': params.get('position_size_pct', 5),
                    'mode': 'paper'
                },
                timeout=10
            )
            response.raise_for_status()
            
            return {
                'action': 'TAKE_SIGNAL',
                'status': 'success',
                'message': 'Position opened',
                'params': params,
                'result': response.json(),
                'executed': True
            }
        
        except Exception as e:
            return {
                'action': 'TAKE_SIGNAL',
                'status': 'error',
                'message': str(e),
                'params': params,
                'executed': False
            }
    
    async def execute_close_position(self, params: Dict) -> Dict:
        """Execute closing a position"""
        
        if self.config['mode'] == 'dry_run':
            return {
                'action': 'CLOSE_POSITION',
                'status': 'dry_run',
                'message': f"DRY RUN: Would close position {params.get('position_id')}",
                'params': params,
                'executed': False
            }
        
        # In live mode, actually close the position
        try:
            response = requests.post(
                f"{self.base_urls['portfolio']}/positions/{params['position_id']}/close",
                json={'reason': params.get('reason', 'AI agent decision')},
                timeout=10
            )
            response.raise_for_status()
            
            return {
                'action': 'CLOSE_POSITION',
                'status': 'success',
                'message': 'Position closed',
                'params': params,
                'result': response.json(),
                'executed': True
            }
        
        except Exception as e:
            return {
                'action': 'CLOSE_POSITION',
                'status': 'error',
                'message': str(e),
                'params': params,
                'executed': False
            }
    
    async def execute_adjust_stop(self, params: Dict) -> Dict:
        """Execute adjusting stop loss"""
        
        if self.config['mode'] == 'dry_run':
            return {
                'action': 'ADJUST_STOP',
                'status': 'dry_run',
                'message': f"DRY RUN: Would adjust stop for position {params.get('position_id')}",
                'params': params,
                'executed': False
            }
        
        # In live mode, actually adjust the stop
        try:
            response = requests.patch(
                f"{self.base_urls['portfolio']}/positions/{params['position_id']}",
                json={'stop_loss_price': params['new_stop_price']},
                timeout=10
            )
            response.raise_for_status()
            
            return {
                'action': 'ADJUST_STOP',
                'status': 'success',
                'message': 'Stop loss adjusted',
                'params': params,
                'result': response.json(),
                'executed': True
            }
        
        except Exception as e:
            return {
                'action': 'ADJUST_STOP',
                'status': 'error',
                'message': str(e),
                'params': params,
                'executed': False
            }
    
    def save_decision_to_audit(self, cycle_time, state, ai_response, decision, execution_results, 
                               portfolio_before, portfolio_after):
        """Save decision cycle to audit trail"""
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO agent_decisions 
                        (cycle_timestamp, system_state, ai_response, decisions, 
                         actions_executed, execution_results, reasoning,
                         portfolio_value_before, portfolio_value_after, mode)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        cycle_time,
                        json.dumps(state, default=str),
                        ai_response,
                        json.dumps(decision),
                        json.dumps([a for a in decision.get('actions', [])]),
                        json.dumps(execution_results, default=str),
                        decision.get('reasoning', ''),
                        portfolio_before,
                        portfolio_after,
                        self.config['mode']
                    ))
            
            logger.info("decision_saved_to_audit")
        
        except Exception as e:
            logger.error("audit_save_error", error=str(e))
    
    def save_error_to_audit(self, cycle_time, error):
        """Save error to audit trail"""
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO agent_decisions 
                        (cycle_timestamp, system_state, ai_response, decisions, 
                         actions_executed, execution_results, error, mode)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        cycle_time,
                        json.dumps({'error': 'Failed to gather state'}),
                        '',
                        json.dumps({}),
                        json.dumps([]),
                        json.dumps([]),
                        error,
                        self.config['mode']
                    ))
        except:
            pass
