"""Isolated tray soak. Default eight hours; no microphone, API keys or PC actions.

Run a separate hands-on wake/microphone soak after first-time setup. This harness
checks idle UI, tray, threads, device enumeration and memory growth only.
"""
import argparse
import json
from pathlib import Path
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--seconds', type=int, default=8*60*60)
    parser.add_argument('--persona', choices=['friday', 'alfred'], default='friday')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not 10 <= args.seconds <= 48*60*60:
        parser.error('Use a duration from 10 seconds to 48 hours.')
    import psutil
    from assistant_core.controller import AssistantController
    from assistant_core.settings import Settings
    from assistant_core.ui import AssistantWindow
    from assistant_core import __version__
    process = psutil.Process()
    samples = []
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='assistant-soak-') as folder:
        Settings(persona=args.persona, speech_enabled=False).save(folder)
        controller = AssistantController(folder, args.persona)
        # Never inherit provider keys from the launching shell in this test.
        controller.save_settings({'api_key':'', 'deepgram_api_key':'', 'wake_on_start':False})
        window = AssistantWindow(controller, background=True)
        controller.start()
        def tick():
            samples.append({'elapsed':round(time.monotonic()-started,1), 'rss_mb':round(process.memory_info().rss/1024**2,1),
                'cpu_percent':process.cpu_percent(), 'threads':process.num_threads(),
                'handles':process.num_handles(), 'tray_hidden':window._hidden_to_tray})
            if time.monotonic()-started >= args.seconds:
                window._exit()
            else:
                window._schedule(10000, tick)
        window._schedule(1000, tick)
        try:
            window.mainloop()
        finally:
            controller.close()
            if controller._device_watch.thread:
                controller._device_watch.thread.join(2)
            for handler in list(controller.log.handlers):
                handler.close()
                controller.log.removeHandler(handler)
    report = {'version':__version__, 'persona':args.persona,
        'device_notifications_ready':controller._device_watch.ready.is_set(),
        'device_notifications_error':controller._device_watch.error,
        'scope':'Isolated idle tray only; microphone, spoken replies and cloud calls off.',
        'requested_seconds':args.seconds, 'elapsed_seconds':round(time.monotonic()-started,1), 'samples':samples}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(f'Saved {len(samples)} samples to {args.output}')


if __name__ == '__main__':
    main()
