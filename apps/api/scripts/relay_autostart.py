"""Windows logon supervisor for the local MAX relay and its temporary HTTPS URL."""

import ctypes
from ctypes import wintypes
import json
import msvcrt
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[3]
RUNTIME = ROOT / '.local/core-relay'
URL_PATTERN = re.compile(r'https://[a-z0-9-]+\.trycloudflare\.com')


def log(message):
    with (RUNTIME / 'autostart.log').open('a', encoding='utf-8') as stream:
        stream.write(datetime.now().isoformat(timespec='seconds') + ' ' + message + '\n')


def alive(pid):
    if not isinstance(pid, int) or pid <= 0:
        return False
    kernel = ctypes.windll.kernel32
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x100000, False, pid)
    if not handle:
        return False
    try:
        return kernel.WaitForSingleObject(handle, 0) == 258
    finally:
        kernel.CloseHandle(handle)


def reachable(base):
    try:
        return httpx.post(base + '/resolve', json={'token': 'synthetic-health-check'}, timeout=8).status_code == 401
    except httpx.RequestError:
        return False


def spawn(args, filename, env=None):
    with (RUNTIME / filename).open('ab') as output:
        return subprocess.Popen(args, cwd=ROOT / 'apps/api', env=env,
            creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
            stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT)


def run_cli(cli, args, value=None):
    result = subprocess.run(['node', cli, *args, '--scope', 'xennophrykiryk-7819'],
        input=value, text=True, capture_output=True, timeout=300,
        creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        # CLI diagnostics can contain credential material; never persist them.
        raise RuntimeError('vercel_operation_failed')


def publish_url(cli, url):
    if not URL_PATTERN.fullmatch(url):
        raise ValueError('invalid_tunnel_url')
    for target in ('production', 'preview'):
        run_cli(cli, ['env', 'add', 'CORE_RELAY_URL', '--environment', target,
                      '--project', 'medved-api', '--force', '--yes'], url)
    # Rebuild the current production deployment, never an arbitrary/new branch.
    run_cli(cli, ['redeploy', 'https://medved-api.vercel.app', '--environment', 'production', '--json'])
    (RUNTIME / 'published-url.txt').write_text(url, encoding='utf-8')
    log('Vercel relay address updated; API redeployed')


def main():
    RUNTIME.mkdir(exist_ok=True)
    with (RUNTIME / 'autostart.lock').open('a+b') as lock:
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return
        settings = json.loads((RUNTIME / 'autostart.json').read_text(encoding='utf-8-sig'))
        values = dict(dotenv_values(RUNTIME / 'private.env'))
        if len(values.get('CORE_RELAY_TOKEN', '')) < 32 or not values.get('CORE_SERVICE_TOKEN'):
            raise ValueError('relay_credentials_missing')
        env = {**os.environ, **values, 'PYTHONPATH': str(ROOT / 'apps/api'), 'MEDVED_DISABLE_DOTENV': '1'}
        state_file = RUNTIME / 'processes.json'
        state = json.loads(state_file.read_text()) if state_file.exists() else {}
        boot = subprocess.run(['powershell.exe', '-NoProfile', '-Command',
            "(Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToUniversalTime().ToString('o')"],
            check=True, capture_output=True, text=True, timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW).stdout.strip()
        if state.get('boot_id', boot) != boot:
            state = {}
        state['boot_id'] = boot
        state_file.write_text(json.dumps(state), encoding='utf-8')
        python = settings['python']
        cli = settings['vercel_cli']
        url_file = RUNTIME / 'url.txt'
        url = url_file.read_text().strip() if url_file.exists() else ''
        log('Supervisor started')
        while True:
            try:
                if not reachable('http://127.0.0.1:8765'):
                    if not alive(state.get('api')):
                        child = spawn([python, '-m', 'uvicorn', 'app.core_relay:create_relay', '--factory',
                            '--host', '127.0.0.1', '--port', '8765', '--no-access-log', '--no-proxy-headers'], 'api.log', env)
                        state['api'] = child.pid
                        log('Relay process started')
                    state_file.write_text(json.dumps(state), encoding='utf-8')
                    time.sleep(10)
                    continue
                if not alive(state.get('tunnel')):
                    tunnel_log = RUNTIME / 'tunnel-autostart.log'
                    tunnel_log.write_text('', encoding='utf-8')
                    child = spawn([str(ROOT / '.local/bin/cloudflared.exe'), 'tunnel', '--no-autoupdate',
                        '--url', 'http://127.0.0.1:8765', '--protocol', 'http2'], 'tunnel-autostart.log')
                    state['tunnel'] = child.pid
                    state_file.write_text(json.dumps(state), encoding='utf-8')
                    url = ''
                    log('HTTPS tunnel process started')
                if not url:
                    matches = URL_PATTERN.findall((RUNTIME / 'tunnel-autostart.log').read_text(errors='replace'))
                    if matches:
                        url = matches[-1]
                        url_file.write_text(url, encoding='utf-8')
                published = RUNTIME / 'published-url.txt'
                previous = published.read_text().strip() if published.exists() else ''
                if url and url != previous and reachable(url):
                    publish_url(cli, url)
            except Exception as error:
                log('Retrying after ' + type(error).__name__)
            time.sleep(30)


if __name__ == '__main__':
    main()
