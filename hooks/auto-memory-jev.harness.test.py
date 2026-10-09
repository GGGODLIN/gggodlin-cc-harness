#!/usr/bin/env python3
"""Real Claude executable, isolated HOME/settings, local fake main/Jev APIs, zero paid calls."""
import http.server
import json
import os
from pathlib import Path
import queue
import subprocess
import tempfile
import threading
import time

HERE = Path(__file__).resolve().parent
CLAUDE = (Path.home() / '.local/bin/claude').resolve()
RULE = (HERE.parent / 'memory/feedback_memory_cluster_maintenance.md').read_text()
MODEL = 'type-safe/jev-latest:free'
REPLY = 'Understood. I will use concise Traditional Chinese answers in future sessions.'


def wait_for(predicate, seconds=8):
  deadline = time.monotonic() + seconds
  while time.monotonic() < deadline:
    if predicate():
      return
    time.sleep(0.05)
  raise AssertionError('harness_condition_timeout')


def main():
  calls = []
  requests = []
  class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_):
      pass

    def send_json(self, obj):
      raw = json.dumps(obj).encode()
      self.send_response(200)
      self.send_header('Content-Type', 'application/json')
      self.send_header('Content-Length', str(len(raw)))
      self.end_headers()
      self.wfile.write(raw)

    def do_GET(self):
      if self.path == '/api/v1/models':
        self.send_json({'data': [{'id': MODEL, 'pricing': {'prompt': '0', 'completion': '0'}}]})
      else:
        self.send_json({})

    def do_POST(self):
      body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))))
      if self.path.startswith('/v1/systemone'):
        assert body['model'] == MODEL
        calls.append(body)
        self.send_json({'model': 'jev-latest', 'answers': {'direct_nudge': {'noul': 0.7}},
                        'usage': {'input_tokens': 600, 'output_tokens': 23, 'cost': 0}})
      elif 'count_tokens' in self.path:
        self.send_json({'input_tokens': 100})
      elif '/v1/messages' in self.path:
        # Inspect delivery in the actual main request, not the hook's own stdout.
        encoded = json.dumps(body, ensure_ascii=False)
        requests.append({'memory_context': '[auto-memory:jev:' in encoded,
                         'full_rules': '## Tier 1:' in encoded})
        mid = 'msg_fixture_' + str(len(requests))
        message = {'id': mid, 'type': 'message', 'role': 'assistant', 'model': 'claude-sonnet-4-5-20250929',
                   'content': [], 'stop_reason': None, 'stop_sequence': None,
                   'usage': {'input_tokens': 100, 'output_tokens': 1}}
        if not body.get('stream'):
          message.update(content=[{'type': 'text', 'text': REPLY}], stop_reason='end_turn')
          self.send_json(message)
          return
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()
        events = [
          ('message_start', {'type': 'message_start', 'message': message}),
          ('content_block_start', {'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'text', 'text': ''}}),
          ('content_block_delta', {'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'text_delta', 'text': REPLY}}),
          ('content_block_stop', {'type': 'content_block_stop', 'index': 0}),
          ('message_delta', {'type': 'message_delta', 'delta': {'stop_reason': 'end_turn', 'stop_sequence': None},
                             'usage': {'output_tokens': 17}}),
          ('message_stop', {'type': 'message_stop'}),
        ]
        for event, data in events:
          self.wfile.write(('event: ' + event + '\ndata: ' + json.dumps(data) + '\n\n').encode())
          self.wfile.flush()
      else:
        self.send_json({})

  server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
  server_thread = threading.Thread(target=server.serve_forever, daemon=True)
  server_thread.start()
  process = None
  try:
    with tempfile.TemporaryDirectory(prefix='jev-memory-harness-') as temp:
      home = Path(temp).resolve()
      cwd = home / 'Desktop/projects/fixture'
      cwd.mkdir(parents=True)
      rule = home / '.claude/memory/feedback_memory_cluster_maintenance.md'
      rule.parent.mkdir(parents=True)
      rule.write_text(RULE)
      probe = home / 'probe.py'
      probe.write_text('import os,json,sys,subprocess\n'
        'raw=sys.stdin.read();p=json.loads(raw)\n'
        'r={"event":p.get("hook_event_name"),"cwd":p.get("cwd"),"agent_id_present":bool(p.get("agent_id")),"agent_type":p.get("agent_type"),"child_session":os.environ.get("CLAUDE_CODE_CHILD_SESSION"),"stop_hook_active":p.get("stop_hook_active")}\n'
        'with open(os.path.join(os.environ["HOME"],"probe.jsonl"),"a") as f:f.write(json.dumps(r)+"\\n")\n'
        'subprocess.run([sys.executable,' + repr(str(HERE / 'auto-memory-jev.py')) + ',sys.argv[1]],input=raw,text=True,check=True)\n')
      settings = home / 'settings.json'
      settings.write_text(json.dumps({'hooks': {
        'Stop': [{'hooks': [{'type': 'command', 'command': 'python3 ' + str(probe) + ' stop', 'async': True}]}],
        'UserPromptSubmit': [{'hooks': [{'type': 'command', 'command': 'python3 ' + str(probe) + ' deliver', 'timeout': 3}]}],
      }}))
      base = 'http://127.0.0.1:' + str(server.server_port)
      env = {k: v for k, v in os.environ.items() if k in ('PATH', 'LANG', 'LC_CTYPE', 'TMPDIR', 'TERM')}
      env.update(HOME=str(home), ANTHROPIC_BASE_URL=base, ANTHROPIC_AUTH_TOKEN='fixture-not-real',
                 CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC='1', DISABLE_TELEMETRY='1', DISABLE_AUTOUPDATER='1',
                 DISABLE_ERROR_REPORTING='1', JEV_MEMORY_TEST_MODE='1', JEV_MEMORY_TEST_URL=base)
      process = subprocess.Popen([str(CLAUDE), '-p', '--input-format', 'stream-json', '--output-format', 'stream-json',
        '--verbose', '--setting-sources', 'project', '--settings', str(settings), '--permission-mode', 'bypassPermissions',
        '--model', 'claude-sonnet-4-5-20250929'], cwd=cwd, env=env, text=True,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
      results = queue.Queue()
      def read_results():
        for line in process.stdout:
          try:
            row = json.loads(line)
          except ValueError:
            continue
          if row.get('type') == 'result':
            results.put(row)
      reader = threading.Thread(target=read_results, daemon=True)
      reader.start()
      def send(text):
        process.stdin.write(json.dumps({'type': 'user', 'message': {'role': 'user', 'content': text}}) + '\n')
        process.stdin.flush()
      send('For all future sessions, I prefer concise Traditional Chinese answers. This is a standing preference.')
      first = results.get(timeout=20)
      assert not first.get('is_error'), 'first_main_result_error'
      journal_dir = home / '.claude/hooks/state/auto-memory-jev'
      def pending():
        for path in journal_dir.glob('session-*.json'):
          try:
            if json.loads(path.read_text()).get('pending'):
              return True
          except ValueError:
            pass
        return False
      try:
        wait_for(pending)
      except AssertionError:
        log = home / '.claude/logs/auto-memory-jev.jsonl'
        statuses = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        shapes = []
        for transcript in (home / '.claude/projects').glob('*/*.jsonl'):
          for line in transcript.read_text().splitlines():
            entry = json.loads(line)
            if entry.get('type') in ('user', 'assistant'):
              shapes.append({'type': entry.get('type'), 'origin_kind': (entry.get('origin') or {}).get('kind'),
                             'turnOrigin': entry.get('turnOrigin'), 'promptSource': entry.get('promptSource'),
                             'isMeta': entry.get('isMeta'), 'content_type': type((entry.get('message') or {}).get('content')).__name__,
                             'stop_reason': (entry.get('message') or {}).get('stop_reason')})
        probe_file = home / 'probe.jsonl'
        probes = [json.loads(line) for line in probe_file.read_text().splitlines()] if probe_file.exists() else []
        print(json.dumps({'diagnostic_fixture_only': True, 'judge_calls': len(calls), 'audit': statuses, 'shapes': shapes, 'hook_payloads': probes}))
        raise
      assert len(calls) == 1 and not requests[0]['memory_context']
      assert not list((home / '.claude/hooks/state').glob('long_injected_*'))
      send('Continue the original task.')
      second = results.get(timeout=20)
      assert not second.get('is_error'), 'second_main_result_error'
      assert len(requests) >= 2 and requests[1]['memory_context'] and requests[1]['full_rules'], 'context_not_in_main_request'
      wait_for(lambda: bool(list((home / '.claude/hooks/state').glob('long_injected_*'))))
      marker = next((home / '.claude/hooks/state').glob('long_injected_*'))
      assert int(marker.read_text()) >= 1
      assert rule.read_text() == RULE, 'fixture_memory_changed'
      assert not list((home / '.claude/hooks/state').glob('trigger_*'))
      assert not list((home / '.claude/hooks/state').glob('checkpoint_*'))
      process.stdin.close()
      process.wait(timeout=10)
      reader.join(timeout=2)
      process.stdout.close()
      process.stderr.close()
      print(json.dumps({'main_requests': len(requests), 'first_request_memory_context': requests[0]['memory_context'],
                        'second_request_memory_context': requests[1]['memory_context'], 'second_request_full_rules': requests[1]['full_rules'],
                        'shared_marker_written': True, 'memory_unchanged': True, 'manual_sentinels_untouched': True,
                        'provider_calls_are_local_fixtures': True}))
      print('AUTO_MEMORY_JEV_HARNESS_OK')
  finally:
    if process and process.poll() is None:
      process.kill()
      process.wait()
    if process:
      for handle in (process.stdin, process.stdout, process.stderr):
        if handle and not handle.closed:
          handle.close()
    server.shutdown()
    server.server_close()
    server_thread.join(timeout=2)


if __name__ == '__main__':
  main()
