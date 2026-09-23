"""User-authored, bounded routines; validation never performs an action."""
import json
import re
from .settings import atomic_json


def parse_step(text):
    text = text.strip()
    for pattern, tool, builder in (
        (r'open (.+)', 'open_app', lambda m: {'app': m[1]}),
        (r'(minimize|maximize|restore|focus) (.+)', 'window_control', lambda m: {'action': m[1].lower(), 'app': m[2]}),
        (r'(?:set )?volume(?: to)? (\d{1,3})(?: percent|%)?', 'set_volume', lambda m: {'action':'set', 'percent':int(m[1])}),
        (r'(?:set )?brightness(?: to)? (\d{1,3})(?: percent|%)?', 'set_brightness', lambda m: {'action':'set', 'percent':int(m[1])}),
    ):
        match = re.fullmatch(pattern, text, re.I)
        if match:
            args = builder(match)
            if args.get('percent', 0) > 100:
                raise ValueError('Routine percentages must be between 0 and 100.')
            if args.get('app', '').casefold() in {'it','that','this app','that app'}:
                raise ValueError('Use explicit app names in routines.')
            return tool, args
    raise ValueError('Routines support opening apps, window controls, volume and brightness; separate steps with semicolons.')


class Routines:
    def __init__(self, path):
        self.path = path

    def load(self):
        if not self.path.exists():
            return {}
        data = json.loads(self.path.read_text(encoding='utf-8'))
        if not isinstance(data, dict) or len(data) > 30:
            raise ValueError('The routines file is invalid; no routine was run.')
        for name, steps in data.items():
            if not isinstance(name, str) or not re.fullmatch(r'[\w -]{1,40}', name) or not name.strip():
                raise ValueError('The routines file contains an invalid name.')
            self.validate(steps)
        return data

    def validate(self, steps):
        if not isinstance(steps, list) or not 1 <= len(steps) <= 8:
            raise ValueError('A routine needs between one and eight steps.')
        for step in steps:
            if not isinstance(step, str) or len(step) > 200:
                raise ValueError('Invalid routine step.')
        return [parse_step(step) for step in steps]

    def handle(self, text, router):
        match = re.fullmatch(r'(?:create|save) routine ([\w -]{1,40}):\s*(.+)', text, re.I)
        if match:
            name, steps = match[1].strip().casefold(), [s.strip() for s in match[2].split(';')]
            if not name:
                raise ValueError('Give the routine a name.')
            self.validate(steps)
            data = self.load()
            if name not in data and len(data) >= 30:
                raise ValueError('You can save up to 30 routines.')
            data[name] = steps
            atomic_json(self.path, data)
            return f'Saved routine {name}. Say “run routine {name}”.'
        if text.casefold() in {'list routines', 'show routines'}:
            data = self.load()
            return '\n'.join(f'{name}: ' + '; '.join(steps) for name, steps in data.items()) or 'No routines saved.'
        match = re.fullmatch(r'(run routine|start|delete routine) ([\w -]{1,40})', text, re.I)
        if not match:
            return None
        data = self.load()
        name = match[2].casefold().strip()
        if name not in data:
            return None if match[1].casefold() == 'start' else f'No routine named {name}.'
        if match[1].casefold() == 'delete routine':
            del data[name]
            atomic_json(self.path, data)
            return f'Deleted routine {name}.'
        actions = self.validate(data[name])  # Validate every step before any side effect.
        results = []
        for tool, args in actions:
            if router._stop.is_set() or router.cancelled():
                results.append('Routine cancelled before the next step.')
                break
            result = router.execute(tool, args)
            results.append(result)
            if any(word in result.casefold() for word in ("couldn't", 'not confirmed', 'not supported', 'ambiguous', 'could not')):
                results.append('Routine stopped because that step was not confirmed.')
                break
        return '\n'.join(results)
