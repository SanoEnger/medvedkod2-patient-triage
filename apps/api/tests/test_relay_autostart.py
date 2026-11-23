import importlib.util
from pathlib import Path

import pytest

pytest.importorskip('msvcrt')
spec = importlib.util.spec_from_file_location('relay_autostart', Path(__file__).resolve().parents[1] / 'scripts/relay_autostart.py')
supervisor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(supervisor)


def test_new_tunnel_updates_both_environments_and_redeploys_current_production(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(supervisor, 'RUNTIME', tmp_path)
    monkeypatch.setattr(supervisor, 'run_cli', lambda cli, args, value=None: calls.append((args, value)))
    url = 'https://synthetic-relay.trycloudflare.com'
    supervisor.publish_url('synthetic-cli', url)
    assert [args[args.index('--environment') + 1] for args, _ in calls] == ['production', 'preview', 'production']
    assert all(args[args.index('--project') + 1] == 'medved-api' for args, _ in calls[:2])
    assert calls[-1][0][:2] == ['redeploy', 'https://medved-api.vercel.app']
    assert (tmp_path / 'published-url.txt').read_text() == url


def test_failed_redeploy_keeps_previous_published_state(monkeypatch, tmp_path):
    monkeypatch.setattr(supervisor, 'RUNTIME', tmp_path)
    published = tmp_path / 'published-url.txt'
    published.write_text('https://previous.trycloudflare.com')

    def cli(_cli, args, value=None):
        if args[0] == 'redeploy':
            raise RuntimeError('synthetic_failure')

    monkeypatch.setattr(supervisor, 'run_cli', cli)
    with pytest.raises(RuntimeError):
        supervisor.publish_url('synthetic-cli', 'https://replacement.trycloudflare.com')
    assert published.read_text() == 'https://previous.trycloudflare.com'


def test_arbitrary_tunnel_destination_never_reaches_vercel(monkeypatch):
    monkeypatch.setattr(supervisor, 'run_cli', lambda *args: pytest.fail('must not update Vercel'))
    with pytest.raises(ValueError):
        supervisor.publish_url('synthetic-cli', 'https://untrusted.example')
