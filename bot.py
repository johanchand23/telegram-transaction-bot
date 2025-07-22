# Improved bot with better error handling and debugging
import telebot
import requests
import json
import os
from io import BytesIO
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import re

# Bot token from BotFather
BOT_TOKEN = os.getenv('BOT_TOKEN', 'YOUR_BOT_TOKEN_HERE')

# OCR.space API key (free - get from ocr.space)
OCR_API_KEY = os.getenv('OCR_API_KEY', 'YOUR_OCR_API_KEY')

# Google Sheets setup
GOOGLE_SHEET_ID = os.getenv('GOOGLE_SHEET_ID', 'your_google_sheet_id')

bot = telebot.TeleBot(BOT_TOKEN)

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

# Enhanced OCR function with better error handling
def extract_text_from_image(image_url):
    try:
        print(f"🔍 Attempting OCR on: {image_url}")
        print(f"🔑 Using API Key: {OCR_API_KEY[:8]}...")
        
        payload = {
            'url': image_url,
            'apikey': OCR_API_KEY,
            'language': 'eng',
            'isOverlayRequired': False,
            'detectOrientation': 'true',
            'scale': 'true',
            'OCREngine': '2'  # Use engine 2 for better accuracy
        }
        
        response = requests.post('https://api.ocr.space/parse/image', data=payload, timeout=60)
        print(f"📡 OCR API Response Status: {response.status_code}")
        
        if response.status_code != 200:
            print(f"❌ HTTP Error: {response.status_code}")
            return None, f"HTTP Error: {response.status_code}"
            
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
        
    except requests.exceptions.Timeout:
        error_msg = "OCR request timed out"
        print(f"⏰ {error_msg}")
        return None, error_msg
    except requests.exceptions.RequestException as e:
        error_msg = f"Network error: {str(e)}"
        print(f"🌐 {error_msg}")
        return None, error_msg
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
    
    # Look for transaction pattern: quantity + description + price + total
    for i, line in enumerate(lines):
        line = line.strip()
        print(f"Line {i+1}: '{line}'")
        
        # Skip header lines, empty lines, or lines with just "TANTY"
        if not line or 'tanty' in line.lower() or len(line) < 5:
            print(f"  ⏭️ Skipping header/empty line")
            continue
            
        # Pattern for transaction lines: "1pc Std ballon jw sCHOFOANI 85 86000"
        # More flexible regex to catch various formats
        transaction_pattern = r'(\d+\s*p[cs]?)\s+([^0-9]+?)\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s*$'
        
        match = re.search(transaction_pattern, line, re.IGNORECASE)
        
        if match:
            quantity = match.group(1).strip()
            description = match.group(2).strip()
            unit_price = float(match.group(3))
            total_amount = float(match.group(4))
            
            transaction = {
                'date': transaction_date,
                'quantity': quantity,
                'description': description,
                'unit_price': unit_price,
                'total_amount': total_amount,
                'currency': 'Rp'
            }
            transactions.append(transaction)
            print(f"  ✅ Found transaction: {quantity} {description} - Rp {total_amount}")
        else:
            # Try alternative pattern for lines that might be split differently
            qty_pattern = r'^(\d+\s*p[cs]?)\s+(.+)'
            qty_match = re.search(qty_pattern, line, re.IGNORECASE)
            
            if qty_match:
                # Look for numbers in this line
                numbers = re.findall(r'\d+(?:\.\d+)?', line)
                if len(numbers) >= 2:
                    quantity = qty_match.group(1).strip()
                    description = qty_match.group(2).strip()
                    
                    # Remove numbers from description
                    description = re.sub(r'\d+(?:\.\d+)?', '', description).strip()
                    
                    # Last two numbers are likely unit price and total
                    unit_price = float(numbers[-2]) if len(numbers) >= 2 else 0
                    total_amount = float(numbers[-1]) if numbers else 0
                    
                    if unit_price > 0 and total_amount > 0:
                        transaction = {
                            'date': transaction_date,
                            'quantity': quantity,
                            'description': description,
                            'unit_price': unit_price,
                            'total_amount': total_amount,
                            'currency': 'Rp'
                        }
                        transactions.append(transaction)
                        print(f"  ✅ Found transaction (alt): {quantity} {description} - Rp {total_amount}")
                    else:
                        print(f"  ❌ Invalid prices: {unit_price}, {total_amount}")
                else:
                    print(f"  ❌ Not enough numbers found: {numbers}")
            else:
                print(f"  ❌ No quantity pattern found")
    
    print(f"🎯 Total transactions found: {len(transactions)}")
    return transactions

