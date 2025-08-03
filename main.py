import os
import asyncio
import logging
from io import BytesIO
from typing import Any, Dict
from config import TOKEN

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.utils.markdown import hbold

# For background removal
from rembg import remove, new_session
from PIL import Image
import gc  # For garbage collection
import threading
import time

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Get token from environment variable (IMPORTANT for hosting)
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    logger.error("❌ BOT_TOKEN environment variable not set!")
    logger.error("Please set BOT_TOKEN in your hosting platform")
    exit(1)

# Initialize bot and dispatcher
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# Background removal session - will be loaded on demand
bg_session = None
session_lock = threading.Lock()

def get_bg_session():
    """Thread-safe lazy loading of background removal session"""
    global bg_session
    with session_lock:
        if bg_session is None:
            try:
                logger.info("Loading AI model (u2net)...")
                bg_session = new_session('u2net')  # Keep high quality model
                logger.info("✅ AI model (u2net) loaded successfully")
            except Exception as e:
                logger.error(f"❌ Failed to load u2net model: {e}")
                raise e
    return bg_session

# Store processed images temporarily with automatic cleanup
user_images = {}
user_timestamps = {}

def cleanup_old_images():
    """Clean up images older than 10 minutes"""
    current_time = time.time()
    to_remove = []
    
    for user_id, timestamp in user_timestamps.items():
        if current_time - timestamp > 600:  # 10 minutes
            to_remove.append(user_id)
    
    for user_id in to_remove:
        if user_id in user_images:
            del user_images[user_id]
        if user_id in user_timestamps:
            del user_timestamps[user_id]
    
    if to_remove:
        gc.collect()
        logger.info(f"Cleaned up {len(to_remove)} old images")

async def periodic_cleanup():
    """Periodic cleanup task"""
    while True:
        await asyncio.sleep(300)  # Every 5 minutes
        cleanup_old_images()
        # Force garbage collection periodically
        gc.collect()
        logger.info(f"Periodic cleanup completed. Active users: {len(user_images)}")

