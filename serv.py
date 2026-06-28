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
CORS(app, resources={r"/*": {"origins": "*"}})
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading', ping_timeout=60, ping_interval=25)

US_TIMEZONE = pytz.timezone('America/New_York')
cache = {}
CACHE_DURATION = 30

# ============================================================
# SYMBOLES DE REMPLACEMENT POUR YFINANCE
# ============================================================
FALLBACK_SYMBOLS = {
    'GC=F': 'GLD',
    'SI=F': 'SLV',
    'CL=F': 'USO',
    'BZ=F': 'BNO',
    'NG=F': 'UNG',
    'ZC=F': 'CORN',
    'ZW=F': 'WEAT',
    'ZS=F': 'SOYB',
    'KC=F': 'JO',
    'CC=F': 'NIB',
    'HG=F': 'CPER',
    '^GSPC': 'SPY',
    '^FCHI': 'EWQ',
    '^IXIC': 'QQQ',
    '^DJI': 'DIA',
}

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

def get_effective_symbol(symbol):
    """Retourne le symbole à utiliser pour yfinance"""
    return FALLBACK_SYMBOLS.get(symbol, symbol)

# ============================================================
# DONNÉES PAR CATÉGORIE
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

    # Paris
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

# ... (le reste du code pour calculate_sma, calculate_ema, etc. reste inchangé) ...

# ============================================================
# ROUTES CORRIGÉES
# ============================================================

@app.route('/api/trading/<symbol>')
def get_trading(symbol):
    try:
        cached = get_cached(f"trading_{symbol}")
        if cached:
            return jsonify(cached)

        logger.info(f"Fetching {symbol}")
        
        # Utiliser le symbole effectif pour yfinance
        effective_symbol = get_effective_symbol(symbol)
        
        try:
            ticker = yf.Ticker(effective_symbol)
            hist_test = ticker.history(period='1d')
            if hist_test.empty:
                # Essayer avec le symbole original si le fallback échoue
                ticker = yf.Ticker(symbol)
                hist_test = ticker.history(period='1d')
                if hist_test.empty:
                    return jsonify({'error': f'Symbole {symbol} non trouvé'}), 404
        except Exception as e:
            logger.error(f"Erreur fetching {symbol}: {e}")
            return jsonify({'error': str(e)}), 500

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
            'data': {},
            'is_fallback': effective_symbol != symbol
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

@app.route('/api/watchlist')
def get_watchlist():
    try:
        results = []
        for symbol in WATCHLIST:
            try:
                effective_symbol = get_effective_symbol(symbol)
                ticker = yf.Ticker(effective_symbol)
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
            except Exception as e:
                logger.warning(f"Erreur watchlist {symbol}: {e}")
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
                effective_symbol = get_effective_symbol(symbol)
                ticker = yf.Ticker(effective_symbol)
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

# ============================================================
# WEBSOCKET - AVEC MEILLEURE GESTION D'ERREURS
# ============================================================

@socketio.on('connect')
def handle_connect():
    logger.info("Client connecté")
    emit('connected', {'status': 'connected', 'timestamp': datetime.now().isoformat()})

@socketio.on('request_insights')
def handle_request_insights(data):
    symbol = data.get('symbol')
    if not symbol:
        emit('error', {'message': 'Symbole manquant'})
        return
    
    try:
        # Récupérer les insights
        with app.app_context():
            response = get_insights(symbol)
            if isinstance(response, tuple):
                response = response[0]
            
            # Extraire les données JSON
            if hasattr(response, 'get_json'):
                data_response = response.get_json()
            else:
                data_response = response
            
            # Vérifier les erreurs
            if data_response and isinstance(data_response, dict) and data_response.get('error'):
                emit('error', data_response)
            else:
                emit('insights_update', data_response)
                
    except Exception as e:
        logger.error(f"Erreur request_insights {symbol}: {e}")
        emit('error', {'message': str(e), 'symbol': symbol})

@socketio.on('disconnect')
def handle_disconnect():
    logger.info("Client déconnecté")

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
    print("🔄 Fallback activé pour les symboles problématiques")

    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
