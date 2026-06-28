#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from flask import Flask, render_template, jsonify, request, send_from_directory
from flask_cors import CORS
from flask_socketio import SocketIO, emit
from datetime import datetime, timedelta
import yfinance as yf
import pandas as pd
import numpy as np
import os
import pytz
import logging
import json
import time
import threading
from sklearn.linear_model import LinearRegression
from sklearn.preprocessing import PolynomialFeatures
from sklearn.pipeline import make_pipeline
import warnings
warnings.filterwarnings('ignore')

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder='static', template_folder='templates')
app.config['SECRET_KEY'] = 'trading-monitor-secret-key'
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

US_TIMEZONE = pytz.timezone('America/New_York')
cache = {}
CACHE_DURATION = 30

# ============================================================
# FONCTIONS UTILITAIRES
# ============================================================

def get_cached(key):
    if key in cache:
        data, ts = cache[key]
        if (datetime.now() - ts).seconds < CACHE_DURATION:
            return data
    return None

def set_cached(key, data):
    cache[key] = (data, datetime.now())

def get_interval_for_period(period):
    intervals = {
        '1d': '1m',
        '5d': '5m',
        '1mo': '15m',
        '3mo': '1h',
        '6mo': '1d',
        '1y': '1d'
    }
    return intervals.get(period, '1d')

def safe_float(v, default=0.0):
    try:
        if pd.isna(v) or v is None:
            return default
        return float(v)
    except:
        return default

def safe_int(v, default=0):
    try:
        if pd.isna(v) or v is None:
            return default
        return int(v)
    except:
        return default

# ============================================================
# DONNÉES PAR CATÉGORIE (Symboles VALIDES uniquement)
# ============================================================

