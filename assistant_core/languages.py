"""Hindi/Hinglish command phrases; every match goes through validated action tools.

This is a small command vocabulary, not a translator. Unmatched questions remain
conversation text. In particular, negated and hypothetical actions are not run.
"""
import re
import unicodedata

APP_NAMES = {
    'स्पॉटिफाई':'Spotify', 'स्पोटिफाई':'Spotify', 'स्पॉटीफाई':'Spotify',
    'नोटपैड':'Notepad', 'नोट पैड':'Notepad', 'क्रोम':'Chrome', 'गूगल क्रोम':'Chrome',
    'एज':'Edge', 'माइक्रोसॉफ्ट एज':'Edge', 'फायरफॉक्स':'Firefox',
    'फाइल एक्सप्लोरर':'File Explorer', 'फ़ाइल एक्सप्लोरर':'File Explorer',
    'व्हाट्सएप':'WhatsApp', 'व्हाट्सऐप':'WhatsApp', 'डिस्कॉर्ड':'Discord',
    'कैलकुलेटर':'Calculator', 'कैलकुलेटर ऐप':'Calculator',
    'टेलीग्राम':'Telegram', 'यूट्यूब':'YouTube', 'ब्राउज़र':'browser', 'ब्राउजर':'browser',
    'इसे':'it', 'इसको':'it', 'उसे':'it', 'isko':'it', 'ise':'it', 'usse':'it',
}
STOP_PHRASES = {'रुको', 'रुक जाओ', 'चुप हो जाओ', 'बस करो', 'रद्द करो',
                'ruko', 'ruk jao', 'chup ho jao', 'bas karo', 'cancel karo'}


def is_hindi(text):
    return bool(re.search(r'[\u0900-\u097f]', text))


def clean(text):
    return unicodedata.normalize('NFC', text).strip().strip(' .!?।').casefold()


def is_stop(text):
    return clean(text) in STOP_PHRASES | {'stop', 'cancel', 'be quiet', 'stop talking'}


def app_name(text):
    text = re.sub(r'\s+(?:को|ko|ऐप|app)$', '', text.strip(), flags=re.I)
    return APP_NAMES.get(clean(text), text)


def command(text):
    value = clean(text).translate(str.maketrans('०१२३४५६७८९', '0123456789'))
    value = re.sub(r'^(?:कृपया|ज़रा|जरा|zara|jara|please)\s+', '', value)
    if re.search(r'(?:\b(?:mat|nahi|nahin|kaise|agar)\b|मत|नहीं|कैसे|अगर|क्या)', value) or '?' in text:
        return None
    if is_stop(value):
        return 'stop'
    exact = {
        'समय बताओ':'what time is it', 'कितने बजे हैं':'what time is it', 'time batao':'what time is it',
        'सिस्टम की जानकारी':'system status', 'सिस्टम स्टेटस':'system status',
        'इंस्टॉल किए हुए ऐप दिखाओ':'list installed apps', 'apps dikhao':'list installed apps',
        'स्क्रीनशॉट लो':'take a screenshot', 'screenshot lo':'take a screenshot',
        'आवाज़ बंद करो':'mute', 'आवाज बंद करो':'mute', 'awaaz band karo':'mute',
        'आवाज़ कम करो':'volume down', 'आवाज कम करो':'volume down', 'volume kam karo':'volume down',
        'आवाज़ बढ़ाओ':'volume up', 'आवाज बढ़ाओ':'volume up', 'volume badhao':'volume up',
        'shutdown cancel karo':'cancel shutdown', 'शटडाउन रद्द करो':'cancel shutdown',
    }
    if value in exact:
        return exact[value]
    for phrase, action in ((r'(?:गाना चलाओ|गाना चलाएं|play karo|गाना प्ले करो)', 'play'),
            (r'(?:गाना रोको|pause karo|पॉज करो)', 'pause'),
            (r'(?:अगला गाना|agla gana|next gana)', 'next track'),
            (r'(?:पिछला गाना|pichla gana)', 'previous track')):
        match = re.fullmatch(r'(.+?)\s+(?:में|mein|me)\s+'+phrase, value)
        if match:
            return f'{action} in {app_name(match[1])}'
    # Power actions require an explicit device and an imperative, as in English.
    device = r'(?:मेरा |मेरे |मेरी |mera |mere |meri )?(?:कंप्यूटर|कम्प्यूटर|लैपटॉप|पीसी|computer|laptop|pc)(?: को| ko)?'
    for suffix, action in ((r'(?:बंद करो|band karo|shutdown karo)', 'shutdown'),
            (r'(?:रीस्टार्ट करो|दोबारा चालू करो|restart karo)', 'restart'),
            (r'(?:स्लीप में डालो|sleep mein dalo|sleep me dalo)', 'sleep'),
            (r'(?:लॉक करो|lock karo)', 'lock')):
        if re.fullmatch(device + r'\s+' + suffix, value):
            return {'shutdown':'shut down my computer', 'restart':'restart my computer',
                    'sleep':'put my computer to sleep', 'lock':'lock my computer'}[action]
    match = re.fullmatch(r'(?:आवाज़|आवाज|वॉल्यूम|volume|awaaz)\s+(\d{1,3})(?:\s*(?:प्रतिशत|percent|%))?\s*(?:करो|कर दो|रखो|karo|kar do|rakho)', value)
    if match:
        return 'volume ' + match[1] + ' percent'
    match = re.fullmatch(r'(.+?)\s+(?:में|mein|me)\s+(.+?)\s+(?:ढूंढो|ढूँढो|खोजो|सर्च करो|search karo|dhundo|khojo)', value)
    if match:
        return f'search {app_name(match[1])} for {match[2]}'
    match = re.fullmatch(r'(.+?)\s+(?:में|mein|me)\s+(?:पीछे जाओ|वापस जाओ|back jao)', value)
    if match:
        return f'go back in {app_name(match[1])}'
    for phrase, verb in ((r'(?:खोलो|खोल दो|चालू करो|kholo|khol do|open karo)', 'open'),
            (r'(?:बंद करो|बंद कर दो|band karo|band kar do|close karo)', 'close'),
            (r'(?:छोटा करो|मिनिमाइज़ करो|minimize karo)', 'minimize'),
            (r'(?:बड़ा करो|मैक्सिमाइज़ करो|maximize karo)', 'maximize')):
        match = re.fullmatch(r'(.+?)\s+'+phrase, value)
        if match:
            return f'{verb} {app_name(match[1])}'
    return None