# Add transactions to Google Sheets
def add_transactions_to_sheet(transactions):
    try:
        sheet = init_google_sheets()
        if not sheet:
            return False, "Google Sheets not connected"
            
        # Add headers if sheet is empty
        if not sheet.get_all_values():
            sheet.append_row(['Date', 'Quantity', 'Description', 'Unit Price', 'Total Amount', 'Currency'])
        
        # Add each transaction
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
        print(f"Sheet update error: {e}")
        return False, str(e)

# Format currency for Indonesian Rupiah
def format_rupiah(amount):
    return f"Rp {amount:,.0f}".replace(',', '.')

# Bot command handlers
@bot.message_handler(commands=['start'])
def send_welcome(message):
    welcome_text = """
👋 Selamat datang di Transaction Bot!

📝 Kirim foto daftar transaksi tulisan tangan Anda dan bot akan:
✅ Membaca data transaksi
✅ Menambahkan ke Google Sheet
✅ Memberikan konfirmasi

Format yang didukung:
• 1pc Nama Produk 85 86000
• 2pcs Item Description 100 200000

Kirim foto untuk memulai!

Commands:
/help - Bantuan
/status - Status bot
/debug - Test OCR API
    """
    bot.reply_to(message, welcome_text)

@bot.message_handler(commands=['debug'])
def debug_ocr(message):
    debug_info = f"""
🔧 Debug Info:
📡 OCR API Key: {'✅ Set' if OCR_API_KEY != 'YOUR_OCR_API_KEY' else '❌ Not set'}
🤖 Bot Token: {'✅ Set' if BOT_TOKEN != 'YOUR_BOT_TOKEN_HERE' else '❌ Not set'}
📊 Sheet ID: {'✅ Set' if GOOGLE_SHEET_ID != 'your_google_sheet_id' else '❌ Not set'}

Send me a test image to see detailed OCR debug info!
    """
    bot.reply_to(message, debug_info)

@bot.message_handler(commands=['help'])
def send_help(message):
    help_text = """
🤖 Panduan Transaction Bot:

📷 Cara menggunakan:
1. Tulis daftar transaksi di kertas dengan format:
   [Jumlah] [Nama Item] [Harga Satuan] [Total]
   
   Contoh:
   1pc Std ballon JW 85 86000
   2pcs Std Ayana 85 170000

2. Foto daftar transaksi
3. Kirim foto ke bot ini
4. Tunggu pemrosesan (30-60 detik)
5. Terima konfirmasi dengan data yang diekstrak

💡 Tips:
• Pastikan tulisan jelas dan mudah dibaca
• Gunakan format: [qty]pc/pcs [nama] [harga] [total]
• Sertakan tanggal di bagian atas
• Coba /debug untuk informasi teknis

❓ Ada masalah? Pastikan tulisan terbaca dengan jelas!
    """
    bot.reply_to(message, help_text)

@bot.message_handler(commands=['status'])
def send_status(message):
    sheet_status = "✅ Terhubung" if init_google_sheets() else "❌ Tidak terhubung"
    ocr_status = "✅ Siap" if OCR_API_KEY != 'YOUR_OCR_API_KEY' else "❌ Belum dikonfigurasi"
    
    status_text = f"""
🔍 Status Bot:
📊 Google Sheets: {sheet_status}
👁️ OCR Service: {ocr_status}
🤖 Bot: ✅ Berjalan

Update terakhir: {datetime.now().strftime("%Y-%m-%d %H:%M")}
    """
    bot.reply_to(message, status_text)