ASSETS = {
    # Commodités
    'GC=F': {'name': 'Or', 'exchange': 'COMEX', 'category': 'Commodités', 'icon': '🥇', 'color': '#ffd700'},
    'SI=F': {'name': 'Argent', 'exchange': 'COMEX', 'category': 'Commodités', 'icon': '🥈', 'color': '#c0c0c0'},
    'CL=F': {'name': 'Pétrole WTI', 'exchange': 'NYMEX', 'category': 'Commodités', 'icon': '🛢️', 'color': '#ff6b00'},
    'BZ=F': {'name': 'Pétrole Brent', 'exchange': 'ICE', 'category': 'Commodités', 'icon': '🛢️', 'color': '#ff8c00'},
    'NG=F': {'name': 'Gaz Naturel', 'exchange': 'NYMEX', 'category': 'Commodités', 'icon': '🔥', 'color': '#00ccff'},
    'ZC=F': {'name': 'Maïs', 'exchange': 'CBOT', 'category': 'Commodités', 'icon': '🌽', 'color': '#ffd700'},
    'ZW=F': {'name': 'Blé', 'exchange': 'CBOT', 'category': 'Commodités', 'icon': '🌾', 'color': '#d4a574'},
    'ZS=F': {'name': 'Soja', 'exchange': 'CBOT', 'category': 'Commodités', 'icon': '🌱', 'color': '#8bc34a'},
    'KC=F': {'name': 'Café', 'exchange': 'ICE', 'category': 'Commodités', 'icon': '☕', 'color': '#6d4c41'},
    'CC=F': {'name': 'Cacao', 'exchange': 'ICE', 'category': 'Commodités', 'icon': '🍫', 'color': '#5d4037'},
    'HG=F': {'name': 'Cuivre', 'exchange': 'COMEX', 'category': 'Commodités', 'icon': '🔶', 'color': '#e65100'},

    # Crypto
    'BTC-USD': {'name': 'Bitcoin', 'exchange': 'CRYPTO', 'category': 'Crypto', 'icon': '₿', 'color': '#ffaa00'},
    'ETH-USD': {'name': 'Ethereum', 'exchange': 'CRYPTO', 'category': 'Crypto', 'icon': '⟠', 'color': '#627eea'},
    'SOL-USD': {'name': 'Solana', 'exchange': 'CRYPTO', 'category': 'Crypto', 'icon': '◎', 'color': '#9945ff'},
    'ADA-USD': {'name': 'Cardano', 'exchange': 'CRYPTO', 'category': 'Crypto', 'icon': '₳', 'color': '#0033ad'},
    'DOGE-USD': {'name': 'Dogecoin', 'exchange': 'CRYPTO', 'category': 'Crypto', 'icon': '🐕', 'color': '#c2a633'},
    'XRP-USD': {'name': 'Ripple', 'exchange': 'CRYPTO', 'category': 'Crypto', 'icon': '✕', 'color': '#00aae4'},
    'BNB-USD': {'name': 'Binance Coin', 'exchange': 'CRYPTO', 'category': 'Crypto', 'icon': '🟡', 'color': '#f3ba2f'},

    # Forex
    'EURUSD=X': {'name': 'EUR/USD', 'exchange': 'FOREX', 'category': 'Forex', 'icon': '🇪🇺🇺🇸', 'color': '#002395'},
    'GBPUSD=X': {'name': 'GBP/USD', 'exchange': 'FOREX', 'category': 'Forex', 'icon': '🇬🇧🇺🇸', 'color': '#012169'},
    'USDJPY=X': {'name': 'USD/JPY', 'exchange': 'FOREX', 'category': 'Forex', 'icon': '🇺🇸🇯🇵', 'color': '#bc002d'},
    'USDCHF=X': {'name': 'USD/CHF', 'exchange': 'FOREX', 'category': 'Forex', 'icon': '🇺🇸🇨🇭', 'color': '#da291c'},
    'AUDUSD=X': {'name': 'AUD/USD', 'exchange': 'FOREX', 'category': 'Forex', 'icon': '🇦🇺🇺🇸', 'color': '#00008b'},
    'USDCAD=X': {'name': 'USD/CAD', 'exchange': 'FOREX', 'category': 'Forex', 'icon': '🇺🇸🇨🇦', 'color': '#ff0000'},

    # US Stocks
    'AAPL': {'name': 'Apple', 'exchange': 'NASDAQ', 'category': 'US Stocks', 'icon': '🍎', 'color': '#555555'},
    'MSFT': {'name': 'Microsoft', 'exchange': 'NASDAQ', 'category': 'US Stocks', 'icon': '💻', 'color': '#00a4ef'},
    'GOOGL': {'name': 'Alphabet', 'exchange': 'NASDAQ', 'category': 'US Stocks', 'icon': '🔍', 'color': '#4285f4'},
    'NVDA': {'name': 'NVIDIA', 'exchange': 'NASDAQ', 'category': 'US Stocks', 'icon': '🎮', 'color': '#76b900'},
    'TSLA': {'name': 'Tesla', 'exchange': 'NASDAQ', 'category': 'US Stocks', 'icon': '🚗', 'color': '#cc0000'},
    'AMZN': {'name': 'Amazon', 'exchange': 'NASDAQ', 'category': 'US Stocks', 'icon': '📦', 'color': '#ff9900'},
    'META': {'name': 'Meta', 'exchange': 'NASDAQ', 'category': 'US Stocks', 'icon': '📱', 'color': '#1877f2'},
    'JPM': {'name': 'JPMorgan', 'exchange': 'NYSE', 'category': 'US Stocks', 'icon': '🏦', 'color': '#003399'},
    '^GSPC': {'name': 'S&P 500', 'exchange': 'INDEX', 'category': 'US Stocks', 'icon': '📈', 'color': '#000000'},

    # Paris (symboles VALIDES uniquement)
    'ML.PA': {'name': 'LVMH', 'exchange': 'Euronext', 'category': 'Paris Stocks', 'icon': '👔', 'color': '#000000'},
    'SAN.PA': {'name': 'Sanofi', 'exchange': 'Euronext', 'category': 'Paris Stocks', 'icon': '💊', 'color': '#005eb8'},
    'BNP.PA': {'name': 'BNP Paribas', 'exchange': 'Euronext', 'category': 'Paris Stocks', 'icon': '🏛️', 'color': '#0090b0'},
    'OR.PA': {'name': "L'Oréal", 'exchange': 'Euronext', 'category': 'Paris Stocks', 'icon': '💄', 'color': '#000000'},
    'AI.PA': {'name': 'Air Liquide', 'exchange': 'Euronext', 'category': 'Paris Stocks', 'icon': '💨', 'color': '#0050a0'},
    '^FCHI': {'name': 'CAC 40', 'exchange': 'Euronext', 'category': 'Paris Stocks', 'icon': '🇫🇷', 'color': '#002395'},

    # Eau
    'PHO': {'name': 'Invesco Water ETF', 'exchange': 'NASDAQ', 'category': 'Eau', 'icon': '🌊', 'color': '#0099cc'},
    'FIW': {'name': 'First Trust Water ETF', 'exchange': 'NASDAQ', 'category': 'Eau', 'icon': '🌊', 'color': '#0055aa'},
    'CGW': {'name': 'Invesco S&P Water ETF', 'exchange': 'NYSE', 'category': 'Eau', 'icon': '🌊', 'color': '#0077bb'},
    'AWK': {'name': 'American Water Works', 'exchange': 'NYSE', 'category': 'Eau', 'icon': '💧', 'color': '#004d99'},
    'XYL': {'name': 'Xylem Inc.', 'exchange': 'NYSE', 'category': 'Eau', 'icon': '💧', 'color': '#0088cc'},
}