def create_result_keyboard(user_id: int):
    """Create keyboard for result delivery options"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📎 Download (Transparent PNG)", callback_data=f"send_doc_{user_id}"),
        ],
        [
            InlineKeyboardButton(text="🖼️ Quick Preview", callback_data=f"send_photo_{user_id}"),
        ]
    ])
    return keyboard

def ensure_transparency(image):
    """Ensure the image has proper transparency"""
    try:
        if image.mode != 'RGBA':
            image = image.convert('RGBA')
        return image
    except Exception as e:
        logger.error(f"Error in transparency processing: {e}")
        return image

def process_image_optimized(input_image):
    """Process image with memory optimization"""
    try:
        # Ensure RGB mode for processing
        if input_image.mode != 'RGB':
            rgb_image = input_image.convert('RGB')
        else:
            rgb_image = input_image
        
        # Get session
        session = get_bg_session()
        
        # Log image info
        width, height = rgb_image.size
        logger.info(f"Processing image: {width}x{height}")
        
        # Remove background
        logger.info("Removing background with u2net model...")
        output_data = remove(rgb_image, session=session)
        
        # Clean up intermediate image
        if rgb_image != input_image:
            del rgb_image
        
        # Force garbage collection
        gc.collect()
        
        return ensure_transparency(output_data)
        
    except Exception as e:
        logger.error(f"Error in image processing: {e}")
        gc.collect()  # Clean up on error
        raise e

@dp.message(CommandStart())
async def command_start_handler(message: Message) -> None:
    """Handle the /start command"""
    await message.answer(
        f"👋 Hello {hbold(message.from_user.full_name)}!\n\n"
        "🤖 <b>AI Background Remover Bot</b>\n\n"
        "✨ <b>What I do:</b>\n"
        "• Remove backgrounds with AI precision (u2net model)\n"
        "• Create high-quality transparent PNG files\n"
        "• Preserve original image quality\n"
        "• Support images up to 20MB\n"
        "• Free to use!\n\n"
        "📤 <b>Send me any image to get started!</b>\n\n"
        "💡 <b>Tip:</b> Download as document to keep perfect transparency!"
    )

@dp.message(F.photo)
async def handle_photo(message: Message) -> None:
    """Handle photo messages and remove background"""
    user_id = message.from_user.id
    
    try:
        logger.info(f"Processing photo from user {user_id}")
        
        # Clean up old images before processing
        cleanup_old_images()
        
        # Send processing message
        processing_msg = await message.answer(
            "🔄 <b>Processing your image...</b>\n\n"
            "🧠 Loading AI model (u2net)\n"
            "⚡ Removing background with precision\n"
            "🎨 Creating high-quality transparent PNG\n"
            "⏱️ Please wait 15-60 seconds..."
        )
        
        # Get the largest photo size for best quality
        photo = message.photo[-1]
        
        # Download the photo
        file_info = await bot.get_file(photo.file_id)
        logger.info(f"Processing image size: {file_info.file_size} bytes")
        
        photo_data = await bot.download_file(file_info.file_path)
        
        # Convert to PIL Image
        input_image = Image.open(BytesIO(photo_data.read()))
        logger.info(f"Image dimensions: {input_image.size}")
        
        # Process the image with optimization
        output_data = await asyncio.get_event_loop().run_in_executor(
            None, process_image_optimized, input_image
        )
        
        # Clean up input image
        del input_image
        photo_data.close() if hasattr(photo_data, 'close') else None
        
        # Store the processed image with timestamp
        user_images[user_id] = output_data
        user_timestamps[user_id] = time.time()
        
        logger.info(f"Image processed successfully for user {user_id}")
        
        # Delete processing message
        await processing_msg.delete()
        
        # Send result options
        await message.answer(
            "✅ <b>Background removed successfully!</b>\n\n"
            "🎨 Your high-quality transparent PNG is ready!\n"
            "📊 Original quality preserved\n"
            "📎 <b>Choose how to receive it:</b>",
            reply_markup=create_result_keyboard(user_id)
        )
        
    except Exception as e:
        logger.error(f"Error processing image: {e}")
        
        # Clean up on error
        if user_id in user_images:
            del user_images[user_id]
        if user_id in user_timestamps:
            del user_timestamps[user_id]
        gc.collect()
        
        try:
            await processing_msg.delete()
        except:
            pass
            
        await message.answer(
            "❌ <b>Processing failed</b>\n\n"
            "The server might be busy or the image format is unsupported.\n"
            "Please try again in a few moments.\n\n"
            "💡 Supported formats: JPG, PNG, WEBP, BMP"
        )

@dp.callback_query(F.data.startswith("send_doc_"))
async def send_as_document(callback: CallbackQuery) -> None:
    """Send processed image as document to preserve transparency"""
    try:
        user_id = int(callback.data.split("_")[-1])
        
        if user_id not in user_images:
            await callback.answer("❌ Image expired. Please send a new image.")
            return
        
        await callback.answer("📎 Preparing your high-quality transparent PNG...")
        
        # Get processed image
        output_data = user_images[user_id]
        
        # Convert to bytes with maximum quality
        output_buffer = BytesIO()
        output_data.save(
            output_buffer, 
            format='PNG', 
            optimize=False,  # Don't optimize to preserve quality
            compress_level=1  # Minimal compression for speed
        )
        output_buffer.seek(0)
        
        # Create InputFile for sending
        output_file = BufferedInputFile(
            file=output_buffer.read(),
            filename="background_removed_transparent.png"
        )
        
        # Send as document
        await callback.message.answer_document(
            document=output_file,
            caption="✅ <b>Your high-quality transparent PNG is ready!</b>\n\n"
                   "🎨 <b>Perfect transparency preserved</b>\n"
                   "📊 <b>Original quality maintained</b>\n"
                   "📱 Works perfectly in all design apps\n"
                   "💎 Premium AI processing (u2net model)\n\n"
                   "🔄 Send another image anytime!"
        )
        
        # Clean up immediately after sending
        if user_id in user_images:
            del user_images[user_id]
        if user_id in user_timestamps:
            del user_timestamps[user_id]
        
        # Force cleanup
        del output_data
        output_buffer.close()
        gc.collect()
        
        # Delete the options message
        await callback.message.delete()
        
    except Exception as e:
        logger.error(f"Error sending document: {e}")
        await callback.answer("❌ Error sending file. Please try again.")

@dp.callback_query(F.data.startswith("send_photo_"))
async def send_as_photo(callback: CallbackQuery) -> None:
    """Send processed image as photo for preview"""
    try:
        user_id = int(callback.data.split("_")[-1])
        
        if user_id not in user_images:
            await callback.answer("❌ Image expired. Please send a new image.")
            return
        
        await callback.answer("🖼️ Sending high-quality preview...")
        
        # Get processed image
        output_data = user_images[user_id]
        
        # Convert to bytes
        output_buffer = BytesIO()
        output_data.save(output_buffer, format='PNG', compress_level=1)
        output_buffer.seek(0)
        
        # Create InputFile for sending
        output_file = BufferedInputFile(
            file=output_buffer.read(),
            filename="preview.png"
        )
        
        # Send as photo
        await callback.message.answer_photo(
            photo=output_file,
            caption="🖼️ <b>High-Quality Preview</b> (transparency may be lost in preview)\n\n"
                   "📎 For perfect transparent PNG, use 'Download' option above!"
        )
        
        # Keep showing options
        await callback.message.answer(
            "📎 <b>Get the perfect transparent version:</b>",
            reply_markup=create_result_keyboard(user_id)
        )
        
        output_buffer.close()
        
    except Exception as e:
        logger.error(f"Error sending photo: {e}")
        await callback.answer("❌ Error sending preview.")

@dp.message(F.document)
async def handle_document(message: Message) -> None:
    """Handle document messages"""
    if not message.document.mime_type or not message.document.mime_type.startswith('image/'):
        await message.answer(
            "📄 <b>Please send an image file</b>\n\n"
            "Supported: JPG, PNG, WEBP, BMP, TIFF"
        )
        return
    
    # Support larger files - up to 20MB
    if message.document.file_size > 20 * 1024 * 1024:  # 20MB limit
        await message.answer(
            "❌ <b>File too large</b>\n\n"
            "Maximum size: 20MB\n"
            "Please compress and try again."
        )
        return
    
    # Process like photo
    await handle_photo(message)

@dp.message(Command("help"))
async def show_help(message: Message) -> None:
    """Show help information"""
    await message.answer(
        "🆘 <b>How to use:</b>\n\n"
        "1️⃣ Send any image (up to 20MB)\n"
        "2️⃣ Wait for AI processing (u2net model)\n"
        "3️⃣ Download high-quality transparent PNG\n\n"
        "💡 <b>Features:</b>\n"
        "• Premium AI model (u2net)\n"
        "• Original quality preserved\n"
        "• Perfect transparency\n"
        "• Supports all image formats\n"
        "• Fast processing\n\n"
        "🤖 Made with ❤️ using cutting-edge AI"
    )

@dp.message(Command("status"))
async def show_status(message: Message) -> None:
    """Show bot status"""
    try:
        active_users = len(user_images)
        
        await message.answer(
            f"📊 <b>Bot Status</b>\n\n"
            f"👥 Active users: {active_users}\n"
            f"🧠 Model: u2net (high quality)\n"
            f"✅ Status: Online and ready!"
        )
    except Exception as e:
        await message.answer("📊 Bot is running normally!")

@dp.message()
async def handle_other_messages(message: Message) -> None:
    """Handle all other message types"""
    await message.answer(
        "🖼️ <b>Send me an image to remove its background!</b>\n\n"
        "📤 Just send any photo or image file (up to 20MB)\n"
        "🎨 I'll create a high-quality transparent PNG for you\n"
        "🧠 Using premium u2net AI model\n\n"
        "💡 Use /help for more info"
    )

async def main() -> None:
    """Main function to start the bot"""
    logger.info("🚀 Starting High-Quality Background Remover Bot...")
    logger.info("🧠 AI model will load on first use...")
    
    # Start periodic cleanup task
    asyncio.create_task(periodic_cleanup())
    
    try:
        # Start polling
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"❌ Bot startup failed: {e}")

if __name__ == "__main__":
    asyncio.run(main())