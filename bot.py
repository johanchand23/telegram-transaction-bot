# Webhook-based bot to avoid 409 conflicts
import telebot
import requests
import json
import os
import base64
from io import BytesIO
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import re
from flask import Flask, request

# Bot token from BotFather
BOT_TOKEN = os.getenv('BOT_TOKEN', 'YOUR_BOT_TOKEN_HERE')

# OCR.space API key (free - get from ocr.space)
OCR_API_KEY = os.getenv('OCR_API_KEY', 'YOUR_OCR_API_KEY')

# Google Sheets setup
GOOGLE_SHEET_ID = os.getenv('GOOGLE_SHEET_ID', 'your_google_sheet_id')

# Get webhook URL from environment (Render provides this automatically)
WEBHOOK_URL = os.getenv('RENDER_EXTERNAL_URL', 'https://your-app.onrender.com')

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

# Initialize Google Sheets client
def init_google_sheets():
    try:
        creds_json = os.getenv('GOOGLE_CREDENTIALS_JSON')
        if creds_json:
            credentials = Credentials.from_service_account_info(
                json.loads(creds_json),
                scopes=['https://spreadsheets.google.com/feeds',
                       'https://www.googleapis.com/auth/drive']
            )
            gc = gspread.authorize(credentials)
            return gc.open_by_key(GOOGLE_SHEET_ID).sheet1
        return None
    except Exception as e:
        print(f"Google Sheets connection error: {e}")
        return None

# Download image from Telegram
def download_telegram_image(bot_token, file_path):
    try:
        download_url = f"https://api.telegram.org/file/bot{bot_token}/{file_path}"
        print(f"📥 Downloading image from: {download_url}")
        
        response = requests.get(download_url, timeout=30)
        response.raise_for_status()
        
        print(f"✅ Image downloaded, size: {len(response.content)} bytes")
        return response.content
    except Exception as e:
        print(f"❌ Failed to download image: {e}")
        return None

# Enhanced OCR function with image download
def extract_text_from_telegram_image(bot_token, file_path):
    try:
        print(f"🔍 Starting OCR process...")
        print(f"🔑 Using API Key: {OCR_API_KEY[:8]}...")
        
        # Download image from Telegram
        image_data = download_telegram_image(bot_token, file_path)
        if not image_data:
            return None, "Failed to download image from Telegram"
        
        # Convert image to base64
        image_base64 = base64.b64encode(image_data).decode('utf-8')
        
        # Detect file type from image content
        if image_data.startswith(b'\x89PNG'):
            content_type = 'image/png'
        elif image_data.startswith(b'\xFF\xD8\xFF'):
            content_type = 'image/jpeg'
        elif image_data.startswith(b'GIF8'):
            content_type = 'image/gif'
        else:
            content_type = 'image/jpeg'  # Default for Telegram photos
        
        # Create base64 data URI with proper content type
        base64_data_uri = f"data:{content_type};base64,{image_base64}"
        
        print(f"📄 Image converted to base64, type: {content_type}")
        
        # OCR.space API request with base64 image and explicit file type
        payload = {
            'base64Image': base64_data_uri,
            'apikey': OCR_API_KEY,
            'language': 'eng',
            'isOverlayRequired': 'false',
            'detectOrientation': 'true',
            'scale': 'true',
            'OCREngine': '2',
            'filetype': content_type
        }
        
        print("📡 Sending OCR request...")
        response = requests.post('https://api.ocr.space/parse/image', data=payload, timeout=90)
        print(f"📡 OCR API Response Status: {response.status_code}")
        
        if response.status_code != 200:
            error_msg = f"HTTP Error: {response.status_code} - {response.text}"
            print(f"❌ {error_msg}")
            return None, error_msg
            
        result = response.json()
        print(f"📄 OCR API Response: {json.dumps(result, indent=2)}")
        
        if result.get('IsErroredOnProcessing'):
            error_msg = result.get('ErrorMessage', 'Unknown OCR error')
            print(f"❌ OCR Processing Error: {error_msg}")
            return None, f"OCR Error: {error_msg}"
        
        if 'ParsedResults' not in result or len(result['ParsedResults']) == 0:
            print("❌ No ParsedResults found")
            return None, "No text detected in image"
            
        extracted_text = result['ParsedResults'][0]['ParsedText']
        print(f"✅ OCR Success! Extracted text length: {len(extracted_text)}")
        print(f"📝 Extracted text preview: {extracted_text[:200]}...")
        
        return extracted_text, None
        
    except Exception as e:
        error_msg = f"Unexpected error: {str(e)}"
        print(f"💥 {error_msg}")
        return None, error_msg

