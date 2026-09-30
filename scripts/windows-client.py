"""Submit a fixed Windows task over the bind-mounted workspace (stdlib only)."""
import argparse
import json
import shutil
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / '.windows-bridge'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('check', 'sync', 'run', 'build'))
    args = parser.parse_args()
    heartbeat = ROOT / 'heartbeat'
    try:
        alive = time.time() - heartbeat.stat().st_mtime < 15
    except FileNotFoundError:
        alive = False
    if not alive:
        print('Windows側のプロジェクトで powershell -ExecutionPolicy Bypass '
              '-File .\\scripts\\manage-windows-host.ps1 を実行するか、Dev Containersで開き直してください。', file=sys.stderr)
        return 1

    job = ROOT / uuid.uuid4().hex
    job.mkdir()
    pending = job / 'request.tmp'
    pending.write_text(json.dumps({'action': args.action}), encoding='utf-8')
    pending.rename(job / 'request.json')
    offsets = {'stdout.log': 0, 'stderr.log': 0}

    def drain():
        for name, stream in [('stdout.log', sys.stdout), ('stderr.log', sys.stderr)]:
            try:
                with (job / name).open('rb') as log:
                    log.seek(offsets[name])
                    data = log.read()
                    offsets[name] = log.tell()
                stream.buffer.write(data)
                stream.flush()
            except FileNotFoundError:
                pass

    try:
        while True:
            drain()
            result = job / 'exit-code'
            if result.exists():
                code = int(result.read_text(encoding='utf-8-sig').strip())
                drain()
                shutil.rmtree(job)
                return code
            try:
                host_alive = time.time() - heartbeat.stat().st_mtime < 15
            except FileNotFoundError:
                host_alive = False
            if not host_alive:
                print('Windows側の待受が停止しました。待受の端末を確認してください。', file=sys.stderr)
                (job / 'cancel').touch()
                return 1
            time.sleep(0.2)
    except KeyboardInterrupt:
        (job / 'cancel').touch()
        print('\nWindows側に停止を要求しました。', file=sys.stderr)
        return 130


if __name__ == '__main__':
    sys.exit(main())
