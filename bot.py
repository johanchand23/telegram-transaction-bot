# Simple polling bot - works with Background Worker
import telebot
import requests
import json
import os
import base64
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import re
import time

# Bot token from BotFather
BOT_TOKEN = os.getenv('BOT_TOKEN', 'YOUR_BOT_TOKEN_HERE')

# OCR.space API key
OCR_API_KEY = os.getenv('OCR_API_KEY', 'YOUR_OCR_API_KEY')

# Google Sheets setup
GOOGLE_SHEET_ID = os.getenv('GOOGLE_SHEET_ID', 'your_google_sheet_id')

# Initialize bot
bot = telebot.TeleBot(BOT_TOKEN)

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

def download_telegram_image(bot_token, file_path):
    try:
        download_url = f"https://api.telegram.org/file/bot{bot_token}/{file_path}"
        response = requests.get(download_url, timeout=30)
        response.raise_for_status()
        return response.content
    except Exception as e:
        print(f"Failed to download image: {e}")
        return None

def extract_text_from_telegram_image(bot_token, file_path):
    try:
        print("Starting OCR process...")
        
        image_data = download_telegram_image(bot_token, file_path)
        if not image_data:
            return None, "Failed to download image"
        
        image_base64 = base64.b64encode(image_data).decode('utf-8')
        
        # Detect file type
        if image_data.startswith(b'\x89PNG'):
            content_type = 'image/png'
        elif image_data.startswith(b'\xFF\xD8\xFF'):
            content_type = 'image/jpeg'
        else:
            content_type = 'image/jpeg'
        
        base64_data_uri = f"data:{content_type};base64,{image_base64}"
        
        payload = {
            'base64Image': base64_data_uri,
            'apikey': OCR_API_KEY,
            'language': 'eng',
            'isOverlayRequired': 'false',
            'OCREngine': '2',
            'filetype': content_type
        }
        
        response = requests.post('https://api.ocr.space/parse/image', data=payload, timeout=60)
        
        if response.status_code != 200:
            return None, f"HTTP Error: {response.status_code}"
            
        result = response.json()
        
        if result.get('IsErroredOnProcessing'):
            return None, f"OCR Error: {result.get('ErrorMessage', 'Unknown error')}"
        
        if 'ParsedResults' not in result or len(result['ParsedResults']) == 0:
            return None, "No text detected"
            
        extracted_text = result['ParsedResults'][0]['ParsedText']
        return extracted_text, None
        
    except Exception as e:
        return None, str(e)

def parse_handwritten_transactions(ocr_text):
    transactions = []
    
    # Extract date
    date_match = re.search(r'(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})', ocr_text)
    transaction_date = date_match.group(1) if date_match else datetime.now().strftime("%d-%m-%Y")
    
    lines = ocr_text.replace('\r', '\n').split('\n')
    lines = [line.strip() for line in lines if line.strip()]
    
    for line in lines:
        if not line or 'tanty' in line.lower() or len(line) < 5:
            continue
            
        # Pattern: "1pc Std ballon jw sCHOFOANI 85 86000"
        pattern = r'(\d+\s*p[cs]?)\s+([^0-9]+?)\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s*$'
        match = re.search(pattern, line, re.IGNORECASE)
        
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
    
    return transactions

def add_transactions_to_sheet(transactions):
    try:
        sheet = init_google_sheets()
        if not sheet:
            return False, "Google Sheets not connected"
            
        if not sheet.get_all_values():
            sheet.append_row(['Date', 'Quantity', 'Description', 'Unit Price', 'Total Amount', 'Currency'])
        
        for transaction in transactions:
            sheet.append_row([
                transaction['date'],
                transaction['quantity'],
                transaction['description'],
                f"{transaction['unit_price']:.0f}",
                f"{transaction['total_amount']:.0f}",
                transaction['currency']
            ])
        
        return True, f"Added {len(transactions)} transactions"
    except Exception as e:
        return False, str(e)

def format_rupiah(amount):
    return f"Rp {amount:,.0f}".replace(',', '.')

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, """
👋 Selamat datang di Transaction Bot!

📝 Kirim foto daftar transaksi tulisan tangan Anda dan bot akan:
✅ Membaca data transaksi
✅ Menambahkan ke Google Sheet
✅ Memberikan konfirmasi

Kirim foto untuk memulai!

Commands:
/help - Bantuan
/status - Cek status bot
    """)

