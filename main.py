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

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Get token from environment variable (IMPORTANT for hosting)
BOT_TOKEN = os.getenv(TOKEN)

if not BOT_TOKEN:
    logger.error("❌ BOT_TOKEN environment variable not set!")
    logger.error("Please set BOT_TOKEN in your hosting platform")
    exit(1)

# Initialize bot and dispatcher
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# Initialize background removal session with lightweight model for hosting
try:
    bg_session = new_session('u2netp')  # Best balance of quality and speed
    logger.info("✅ AI model loaded successfully")
except Exception as e:
    logger.error(f"❌ Failed to load AI model: {e}")
    exit(1)

# Store processed images temporarily
user_images = {}


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
        # Convert to RGBA if not already
        if image.mode != 'RGBA':
            image = image.convert('RGBA')
        
        return image
    except Exception as e:
        logger.error(f"Error in transparency processing: {e}")
        return image


@dp.message(CommandStart())
async def command_start_handler(message: Message) -> None:
    """Handle the /start command"""
    await message.answer(
        f"👋 Hello {hbold(message.from_user.full_name)}!\n\n"
        "🤖 <b>AI Background Remover Bot</b>\n\n"
        "✨ <b>What I do:</b>\n"
        "• Remove backgrounds with AI precision\n"
        "• Create transparent PNG files\n"
        "• Preserve image quality\n"
        "• Free to use!\n\n"
        "📤 <b>Send me any image to get started!</b>\n\n"
        "💡 <b>Tip:</b> Download as document to keep transparency!"
    )


@dp.message(F.photo)
async def handle_photo(message: Message) -> None:
    """Handle photo messages and remove background"""
    try:
        user_id = message.from_user.id
        logger.info(f"Processing photo from user {user_id}")
        
        # Send processing message
        processing_msg = await message.answer(
            "🔄 <b>Processing your image...</b>\n\n"
            "⚡ AI is removing the background\n"
            "🎨 Creating transparent PNG\n"
            "⏱️ Please wait 10-30 seconds..."
        )
        
        # Get the largest photo size for best quality
        photo = message.photo[-1]
        
        # Download the photo
        file_info = await bot.get_file(photo.file_id)
        photo_data = await bot.download_file(file_info.file_path)
        
        # Convert to PIL Image and ensure RGB mode for processing
        input_image = Image.open(BytesIO(photo_data.read()))
        if input_image.mode != 'RGB':
            input_image = input_image.convert('RGB')
        
        # Remove background using rembg
        logger.info("Removing background...")
        output_data = remove(input_image, session=bg_session)
        
        # Ensure proper transparency
        output_data = ensure_transparency(output_data)
        
        # Store the processed image
        user_images[user_id] = output_data
        logger.info(f"Image processed successfully for user {user_id}")
        
        # Delete processing message
        await processing_msg.delete()
        
        # Send result options
        await message.answer(
            "✅ <b>Background removed successfully!</b>\n\n"
            "🎨 Your transparent PNG is ready!\n"
            "📎 <b>Choose how to receive it:</b>",
            reply_markup=create_result_keyboard(user_id)
        )
        
    except Exception as e:
        logger.error(f"Error processing image: {e}")
        try:
            await processing_msg.delete()
        except:
            pass
        await message.answer(
            "❌ <b>Processing failed</b>\n\n"
            "The image might be too large or corrupted.\n"
            "Please try with a smaller image (under 10MB)."
        )


@dp.callback_query(F.data.startswith("send_doc_"))
async def send_as_document(callback: CallbackQuery) -> None:
    """Send processed image as document to preserve transparency"""
    try:
        user_id = int(callback.data.split("_")[-1])
        
        if user_id not in user_images:
            await callback.answer("❌ Image expired. Please send a new image.")
            return
        
        await callback.answer("📎 Preparing your transparent PNG...")
        
        # Get processed image
        output_data = user_images[user_id]
        
        # Convert to bytes with high quality
        output_buffer = BytesIO()
        output_data.save(output_buffer, format='PNG', optimize=False)
        output_buffer.seek(0)
        
        # Create InputFile for sending
        output_file = BufferedInputFile(
            file=output_buffer.read(),
            filename="background_removed_transparent.png"
        )
        
        # Send as document
        await callback.message.answer_document(
            document=output_file,
            caption="✅ <b>Your transparent PNG is ready!</b>\n\n"
                   "🎨 <b>Perfect transparency preserved</b>\n"
                   "📱 Works in all design apps\n"
                   "💡 True transparent background\n\n"
                   "🔄 Send another image anytime!"
        )
        
        # Clean up
        del user_images[user_id]
        
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
        
        await callback.answer("🖼️ Sending preview...")
        
        # Get processed image
        output_data = user_images[user_id]
        
        # Convert to bytes
        output_buffer = BytesIO()
        output_data.save(output_buffer, format='PNG')
        output_buffer.seek(0)
        
        # Create InputFile for sending
        output_file = BufferedInputFile(
            file=output_buffer.read(),
            filename="preview.png"
        )
        
        # Send as photo
        await callback.message.answer_photo(
            photo=output_file,
            caption="🖼️ <b>Preview</b> (transparency may be lost)\n\n"
                   "📎 For transparent PNG, use 'Download' option above!"
        )
        
        # Keep showing options
        await callback.message.answer(
            "📎 <b>Get the transparent version:</b>",
            reply_markup=create_result_keyboard(user_id)
        )
        
    except Exception as e:
        logger.error(f"Error sending photo: {e}")
        await callback.answer("❌ Error sending preview.")


@dp.message(F.document)
async def handle_document(message: Message) -> None:
    """Handle document messages"""
    if not message.document.mime_type or not message.document.mime_type.startswith('image/'):
        await message.answer(
            "📄 <b>Please send an image file</b>\n\n"
            "Supported: JPG, PNG, WEBP, BMP"
        )
        return
    
    # Check file size (limit for free hosting)
    if message.document.file_size > 10 * 1024 * 1024:  # 10MB limit
        await message.answer(
            "❌ <b>File too large</b>\n\n"
            "Maximum size: 10MB\n"
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
        "1️⃣ Send any image\n"
        "2️⃣ Wait for AI processing\n"
        "3️⃣ Download transparent PNG\n\n"
        "💡 <b>Tips:</b>\n"
        "• Use 'Download' for transparency\n"
        "• Max file size: 10MB\n"
        "• Works with JPG, PNG, WEBP\n\n"
        "🤖 Made with ❤️ using AI"
    )


@dp.message()
async def handle_other_messages(message: Message) -> None:
    """Handle all other message types"""
    await message.answer(
        "🖼️ <b>Send me an image to remove its background!</b>\n\n"
        "📤 Just send any photo or image file\n"
        "🎨 I'll create a transparent PNG for you\n\n"
        "💡 Use /help for more info"
    )


async def main() -> None:
    """Main function to start the bot"""
    logger.info("🚀 Starting Background Remover Bot...")
    logger.info("🤖 Loading AI model...")
    
    try:
        # Start polling
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"❌ Bot startup failed: {e}")


if __name__ == "__main__":
    asyncio.run(main())