# Parse handwritten transaction list (Indonesian format)
def parse_handwritten_transactions(ocr_text):
    print(f"🔍 Parsing text: {ocr_text[:300]}...")
    transactions = []
    
    # Extract date from header (like "Senin 14-7-2025")
    date_match = re.search(r'(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})', ocr_text)
    transaction_date = date_match.group(1) if date_match else datetime.now().strftime("%d-%m-%Y")
    print(f"📅 Found date: {transaction_date}")
    
    # Clean and split text into lines
    lines = ocr_text.replace('\r', '\n').split('\n')
    lines = [line.strip() for line in lines if line.strip()]
    print(f"📄 Processing {len(lines)} lines")
    
    # Look for transaction pattern
    for i, line in enumerate(lines):
        line = line.strip()
        print(f"Line {i+1}: '{line}'")
        
        if not line or 'tanty' in line.lower() or len(line) < 5:
            continue
            
        # Pattern for transaction lines: "1pc Std ballon jw sCHOFOANI 85 86000"
        transaction_pattern = r'(\d+\s*p[cs]?)\s+([^0-9]+?)\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s*$'
        
        match = re.search(transaction_pattern, line, re.IGNORECASE)
        
        if match:
            quantity = match.group(1).strip()
            description = match.group(2).strip()
            unit_price = float(match.group(3))
            total_amount = float(match.group(4))
            
            transactions.append({
                'date': transaction_date,
                'quantity': quantity,
                'description': description,
                'unit_price': unit_price,
                'total_amount': total_amount,
                'currency': 'Rp'
            })
            print(f"  ✅ Found transaction: {quantity} {description} - Rp {total_amount}")
    
    print(f"🎯 Total transactions found: {len(transactions)}")
    return transactions

# Add transactions to Google Sheets
def add_transactions_to_sheet(transactions):
    try:
        sheet = init_google_sheets()
        if not sheet:
            return False, "Google Sheets not connected"
            
        if not sheet.get_all_values():
            sheet.append_row(['Date', 'Quantity', 'Description', 'Unit Price', 'Total Amount', 'Currency'])
        
        rows_added = 0
        for transaction in transactions:
            sheet.append_row([
                transaction['date'],
                transaction['quantity'],
                transaction['description'],
                f"{transaction['unit_price']:.0f}",
                f"{transaction['total_amount']:.0f}",
                transaction['currency']
            ])
            rows_added += 1
        
        return True, f"Added {rows_added} transactions"
    except Exception as e:
        return False, str(e)

# Format currency
def format_rupiah(amount):
    return f"Rp {amount:,.0f}".replace(',', '.')

# Bot message handlers
@bot.message_handler(commands=['start'])
def send_welcome(message):
    welcome_text = """
👋 Selamat datang di Transaction Bot!

📝 Kirim foto daftar transaksi tulisan tangan Anda dan bot akan:
✅ Membaca data transaksi
✅ Menambahkan ke Google Sheet
✅ Memberikan konfirmasi

Kirim foto untuk memulai!

Commands:
/help - Bantuan
/status - Status bot
    """
    bot.reply_to(message, welcome_text)