WATCHLIST = list(ASSETS.keys())

# ============================================================
# CALCUL DES INDICATEURS TECHNIQUES
# ============================================================

def calculate_sma(data, period):
    if len(data) < period:
        return [None] * len(data)
    result = []
    for i in range(len(data)):
        if i < period - 1:
            result.append(None)
        else:
            result.append(sum(data[i-period+1:i+1]) / period)
    return result

def calculate_ema(data, period):
    if len(data) < period:
        return [None] * len(data)
    k = 2 / (period + 1)
    result = [data[0]]
    for i in range(1, len(data)):
        result.append(data[i] * k + result[-1] * (1 - k))
    return result

def calculate_rsi(data, period=14):
    if len(data) < period + 1:
        return [None] * len(data)

    result = [None] * len(data)
    gains = []
    losses = []

    for i in range(1, len(data)):
        diff = data[i] - data[i-1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    if avg_loss == 0:
        result[period] = 100
    else:
        result[period] = 100 - (100 / (1 + avg_gain / avg_loss))

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            result[i+1] = 100
        else:
            result[i+1] = 100 - (100 / (1 + avg_gain / avg_loss))

    return result

def calculate_macd(data, fast=12, slow=26, signal=9):
    if len(data) < slow:
        return {'macd': [None] * len(data), 'signal': [None] * len(data), 'histogram': [None] * len(data)}

    ema_fast = calculate_ema(data, fast)
    ema_slow = calculate_ema(data, slow)

    macd_line = []
    for i in range(len(data)):
        if ema_fast[i] is not None and ema_slow[i] is not None:
            macd_line.append(ema_fast[i] - ema_slow[i])
        else:
            macd_line.append(None)

    macd_clean = [x for x in macd_line if x is not None]
    signal_line = calculate_ema(macd_clean, signal) if macd_clean else []

    signal_full = [None] * len(data)
    idx = 0
    for i in range(len(data)):
        if macd_line[i] is not None:
            if idx < len(signal_line):
                signal_full[i] = signal_line[idx]
            idx += 1

    histogram = []
    for i in range(len(data)):
        if macd_line[i] is not None and signal_full[i] is not None:
            histogram.append(macd_line[i] - signal_full[i])
        else:
            histogram.append(None)

    return {'macd': macd_line, 'signal': signal_full, 'histogram': histogram}

def calculate_bollinger(data, period=20, std_mult=2):
    if len(data) < period:
        return {'upper': [None] * len(data), 'middle': [None] * len(data), 'lower': [None] * len(data)}

    sma = calculate_sma(data, period)
    upper = []
    lower = []

    for i in range(len(data)):
        if sma[i] is None:
            upper.append(None)
            lower.append(None)
        else:
            window = data[i-period+1:i+1]
            std = np.std(window)
            upper.append(sma[i] + std_mult * std)
            lower.append(sma[i] - std_mult * std)

    return {'upper': upper, 'middle': sma, 'lower': lower}

def calculate_atr(high, low, close, period=14):
    if len(close) < period + 1:
        return [None] * len(close)

    tr = []
    for i in range(1, len(close)):
        hl = high[i] - low[i]
        hc = abs(high[i] - close[i-1])
        lc = abs(low[i] - close[i-1])
        tr.append(max(hl, hc, lc))

    atr = [None] * len(close)
    atr[period] = sum(tr[:period]) / period

    for i in range(period, len(tr)):
        atr[i+1] = (atr[i] * (period - 1) + tr[i]) / period

    return atr

def calculate_stochastic(high, low, close, k_period=14, d_period=3):
    if len(close) < k_period:
        return {'k': [None] * len(close), 'd': [None] * len(close)}

    k_values = [None] * len(close)
    for i in range(k_period - 1, len(close)):
        high_max = max(high[i-k_period+1:i+1])
        low_min = min(low[i-k_period+1:i+1])
        if high_max == low_min:
            k_values[i] = 50
        else:
            k_values[i] = ((close[i] - low_min) / (high_max - low_min)) * 100

    d_values = [None] * len(close)
    for i in range(k_period - 1 + d_period - 1, len(close)):
        valid_k = [k for k in k_values[i-d_period+1:i+1] if k is not None]
        if valid_k:
            d_values[i] = sum(valid_k) / len(valid_k)

    return {'k': k_values, 'd': d_values}

def calculate_volatility(data, period=20):
    if len(data) < period + 1:
        return 0
    returns = []
    for i in range(len(data) - period, len(data)):
        if i > 0 and data[i-1] != 0:
            returns.append((data[i] - data[i-1]) / data[i-1])
    if len(returns) < 2:
        return 0
    std = np.std(returns)
    return std * np.sqrt(252) * 100

def calculate_all_indicators(candles):
    if not candles or len(candles) < 20:
        return {}

    close = [c['close'] for c in candles]
    high = [c['high'] for c in candles]
    low = [c['low'] for c in candles]
    current_price = close[-1] if close else 0

    indicators = {}

    indicators['sma_20'] = calculate_sma(close, 20)
    indicators['sma_50'] = calculate_sma(close, 50)
    indicators['sma_200'] = calculate_sma(close, 200)
    indicators['ema_12'] = calculate_ema(close, 12)
    indicators['ema_26'] = calculate_ema(close, 26)
    indicators['rsi'] = calculate_rsi(close, 14)

    macd = calculate_macd(close)
    indicators['macd'] = macd['macd']
    indicators['macd_signal'] = macd['signal']
    indicators['macd_histogram'] = macd['histogram']

    bb = calculate_bollinger(close)
    indicators['bb_upper'] = bb['upper']
    indicators['bb_middle'] = bb['middle']
    indicators['bb_lower'] = bb['lower']

    sto = calculate_stochastic(high, low, close)
    indicators['stoch_k'] = sto['k']
    indicators['stoch_d'] = sto['d']

    indicators['atr'] = calculate_atr(high, low, close)
    indicators['volatility'] = calculate_volatility(close)

    if len(close) >= 10:
        indicators['momentum'] = ((close[-1] - close[-10]) / close[-10]) * 100
    else:
        indicators['momentum'] = 0

    indicators['current_price'] = current_price
    indicators['last_rsi'] = indicators['rsi'][-1] if indicators['rsi'] and indicators['rsi'][-1] is not None else None
    indicators['last_macd'] = indicators['macd'][-1] if indicators['macd'] and indicators['macd'][-1] is not None else None
    indicators['last_macd_signal'] = indicators['macd_signal'][-1] if indicators['macd_signal'] and indicators['macd_signal'][-1] is not None else None
    indicators['last_sma_20'] = indicators['sma_20'][-1] if indicators['sma_20'] and indicators['sma_20'][-1] is not None else None
    indicators['last_sma_50'] = indicators['sma_50'][-1] if indicators['sma_50'] and indicators['sma_50'][-1] is not None else None
    indicators['last_sma_200'] = indicators['sma_200'][-1] if indicators['sma_200'] and indicators['sma_200'][-1] is not None else None
    indicators['last_stoch_k'] = indicators['stoch_k'][-1] if indicators['stoch_k'] and indicators['stoch_k'][-1] is not None else None
    indicators['last_stoch_d'] = indicators['stoch_d'][-1] if indicators['stoch_d'] and indicators['stoch_d'][-1] is not None else None
    indicators['last_bb_upper'] = indicators['bb_upper'][-1] if indicators['bb_upper'] and indicators['bb_upper'][-1] is not None else None
    indicators['last_bb_middle'] = indicators['bb_middle'][-1] if indicators['bb_middle'] and indicators['bb_middle'][-1] is not None else None
    indicators['last_bb_lower'] = indicators['bb_lower'][-1] if indicators['bb_lower'] and indicators['bb_lower'][-1] is not None else None
    indicators['last_atr'] = indicators['atr'][-1] if indicators['atr'] and indicators['atr'][-1] is not None else None

    # Signaux IA
    signals = []
    score = 0

    if indicators['last_rsi'] is not None:
        if indicators['last_rsi'] < 30:
            signals.append({'type': 'buy', 'indicator': 'RSI', 'value': f"{indicators['last_rsi']:.1f}", 'message': 'Zone de survente'})
            score += 15
        elif indicators['last_rsi'] > 70:
            signals.append({'type': 'sell', 'indicator': 'RSI', 'value': f"{indicators['last_rsi']:.1f}", 'message': 'Zone de surachat'})
            score -= 15

    if indicators['last_macd'] is not None and indicators['last_macd_signal'] is not None and len(indicators['macd']) > 1:
        prev_macd = indicators['macd'][-2]
        prev_signal = indicators['macd_signal'][-2]
        if prev_macd is not None and prev_signal is not None:
            if prev_macd < prev_signal and indicators['last_macd'] > indicators['last_macd_signal']:
                signals.append({'type': 'buy', 'indicator': 'MACD', 'value': f"{indicators['last_macd']:.3f}", 'message': 'Croisement haussier'})
                score += 15
            elif prev_macd > prev_signal and indicators['last_macd'] < indicators['last_macd_signal']:
                signals.append({'type': 'sell', 'indicator': 'MACD', 'value': f"{indicators['last_macd']:.3f}", 'message': 'Croisement baissier'})
                score -= 15

    if indicators['last_sma_20'] is not None and indicators['last_sma_50'] is not None:
        prev_sma20 = indicators['sma_20'][-2] if len(indicators['sma_20']) > 1 else None
        prev_sma50 = indicators['sma_50'][-2] if len(indicators['sma_50']) > 1 else None
        if prev_sma20 is not None and prev_sma50 is not None:
            if prev_sma20 < prev_sma50 and indicators['last_sma_20'] > indicators['last_sma_50']:
                signals.append({'type': 'buy', 'indicator': 'SMA', 'value': 'Golden Cross', 'message': 'Croisement haussier 20/50'})
                score += 12
            elif prev_sma20 > prev_sma50 and indicators['last_sma_20'] < indicators['last_sma_50']:
                signals.append({'type': 'sell', 'indicator': 'SMA', 'value': 'Death Cross', 'message': 'Croisement baissier 20/50'})
                score -= 12

    if indicators['last_stoch_k'] is not None and indicators['last_stoch_d'] is not None:
        if indicators['last_stoch_k'] < 20 and indicators['last_stoch_d'] < 20:
            signals.append({'type': 'buy', 'indicator': 'Stochastic', 'value': f"K:{indicators['last_stoch_k']:.1f}", 'message': 'Zone de survente'})
            score += 10
        elif indicators['last_stoch_k'] > 80 and indicators['last_stoch_d'] > 80:
            signals.append({'type': 'sell', 'indicator': 'Stochastic', 'value': f"K:{indicators['last_stoch_k']:.1f}", 'message': 'Zone de surachat'})
            score -= 10

    if indicators['last_bb_lower'] is not None and indicators['last_bb_upper'] is not None:
        if current_price <= indicators['last_bb_lower'] * 1.01:
            signals.append({'type': 'buy', 'indicator': 'Bollinger', 'value': f"${current_price:.2f}", 'message': 'Proche bande inférieure'})
            score += 8
        elif current_price >= indicators['last_bb_upper'] * 0.99:
            signals.append({'type': 'sell', 'indicator': 'Bollinger', 'value': f"${current_price:.2f}", 'message': 'Proche bande supérieure'})
            score -= 8

    if indicators['momentum'] > 5:
        signals.append({'type': 'buy', 'indicator': 'Momentum', 'value': f"{indicators['momentum']:.1f}%", 'message': 'Momentum haussier'})
        score += 8
    elif indicators['momentum'] < -5:
        signals.append({'type': 'sell', 'indicator': 'Momentum', 'value': f"{indicators['momentum']:.1f}%", 'message': 'Momentum baissier'})
        score -= 8

    if indicators['volatility'] > 50:
        signals.append({'type': 'neutral', 'indicator': 'Volatilité', 'value': f"{indicators['volatility']:.1f}%", 'message': 'Volatilité élevée'})
    elif indicators['volatility'] < 15:
        signals.append({'type': 'neutral', 'indicator': 'Volatilité', 'value': f"{indicators['volatility']:.1f}%", 'message': 'Volatilité faible'})

    if score > 20:
        recommendation = 'ACHAT'
        confidence = min(95, 50 + abs(score) * 0.8)
    elif score < -20:
        recommendation = 'VENTE'
        confidence = min(95, 50 + abs(score) * 0.8)
    else:
        recommendation = 'NEUTRE'
        confidence = 50 + (abs(score) / 2)

    confidence = min(95, max(15, confidence))

    if indicators['last_atr'] is not None and indicators['last_atr'] > 0:
        indicators['stop_loss'] = current_price - 2 * indicators['last_atr']
        indicators['take_profit'] = current_price + 2 * indicators['last_atr']
    else:
        indicators['stop_loss'] = current_price * 0.975
        indicators['take_profit'] = current_price * 1.05

    indicators['signals'] = signals
    indicators['recommendation'] = recommendation
    indicators['confidence'] = confidence
    indicators['score'] = score
    indicators['buy_signals'] = sum(1 for s in signals if s['type'] == 'buy')
    indicators['sell_signals'] = sum(1 for s in signals if s['type'] == 'sell')
    indicators['is_strong_signal'] = (score > 30 or score < -30) and confidence > 70

    try:
        if len(close) >= 30:
            x = np.arange(len(close)).reshape(-1, 1)
            y = np.array(close).reshape(-1, 1)
            model = make_pipeline(PolynomialFeatures(2), LinearRegression())
            model.fit(x, y)
            future = np.arange(len(close), len(close) + 5).reshape(-1, 1)
            predictions = model.predict(future).flatten()
            indicators['predictions'] = [float(p) for p in predictions]
        else:
            indicators['predictions'] = [current_price] * 5
    except:
        indicators['predictions'] = [current_price] * 5

    return indicators

# ============================================================
# ROUTES
# ============================================================

@app.route('/static/<path:filename>')
def static_files(filename):
    return send_from_directory('static', filename)

@app.route('/favicon.ico')
def favicon():
    return '', 204

@app.route('/api/clear-cache')
def clear_cache():
    cache.clear()
    return jsonify({'status': 'ok'})

@app.route('/api/trading/<symbol>')
def get_trading(symbol):
    try:
        cached = get_cached(f"trading_{symbol}")
        if cached:
            return jsonify(cached)

        logger.info(f"Fetching {symbol}")
        ticker = yf.Ticker(symbol)

        hist_test = ticker.history(period='1d')
        if hist_test.empty:
            return jsonify({'error': f'Symbole {symbol} non trouvé'}), 404

        periods = ['1d', '5d', '1mo', '3mo', '6mo', '1y']
        info = ASSETS.get(symbol, {})

        result = {
            'symbol': symbol,
            'name': info.get('name', symbol),
            'exchange': info.get('exchange', 'Market'),
            'currency': 'USD',
            'category': info.get('category', 'Autre'),
            'icon': info.get('icon', '📈'),
            'color': info.get('color', '#33ff33'),
            'data': {}
        }

        for period in periods:
            try:
                interval = get_interval_for_period(period)
                hist = ticker.history(period=period, interval=interval)
                if hist.empty:
                    continue

                if hist.index.tz is None:
                    hist.index = hist.index.tz_localize('UTC').tz_convert(US_TIMEZONE)
                else:
                    hist.index = hist.index.tz_convert(US_TIMEZONE)

                close = hist['Close'].values
                high = hist['High'].values
                low = hist['Low'].values

                candles = []
                for idx, row in hist.iterrows():
                    candles.append({
                        'time': int(idx.timestamp()),
                        'open': safe_float(row['Open']),
                        'high': safe_float(row['High']),
                        'low': safe_float(row['Low']),
                        'close': safe_float(row['Close']),
                        'volume': safe_int(row['Volume'])
                    })

                if not candles:
                    continue

                indicators = calculate_all_indicators(candles)

                result['data'][period] = {
                    'candles': candles,
                    'indicators': indicators,
                    'stats': {
                        'current_price': safe_float(close[-1]),
                        'change': safe_float(close[-1] - close[-2]) if len(close) > 1 else 0,
                        'change_percent': safe_float(((close[-1] - close[-2]) / close[-2] * 100)) if len(close) > 1 and close[-2] != 0 else 0,
                        'high': safe_float(max(high)),
                        'low': safe_float(min(low)),
                        'volume': safe_int(hist['Volume'].sum()),
                        'open': safe_float(close[0]) if len(close) > 0 else 0
                    }
                }

            except Exception as e:
                logger.error(f"Erreur {period} {symbol}: {e}")
                continue

        if not result['data']:
            return jsonify({'error': f'Aucune donnée pour {symbol}'}), 404

        set_cached(f"trading_{symbol}", result)
        return jsonify(result)

    except Exception as e:
        logger.error(f"Erreur {symbol}: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/insights/<symbol>')
def get_insights(symbol):
    try:
        cached = get_cached(f"insights_{symbol}")
        if cached:
            return jsonify(cached)

        ticker = yf.Ticker(symbol)
        hist = ticker.history(period='3mo')

        if hist.empty or len(hist) < 30:
            return jsonify({'error': 'Pas assez de données'}), 404

        candles = []
        for idx, row in hist.iterrows():
            candles.append({
                'time': int(idx.timestamp()),
                'open': safe_float(row['Open']),
                'high': safe_float(row['High']),
                'low': safe_float(row['Low']),
                'close': safe_float(row['Close']),
                'volume': safe_int(row['Volume'])
            })

        indicators = calculate_all_indicators(candles)
        indicators['symbol'] = symbol
        indicators['name'] = ASSETS.get(symbol, {}).get('name', symbol)
        indicators['icon'] = ASSETS.get(symbol, {}).get('icon', '📈')

        # Retourner un dict, pas un objet Response
        result = dict(indicators)

        set_cached(f"insights_{symbol}", result)
        return jsonify(result)

    except Exception as e:
        logger.error(f"Erreur insights {symbol}: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/watchlist')
def get_watchlist():
    try:
        results = []
        for symbol in WATCHLIST:
            try:
                ticker = yf.Ticker(symbol)
                info = ticker.info
                hist = ticker.history(period='1d')

                current = safe_float(info.get('regularMarketPrice', 0))
                if current == 0 and not hist.empty:
                    current = safe_float(hist['Close'].iloc[-1])

                prev = safe_float(info.get('regularMarketPreviousClose', 0))
                if prev == 0 and len(hist) > 1:
                    prev = safe_float(hist['Close'].iloc[-2])

                change_pct = ((current - prev) / prev * 100) if prev else 0

                asset_info = ASSETS.get(symbol, {})

                results.append({
                    'symbol': symbol,
                    'name': asset_info.get('name', symbol),
                    'price': current,
                    'changePercent': change_pct,
                    'change': current - prev,
                    'currency': 'USD',
                    'category': asset_info.get('category', 'Autre'),
                    'icon': asset_info.get('icon', '📈')
                })
            except:
                continue

        results.sort(key=lambda x: (x['category'], -x['changePercent']))
        return jsonify(results)

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/top-performers')
def get_top_performers():
    try:
        performers = []
        for symbol in WATCHLIST:
            try:
                ticker = yf.Ticker(symbol)
                info = ticker.info
                hist = ticker.history(period='1d')

                current = safe_float(info.get('regularMarketPrice', 0))
                if current == 0 and not hist.empty:
                    current = safe_float(hist['Close'].iloc[-1])

                prev = safe_float(info.get('regularMarketPreviousClose', 0))
                if prev == 0 and len(hist) > 1:
                    prev = safe_float(hist['Close'].iloc[-2])

                change_pct = ((current - prev) / prev * 100) if prev else 0

                asset_info = ASSETS.get(symbol, {})

                performers.append({
                    'symbol': symbol,
                    'name': asset_info.get('name', symbol),
                    'price': current,
                    'changePercent': change_pct,
                    'currency': 'USD',
                    'category': asset_info.get('category', 'Autre'),
                    'icon': asset_info.get('icon', '📈')
                })
            except:
                continue

        performers.sort(key=lambda x: x['changePercent'], reverse=True)
        return jsonify(performers[:15])

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/market-status')
def market_status():
    now = datetime.now(US_TIMEZONE)
    is_open = now.weekday() < 5 and 9 <= now.hour <= 16
    return jsonify({
        'status': 'open' if is_open else 'closed',
        'label': 'Ouvert' if is_open else 'Fermé',
        'icon': '🟢' if is_open else '🔴',
        'time': now.strftime('%H:%M:%S')
    })

@app.route('/')
def index():
    return render_template('monitor.html')

# ============================================================
# WEBSOCKET
# ============================================================

@socketio.on('connect')
def handle_connect():
    logger.info("Client connecté")
    emit('connected', {'status': 'connected', 'timestamp': datetime.now().isoformat()})

@socketio.on('request_insights')
def handle_request_insights(data):
    symbol = data.get('symbol')
    if not symbol:
        return
    try:
        # Appeler la route API directement
        with app.app_context():
            from flask import jsonify
            response = get_insights(symbol)
            if isinstance(response, tuple):
                response = response[0]
            # Extraire les données JSON
            if hasattr(response, 'get_json'):
                data = response.get_json()
            else:
                data = response
            emit('insights_update', data)
    except Exception as e:
        logger.error(f"Erreur request_insights {symbol}: {e}")
        emit('error', {'message': str(e)})

# ============================================================
# LANCEMENT
# ============================================================

if __name__ == '__main__':
    os.makedirs('templates', exist_ok=True)
    os.makedirs('static/js', exist_ok=True)
    os.makedirs('static/css', exist_ok=True)

    print("=" * 70)
    print("📊 TRADING MONITOR - Indicateurs + IA")
    print("=" * 70)
    print("🌐 http://localhost:5000")
    print("=" * 70)
    print("📈 Symboles disponibles: " + str(len(WATCHLIST)))
    print("=" * 70)

    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
