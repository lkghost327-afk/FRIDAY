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
        alias = re.fullmatch(r'when I say ([\w -]{1,40})[, :]\s*(.+)', text, re.I)
        if ',' not in text and ':' not in text:
            alias = re.fullmatch(r'when I say ([\w -]{1,40}?)\s+((?:open|minimize|maximize|restore|focus|(?:set )?volume|(?:set )?brightness)\s+.+)', text, re.I) or alias
        if alias:
            text = f'create routine {alias[1].strip()}: {alias[2]}'
        match = re.fullmatch(r'(?:create|save) routine ([\w -]{1,40}):\s*(.+)', text, re.I)
        if match:
            name, steps = match[1].strip().casefold(), self.split_steps(match[2])
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
            # Only explicit sequence separators; "and" can be part of an app name.
            if re.match(r'(?:open|minimize|maximize|restore|focus|(?:set )?volume|(?:set )?brightness)\b', text, re.I) and re.search(r';|\s+then\s+', text, re.I):
                return self.run(self.split_steps(text), router)
            if re.fullmatch(r'[\w -]{1,40}', text):
                data = self.load()
                name = text.casefold().strip()
                if name in data:
                    return self.run(data[name], router)
            return None
        data = self.load()
        name = match[2].casefold().strip()
        if name not in data:
            return None if match[1].casefold() == 'start' else f'No routine named {name}.'
        if match[1].casefold() == 'delete routine':
            del data[name]
            atomic_json(self.path, data)
            return f'Deleted routine {name}.'
        return self.run(data[name], router)

    @staticmethod
    def split_steps(text):
        return [s.strip() for s in re.split(r';|\s+then\s+', text, flags=re.I)]

    def run(self, steps, router):
        actions = self.validate(steps)  # Validate every step before any side effect.
        results = []
        for tool, args in actions:
            if router._stop.is_set() or router.cancelled():
                results.append('Routine cancelled before the next step.')
                break
            result = router.execute(tool, args)
            results.append(result)
            if not self.confirmed(tool, result, args):
                results.append('Routine stopped because that step was not confirmed.')
                break
        return '\n'.join(results)

    @staticmethod
    def confirmed(tool, result, args):
        """Fail closed for unknown outcomes, including missing dependencies."""
        if tool == 'open_app':
            return any(line.startswith('Confirmed: ') and line.endswith(' is open.') for line in result.splitlines())
        if tool == 'window_control':
            return result.endswith(': confirmed.')
        if tool == 'set_volume':
            match = re.fullmatch(r'Volume is (\d+)%\..*', result)
            return bool(match and int(match[1]) == args['percent'])
        if tool == 'set_brightness':
            match = re.fullmatch(r'Display brightness: (\d+%(?:, \d+%)*)\.', result)
            return bool(match and all(int(value) == args['percent'] for value in re.findall(r'\d+', match[1])))
        return False