@bot.message_handler(commands=['status'])
def send_status(message):
    sheet_status = "✅ Terhubung" if init_google_sheets() else "❌ Tidak terhubung"
    ocr_status = "✅ Siap" if OCR_API_KEY != 'YOUR_OCR_API_KEY' else "❌ Belum dikonfigurasi"
    
    status_text = f"""
🔍 Status Bot:
📊 Google Sheets: {sheet_status}
👁️ OCR Service: {ocr_status}
🤖 Bot: ✅ Berjalan (Webhook Mode)
🔑 API Key: {OCR_API_KEY[:8]}...

Update terakhir: {datetime.now().strftime("%Y-%m-%d %H:%M")}
    """
    bot.reply_to(message, status_text)

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    try:
        processing_msg = bot.reply_to(message, "📝 Memproses daftar transaksi... Mohon tunggu 30-90 detik.")
        
        photo = message.photo[-1]
        file_info = bot.get_file(photo.file_id)
        
        print(f"📸 Processing photo: {file_info.file_path}")
        
        ocr_text, error_msg = extract_text_from_telegram_image(BOT_TOKEN, file_info.file_path)
        
        if not ocr_text:
            error_response = f"❌ Maaf, tidak bisa membaca tulisan.\n\n🔍 Detail error: {error_msg}\n\n💡 Coba foto yang lebih jelas"
            bot.edit_message_text(error_response, message.chat.id, processing_msg.message_id)
            return
        
        transactions = parse_handwritten_transactions(ocr_text)
        
        if not transactions:
            debug_response = f"❌ Tidak ada transaksi terdeteksi.\n\n📝 Teks terbaca:\n{ocr_text[:300]}..."
            bot.edit_message_text(debug_response, message.chat.id, processing_msg.message_id)
            return
        
        sheet_success, sheet_message = add_transactions_to_sheet(transactions)
        grand_total = sum(t['total_amount'] for t in transactions)
        
        response = f"✅ Berhasil memproses {len(transactions)} transaksi!\n\n"
        response += "📋 **Ringkasan:**\n"
        
        for i, t in enumerate(transactions[:3]):
            response += f"• {t['quantity']} {t['description']} - {format_rupiah(t['total_amount'])}\n"
        
        if len(transactions) > 3:
            response += f"... dan {len(transactions) - 3} item lainnya\n"
        
        response += f"\n💰 **Total: {format_rupiah(grand_total)}**\n"
        response += f"📅 **Tanggal: {transactions[0]['date']}**\n\n"
        
        if sheet_success:
            response += f"✅ **{sheet_message} ke Google Sheet!**"
        else:
            response += f"⚠️ **Google Sheets belum terhubung**"
        
        bot.edit_message_text(response, message.chat.id, processing_msg.message_id, parse_mode='Markdown')
        
    except Exception as e:
        error_msg = f"❌ Error: {str(e)}"
        print(error_msg)
        bot.reply_to(message, error_msg)

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    bot.reply_to(message, "📝 Kirim foto daftar transaksi untuk diproses!\n\nGunakan /help untuk panduan.")

# Flask webhook endpoint
@app.route('/')
def index():
    return "🤖 Transaction Bot is running!"

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        json_str = request.get_data().decode('UTF-8')
        update = telebot.types.Update.de_json(json_str)
        bot.process_new_updates([update])
        return "OK", 200
    except Exception as e:
        print(f"Webhook error: {e}")
        return "Error", 500

if __name__ == '__main__':
    print("🤖 Setting up webhook...")
    
    # Set webhook
    webhook_url = f"{WEBHOOK_URL}/webhook"
    webhook_info = bot.get_webhook_info()
    
    if webhook_info.url != webhook_url:
        print(f"🔗 Setting webhook to: {webhook_url}")
        bot.remove_webhook()
        success = bot.set_webhook(url=webhook_url)
        print(f"✅ Webhook set: {success}")
    else:
        print("✅ Webhook already configured")
    
    print(f"🔑 OCR API Key: {'✅ Set' if OCR_API_KEY != 'YOUR_OCR_API_KEY' else '❌ NOT SET!'}")
    print("✅ Bot running in webhook mode!")
    
    # Run Flask app
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)