@bot.message_handler(commands=['help'])
def send_help(message):
    help_text = """
🤖 Panduan Transaction Bot:

📷 Cara menggunakan:
1. Tulis daftar transaksi di kertas
2. Foto daftar transaksi
3. Kirim foto ke bot ini
4. Tunggu pemrosesan
5. Terima konfirmasi

💡 Tips:
• Pastikan tulisan jelas
• Format: [qty]pc/pcs [nama] [harga] [total]
• Sertakan tanggal di bagian atas

Commands:
/status - Cek status koneksi
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
🤖 Bot: ✅ Berjalan (Polling Mode)

Update: {datetime.now().strftime("%Y-%m-%d %H:%M")}
    """
    bot.reply_to(message, status_text)

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    try:
        processing_msg = bot.reply_to(message, "📝 Memproses daftar transaksi... Mohon tunggu...")
        
        photo = message.photo[-1]
        file_info = bot.get_file(photo.file_id)
        
        ocr_text, error_msg = extract_text_from_telegram_image(BOT_TOKEN, file_info.file_path)
        
        if not ocr_text:
            bot.edit_message_text(f"❌ Error: {error_msg}", message.chat.id, processing_msg.message_id)
            return
        
        transactions = parse_handwritten_transactions(ocr_text)
        
        if not transactions:
            bot.edit_message_text(f"❌ Tidak ada transaksi terdeteksi.\n\nTeks terbaca:\n{ocr_text[:200]}...", message.chat.id, processing_msg.message_id)
            return
        
        sheet_success, sheet_message = add_transactions_to_sheet(transactions)
        grand_total = sum(t['total_amount'] for t in transactions)
        
        response = f"✅ Berhasil memproses {len(transactions)} transaksi!\n\n"
        
        for i, t in enumerate(transactions[:3]):
            response += f"• {t['quantity']} {t['description']} - {format_rupiah(t['total_amount'])}\n"
        
        if len(transactions) > 3:
            response += f"... dan {len(transactions) - 3} item lainnya\n"
        
        response += f"\n💰 Total: {format_rupiah(grand_total)}\n"
        response += f"📅 Tanggal: {transactions[0]['date']}\n\n"
        
        if sheet_success:
            response += f"✅ {sheet_message} ke Google Sheet!"
        else:
            response += f"⚠️ Google Sheets belum terhubung"
        
        bot.edit_message_text(response, message.chat.id, processing_msg.message_id)
        
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {str(e)}")

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    bot.reply_to(message, "📝 Kirim foto daftar transaksi untuk diproses!")

if __name__ == '__main__':
    print("🤖 Transaction Bot starting...")
    print("🔍 Debug: Checking environment variables...")
    
    # Debug environment variables
    print(f"🔑 OCR API Key: {'✅ Set (' + str(len(OCR_API_KEY)) + ' chars)' if OCR_API_KEY != 'YOUR_OCR_API_KEY' else '❌ NOT SET!'}")
    print(f"🤖 Bot Token: {'✅ Set (' + str(len(BOT_TOKEN)) + ' chars)' if BOT_TOKEN != 'YOUR_BOT_TOKEN_HERE' else '❌ NOT SET!'}")
    print(f"📊 Sheet ID: {'✅ Set (' + str(len(GOOGLE_SHEET_ID)) + ' chars)' if GOOGLE_SHEET_ID != 'your_google_sheet_id' else '❌ NOT SET!'}")
    
    # Test Google Sheets connection
    try:
        print("🔍 Testing Google Sheets connection...")
        sheet_test = init_google_sheets()
        if sheet_test:
            print("✅ Google Sheets: Connected successfully!")
        else:
            print("❌ Google Sheets: Connection failed")
    except Exception as e:
        print(f"❌ Google Sheets error: {e}")
    
    # Force clear webhook and ensure single instance
    try:
        print("🧹 Clearing webhook...")
        bot.remove_webhook()
        print("✅ Webhook cleared")
        time.sleep(2)  # Wait for clear
    except Exception as e:
        print(f"⚠️ Webhook clear warning: {e}")
    
    print("✅ Bot starting polling mode...")
    
    # Start polling with more robust error handling
    while True:
        try:
            print("🔄 Starting polling...")
            bot.polling(none_stop=True, interval=2, timeout=30, restart_on_change=True)
        except Exception as e:
            print(f"⚠️ Polling error: {e}")
            print("🔄 Restarting in 10 seconds...")
            time.sleep(10)  # Wait longer before retrying
