# Binance Spot Testnet GUI

A Flask-based web application for trading on the Binance Spot Testnet.

API keys can be created here: https://testnet.binance.vision/

## Features

- **Portfolio Dashboard**: View cash balance and total portfolio value
- **Asset Management**: See all your holdings with real-time USDT values
- **Trading**: Buy and sell with market or limit orders
- **Order Management**: View and cancel open orders
- **Order History**: Track past trades
- **Portfolio Reset**: One-click reset to sell all assets

## Setup

1. Create a virtual environment:
   ```bash
   python -m venv .venv
   ```

2. Activate and install dependencies:
   ```bash
   .venv\Scripts\activate   # Windows
   pip install -r requirements.txt
   ```

3. Create a `resources/secrets.json` file with the following structure:
   ```json
   {
       "api_key_binance_spot_testnet": "your_api_key_here",
       "secret_key_binance_spot_testnet": "your_secret_key_here"
   }
   ```

4. Run the application:
   ```bash
   python app.py
   ```
   Or use `run.bat` on Windows.

5. Open http://localhost:5000 in your browser.

## Project Structure

```
├── app.py                 # Main Flask application
├── templates/             # HTML templates
│   ├── base.html
│   ├── index.html
│   └── error.html
├── static/                # Static assets
│   ├── css/style.css
│   └── js/app.js
├── libs/
│   └── exchange/          # Binance API client
│       └── client.py
└── resources/
    └── secrets.json       # API credentials (not in repo)
```

