# Fixed bot that downloads Telegram images before OCR
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
        
        # Determine image format from file extension or content
        file_extension = file_path.lower().split('.')[-1] if '.' in file_path else 'jpg'
        if file_extension == 'jpg':
            file_extension = 'jpeg'
        
        # Detect file type from image content if extension detection fails
        if image_data.startswith(b'\x89PNG'):
            file_extension = 'png'
            content_type = 'image/png'
        elif image_data.startswith(b'\xFF\xD8\xFF'):
            file_extension = 'jpeg'  
            content_type = 'image/jpeg'
        elif image_data.startswith(b'GIF8'):
            file_extension = 'gif'
            content_type = 'image/gif'
        else:
            # Default to JPEG for Telegram photos
            file_extension = 'jpeg'
            content_type = 'image/jpeg'
        
        # Create base64 data URI with proper content type
        base64_data_uri = f"data:{content_type};base64,{image_base64}"
        
        print(f"📄 Image converted to base64, length: {len(base64_data_uri)}")
        
        # OCR.space API request with base64 image and explicit file type
        payload = {
            'base64Image': base64_data_uri,
            'apikey': OCR_API_KEY,
            'language': 'eng',
            'isOverlayRequired': 'false',
            'detectOrientation': 'true',
            'scale': 'true',
            'OCREngine': '2',  # Use engine 2 for better accuracy
            'filetype': content_type  # Explicitly specify file type
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
        
    except requests.exceptions.Timeout:
        error_msg = "OCR request timed out (90 seconds)"
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
/test - Test OCR dengan gambar sampel
    """
    bot.reply_to(message, welcome_text)

@bot.message_handler(commands=['test'])
def test_ocr_api(message):
    test_msg = bot.reply_to(message, "🧪 Testing OCR API dengan gambar sampel...")
    
    try:
        # Test with a simple online image
        test_image_url = "https://dl.a9t9.com/ocr/solarcell.jpg"
        
        payload = {
            'url': test_image_url,
            'apikey': OCR_API_KEY,
            'language': 'eng',
            'isOverlayRequired': 'false'
        }
        
        response = requests.post('https://api.ocr.space/parse/image', data=payload, timeout=30)
        result = response.json()
        
        if result.get('IsErroredOnProcessing'):
            error_msg = result.get('ErrorMessage', 'Unknown error')
            bot.edit_message_text(f"❌ OCR Test Failed: {error_msg}", message.chat.id, test_msg.message_id)
        elif result.get('ParsedResults') and len(result['ParsedResults']) > 0:
            extracted_text = result['ParsedResults'][0]['ParsedText'][:100]
            bot.edit_message_text(f"✅ OCR Test Success!\n\nSample text: {extracted_text}...", message.chat.id, test_msg.message_id)
        else:
            bot.edit_message_text("❌ OCR Test: No text extracted", message.chat.id, test_msg.message_id)
            
    except Exception as e:
        bot.edit_message_text(f"❌ OCR Test Error: {str(e)}", message.chat.id, test_msg.message_id)

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
4. Tunggu pemrosesan (30-90 detik)
5. Terima konfirmasi dengan data yang diekstrak

💡 Tips:
• Pastikan tulisan jelas dan mudah dibaca
• Gunakan format: [qty]pc/pcs [nama] [harga] [total]
• Sertakan tanggal di bagian atas
• Coba /test untuk test API
• Coba /status untuk status bot

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
🔑 API Key: {OCR_API_KEY[:8]}...

Update terakhir: {datetime.now().strftime("%Y-%m-%d %H:%M")}

💡 Gunakan /test untuk test OCR API
    """
    bot.reply_to(message, status_text)

# Handle photo messages with enhanced debugging
@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    try:
        # Send processing message
        processing_msg = bot.reply_to(message, "📝 Memproses daftar transaksi... Mohon tunggu 30-90 detik.")
        
        # Get the largest photo size
        photo = message.photo[-1]
        
        # Get file info
        file_info = bot.get_file(photo.file_id)
        
        print(f"📸 Processing photo: {file_info.file_path}")
        
        # Extract text using OCR with image download
        ocr_text, error_msg = extract_text_from_telegram_image(BOT_TOKEN, file_info.file_path)
        
        if not ocr_text:
            error_response = f"❌ Maaf, tidak bisa membaca tulisan.\n\n🔍 Detail error: {error_msg}\n\n💡 Tips:\n• Pastikan foto jelas dan terang\n• Tulisan tidak terlalu kecil\n• Tidak ada bayangan pada kertas\n• Coba /test untuk test API\n• Coba ambil foto lagi"
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
    bot.reply_to(message, "📝 Silakan kirim foto daftar transaksi tulisan tangan untuk diproses!\n\nGunakan /help untuk panduan lengkap atau /test untuk test OCR API.")

if __name__ == '__main__':
    print("🤖 Transaction Bot starting...")
    print(f"🔑 OCR API Key: {'✅ Set' if OCR_API_KEY != 'YOUR_OCR_API_KEY' else '❌ NOT SET!'}")
    print(f"🤖 Bot Token: {'✅ Set' if BOT_TOKEN != 'YOUR_BOT_TOKEN_HERE' else '❌ NOT SET!'}")
    print("✅ Bot berjalan dan menunggu pesan!")
    bot.polling(none_stop=True)