# Handle photo messages with enhanced debugging
@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    try:
        # Send processing message
        processing_msg = bot.reply_to(message, "📝 Memproses daftar transaksi... Mohon tunggu 30-60 detik.")
        
        # Get the largest photo size
        photo = message.photo[-1]
        
        # Get file info
        file_info = bot.get_file(photo.file_id)
        
        # Download photo
        photo_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_info.file_path}"
        print(f"📸 Processing photo: {photo_url}")
        
        # Extract text using OCR with error details
        ocr_text, error_msg = extract_text_from_image(photo_url)
        
        if not ocr_text:
            error_response = f"❌ Maaf, tidak bisa membaca tulisan.\n\n🔍 Detail error: {error_msg}\n\n💡 Tips:\n• Pastikan foto jelas dan terang\n• Tulisan tidak terlalu kecil\n• Tidak ada bayangan pada kertas\n• Coba ambil foto lagi"
            bot.edit_message_text(error_response, message.chat.id, processing_msg.message_id)
            return
        
        # Parse handwritten transactions
        transactions = parse_handwritten_transactions(ocr_text)
        
        if not transactions:
            debug_response = f"❌ Tidak ada transaksi yang terdeteksi.\n\n📝 Teks yang terbaca:\n{ocr_text[:500]}...\n\n💡 Pastikan format sesuai:\n1pc Nama Item 85 86000"
            bot.edit_message_text(debug_response, message.chat.id, processing_msg.message_id)
            return
        
        # Add to Google Sheets
        sheet_success, sheet_message = add_transactions_to_sheet(transactions)
        
        # Calculate total
        grand_total = sum(t['total_amount'] for t in transactions)
        
        # Format response message
        response = f"✅ Berhasil memproses {len(transactions)} transaksi!\n\n"
        
        # Add transaction summary (max 5 items)
        response += "📋 **Ringkasan Transaksi:**\n"
        for i, t in enumerate(transactions[:5]):
            response += f"• {t['quantity']} {t['description']} - {format_rupiah(t['total_amount'])}\n"
        
        if len(transactions) > 5:
            response += f"... dan {len(transactions) - 5} item lainnya\n"
        
        response += f"\n💰 **Total Keseluruhan: {format_rupiah(grand_total)}**\n"
        response += f"📅 **Tanggal: {transactions[0]['date']}**\n\n"
        
        if sheet_success:
            response += f"✅ **{sheet_message} ke Google Sheet!**"
        else:
            response += f"⚠️ **Data diproses tapi Google Sheets belum terhubung**\n{sheet_message}"
        
        # Edit the processing message with results
        bot.edit_message_text(response, message.chat.id, processing_msg.message_id, parse_mode='Markdown')
        
    except Exception as e:
        error_msg = f"❌ Error memproses transaksi: {str(e)}"
        print(error_msg)
        bot.reply_to(message, error_msg)

# Handle other messages
@bot.message_handler(func=lambda message: True)
def handle_message(message):
    bot.reply_to(message, "📝 Silakan kirim foto daftar transaksi tulisan tangan untuk diproses!\n\nGunakan /help untuk panduan lengkap atau /debug untuk info teknis.")

if __name__ == '__main__':
    print("🤖 Transaction Bot starting...")
    print(f"🔑 OCR API Key: {'✅ Set' if OCR_API_KEY != 'YOUR_OCR_API_KEY' else '❌ NOT SET!'}")
    print(f"🤖 Bot Token: {'✅ Set' if BOT_TOKEN != 'YOUR_BOT_TOKEN_HERE' else '❌ NOT SET!'}")
    
    # For Render web service compatibility
    import threading
    from flask import Flask
    
    # Create a simple web server to satisfy Render's port requirement
    app = Flask(__name__)
    
    @app.route('/')
    def health_check():
        return "Bot is running!"
    
    @app.route('/health')
    def health():
        return {"status": "healthy", "bot": "running"}
    
    # Start Flask in a separate thread
    def run_flask():
        port = int(os.environ.get("PORT", 8080))
        app.run(host='0.0.0.0', port=port, debug=False)
    
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    print("✅ Bot berjalan dan menunggu pesan!")
    print(f"🌐 Web server running on port {os.environ.get('PORT', 8080)}")
    bot.polling(none_stop=True)
