"""Explicit one-shot primary-screen questions; no ambient capture or image files."""
import base64
import io
import re


def is_screen_question(text):
    return bool(re.match(r"^(?:please )?(?:look at (?:my |the )?screen\b|(?:what is|what's|explain|describe|summarize|read) (?:on )?(?:my |the )screen\b)", text.strip(), re.I))


def capture_screen():
    from PIL import ImageGrab
    picture = ImageGrab.grab(all_screens=False).convert('RGB')
    try:
        picture.thumbnail((1920, 1200))
        stream = io.BytesIO()
        picture.save(stream, format='JPEG', quality=85)
        return 'data:image/jpeg;base64,' + base64.b64encode(stream.getvalue()).decode('ascii')
    finally:
        picture.close()
