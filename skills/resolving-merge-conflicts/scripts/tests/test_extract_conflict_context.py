from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'extract_conflict_context.py'


def run(command: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
  result = subprocess.run(
    command,
    cwd=cwd,
    capture_output=True,
    text=True,
    check=False,
    stdin=subprocess.DEVNULL,
    timeout=20,
    env={**os.environ, 'GIT_TERMINAL_PROMPT': '0'},
  )
  if check and result.returncode != 0:
    raise AssertionError(f'{command} failed with {result.returncode}: {result.stderr or result.stdout}')
  return result


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
  return run(['git', *args], repo, check)


def write_text(path: Path, content: str) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_text(content, encoding='utf-8')


def init_repo(root: Path) -> Path:
  repo = root
  repo.mkdir(parents=True, exist_ok=True)
  git(repo, 'init', '-q', '-b', 'main')
  git(repo, 'config', 'user.email', 'test@example.com')
  git(repo, 'config', 'user.name', 'Test')
  return repo


def commit_all(repo: Path, message: str) -> None:
  git(repo, 'add', '-A')
  git(repo, 'commit', '-q', '-m', message)


def unmerged(repo: Path) -> dict[str, dict[int, str]]:
  output = git(repo, 'ls-files', '-u', '-z').stdout
  entries: dict[str, dict[int, str]] = {}
  for record in output.split('\0'):
    if not record:
      continue
    metadata, path = record.split('\t', 1)
    mode, _, stage = metadata.split()
    entries.setdefault(path, {})[int(stage)] = mode
  return entries


def require(condition: bool, message: str) -> None:
  if not condition:
    raise AssertionError(message)


def merge_conflict(repo: Path, theirs: str = 'theirs') -> dict[str, dict[int, str]]:
  result = git(repo, 'merge', '--no-commit', '--no-ff', theirs, check=False)
  require(result.returncode == 1, f'expected merge conflict exit 1, got {result.returncode}: {result.stderr or result.stdout}')
  entries = unmerged(repo)
  require(bool(entries), 'merge exited 1 without unmerged index entries')
  return entries


def invoke(repo: Path, *args: str, expected: int = 0) -> subprocess.CompletedProcess[str]:
  result = run([sys.executable, str(SCRIPT), '--repo', str(repo), *args], repo, False)
  require(result.returncode == expected, f'extractor exit {result.returncode}, expected {expected}: {result.stderr or result.stdout}')
  return result


def payload(repo: Path, *args: str) -> dict[str, object]:
  result = invoke(repo, *args, '--json')
  try:
    return json.loads(result.stdout)
  except json.JSONDecodeError as error:
    raise AssertionError(f'invalid JSON: {result.stdout}\nstderr: {result.stderr}') from error


def create_text_conflict(root: Path, diff3: bool = False, long: bool = False, relative_path: str = 'f.txt') -> Path:
  repo = init_repo(root)
  base = 'base\n' if not long else '\n'.join(f'base-{i}' for i in range(80)) + '\n'
  write_text(repo / relative_path, base)
  commit_all(repo, 'base')
  git(repo, 'checkout', '-q', '-b', 'ours')
  ours = 'ours\n' if not long else '\n'.join(f'ours-{i}' for i in range(80)) + '\n'
  write_text(repo / relative_path, ours)
  commit_all(repo, 'ours')
  git(repo, 'checkout', '-q', 'main')
  git(repo, 'checkout', '-q', '-b', 'theirs')
  theirs = 'theirs\n' if not long else '\n'.join(f'theirs-{i}' for i in range(80)) + '\n'
  write_text(repo / relative_path, theirs)
  commit_all(repo, 'theirs')
  git(repo, 'checkout', '-q', 'ours')
  if diff3:
    git(repo, 'config', 'merge.conflictstyle', 'diff3')
  merge_conflict(repo)
  return repo


def create_add_add(root: Path) -> Path:
  repo = init_repo(root)
  write_text(repo / 'base.txt', 'base\n')
  commit_all(repo, 'base')
  git(repo, 'checkout', '-q', '-b', 'ours')
  write_text(repo / 'new.txt', 'ours\n')
  commit_all(repo, 'ours')
  git(repo, 'checkout', '-q', 'main')
  git(repo, 'checkout', '-q', '-b', 'theirs')
  write_text(repo / 'new.txt', 'theirs\n')
  commit_all(repo, 'theirs')
  git(repo, 'checkout', '-q', 'ours')
  merge_conflict(repo)
  return repo


def create_invalid_utf8_add_add(root: Path) -> tuple[Path, str]:
  repo = init_repo(root)
  write_text(repo / 'base.txt', 'base\n')
  commit_all(repo, 'base')
  ours = subprocess.run(
    ['git', 'hash-object', '-w', '--stdin'],
    cwd=repo,
    input=b'ours-\xff\n',
    capture_output=True,
    check=True,
  ).stdout.strip()
  theirs = subprocess.run(
    ['git', 'hash-object', '-w', '--stdin'],
    cwd=repo,
    input=b'theirs-\xfe\n',
    capture_output=True,
    check=True,
  ).stdout.strip()
  path_bytes = b'invalid-\xff.txt'
  index_input = b'100644 ' + ours + b' 2\t' + path_bytes + b'\0' + b'100644 ' + theirs + b' 3\t' + path_bytes + b'\0'
  index_result = subprocess.run(
    ['git', 'update-index', '-z', '--index-info'],
    cwd=repo,
    input=index_input,
    capture_output=True,
    check=False,
  )
  require(index_result.returncode == 0, f'invalid UTF-8 index setup failed: {index_result.stderr!r}')
  return repo, os.fsdecode(path_bytes)


def create_modify_delete(root: Path, ours_content: str = 'ours changed\n') -> Path:
  repo = init_repo(root)
  write_text(repo / 'f.txt', 'base\n')
  commit_all(repo, 'base')
  git(repo, 'checkout', '-q', '-b', 'ours')
  write_text(repo / 'f.txt', ours_content)
  commit_all(repo, 'ours')
  git(repo, 'checkout', '-q', 'main')
  git(repo, 'checkout', '-q', '-b', 'theirs')
  git(repo, 'rm', '-q', 'f.txt')
  commit_all(repo, 'theirs deletes')
  git(repo, 'checkout', '-q', 'ours')
  merge_conflict(repo)
  return repo


def create_binary(root: Path) -> Path:
  repo = init_repo(root)
  (repo / 'f.bin').write_bytes(b'base\xff\x00data')
  commit_all(repo, 'base')
  git(repo, 'checkout', '-q', '-b', 'ours')
  (repo / 'f.bin').write_bytes(b'ours\xff\x00data')
  commit_all(repo, 'ours')
  git(repo, 'checkout', '-q', 'main')
  git(repo, 'checkout', '-q', '-b', 'theirs')
  (repo / 'f.bin').write_bytes(b'theirs\xff\x00data')
  commit_all(repo, 'theirs')
  git(repo, 'checkout', '-q', 'ours')
  merge_conflict(repo)
  return repo


def create_rename(root: Path) -> Path:
  repo = init_repo(root)
  write_text(repo / 'old.txt', 'base\n')
  commit_all(repo, 'base')
  git(repo, 'checkout', '-q', '-b', 'ours')
  git(repo, 'mv', 'old.txt', 'ours.txt')
  commit_all(repo, 'ours rename')
  git(repo, 'checkout', '-q', 'main')
  git(repo, 'checkout', '-q', '-b', 'theirs')
  git(repo, 'mv', 'old.txt', 'theirs.txt')
  commit_all(repo, 'theirs rename')
  git(repo, 'checkout', '-q', 'ours')
  merge_conflict(repo)
  return repo


def create_submodule(root: Path) -> Path:
  sub = init_repo(root / 'subrepo')
  write_text(sub / 'value.txt', 'base\n')
  commit_all(sub, 'base')
  base = git(sub, 'rev-parse', 'HEAD').stdout.strip()
  git(sub, 'checkout', '-q', '-b', 'ours')
  write_text(sub / 'value.txt', 'ours\n')
  commit_all(sub, 'ours')
  ours = git(sub, 'rev-parse', 'HEAD').stdout.strip()
  git(sub, 'checkout', '-q', base)
  git(sub, 'checkout', '-q', '-b', 'theirs')
  write_text(sub / 'value.txt', 'theirs\n')
  commit_all(sub, 'theirs')
  theirs = git(sub, 'rev-parse', 'HEAD').stdout.strip()

  repo = init_repo(root / 'super')
  git(repo, '-c', 'protocol.file.allow=always', 'submodule', 'add', '-q', str(sub), 'sub')
  git(repo / 'sub', 'checkout', '-q', base)
  git(repo, 'add', 'sub')
  commit_all(repo, 'base submodule')
  git(repo, 'checkout', '-q', '-b', 'ours')
  git(repo / 'sub', 'checkout', '-q', ours)
  git(repo, 'add', 'sub')
  commit_all(repo, 'ours submodule')
  git(repo, 'checkout', '-q', 'main')
  git(repo, 'checkout', '-q', '-b', 'theirs')
  git(repo / 'sub', 'checkout', '-q', theirs)
  git(repo, 'add', 'sub')
  commit_all(repo, 'theirs submodule')
  git(repo, 'checkout', '-q', 'ours')
  git(repo / 'sub', 'checkout', '-q', ours)
  merge_conflict(repo)
  return repo


def run_tests() -> list[dict[str, str]]:
  require(__debug__, 'run without Python optimization')
  results: list[dict[str, str]] = []

  def item_for(data: dict[str, object], path: str) -> dict[str, object]:
    files = data.get('conflicted_files')
    require(isinstance(files, list), 'missing conflicted_files list')
    matches = [item for item in files if isinstance(item, dict) and item.get('path') == path]
    require(len(matches) == 1, f'expected one {path} entry, got {matches}')
    return matches[0]

  def preview_side(preview: dict[str, object], side: str) -> dict[str, object]:
    value = preview.get(side)
    require(isinstance(value, dict), f'missing {side} preview: {preview}')
    return value

  def expected_type(stages: list[int]) -> str:
    stage_set = set(stages)
    if stage_set == {2, 3}:
      return 'add/add'
    if stage_set == {1, 2}:
      return 'deleted-by-them'
    if stage_set == {1, 3}:
      return 'deleted-by-us'
    if stage_set == {1, 2, 3}:
      return 'index-only'
    return 'unmerged'

  with tempfile.TemporaryDirectory(prefix='conflict-context-') as tmp:
    root = Path(tmp)

    text_repo = create_text_conflict(root / 'text')
    text_item = item_for(payload(text_repo, '--file', 'f.txt'), 'f.txt')
    require(text_item['conflict_type'] == 'text', f'text type mismatch: {text_item}')
    require(text_item['stages'] == [1, 2, 3], f'text stages mismatch: {text_item}')
    require(text_item['marker_hunks'] == 1, f'text hunk count mismatch: {text_item}')
    hunks = text_item.get('hunks')
    require(isinstance(hunks, list) and len(hunks) == 1, f'text hunks missing: {text_item}')
    hunk = hunks[0]
    require(hunk['ours'] == ['ours'] and hunk['theirs'] == ['theirs'], f'text sides mismatch: {hunk}')
    require(hunk['base'] is None, f'text base should be absent: {hunk}')
    require(bool(hunk['ours_label']) and bool(hunk['theirs_label']), f'text labels missing: {hunk}')
    require('-ours' in hunk['ours_vs_theirs_diff'] and '+theirs' in hunk['ours_vs_theirs_diff'], f'text diff mismatch: {hunk}')
    results.append({'case': 'text', 'status': 'PASS', 'detail': 'exact hunk sides, labels, diff'})

    diff3_repo = create_text_conflict(root / 'diff3', diff3=True)
    diff3_item = item_for(payload(diff3_repo, '--file', 'f.txt'), 'f.txt')
    diff3_hunks = diff3_item.get('hunks')
    require(isinstance(diff3_hunks, list) and len(diff3_hunks) == 1, f'diff3 hunks missing: {diff3_item}')
    diff3_hunk = diff3_hunks[0]
    require(diff3_hunk['ours'] == ['ours'], f'diff3 ours mismatch: {diff3_hunk}')
    require(diff3_hunk['base'] == ['base'], f'diff3 base mismatch: {diff3_hunk}')
    require(diff3_hunk['theirs'] == ['theirs'], f'diff3 theirs mismatch: {diff3_hunk}')
    require(bool(diff3_hunk['base_label']), f'diff3 base label missing: {diff3_hunk}')
    results.append({'case': 'diff3', 'status': 'PASS', 'detail': 'exact ours/base/theirs captured'})

    add_repo = create_add_add(root / 'add-add')
    add_entries = unmerged(add_repo)
    require(add_entries == {'new.txt': {2: '100644', 3: '100644'}}, f'add/add index mismatch: {add_entries}')
    marked_add_item = item_for(payload(add_repo, '--file', 'new.txt'), 'new.txt')
    require(marked_add_item['conflict_type'] == 'add/add' and marked_add_item['marker_hunks'] == 1, f'marked add/add mismatch: {marked_add_item}')
    (add_repo / 'new.txt').unlink()
    add_item = item_for(payload(add_repo, '--file', 'new.txt'), 'new.txt')
    require(add_item['stages'] == [2, 3] and add_item['conflict_type'] == 'add/add', f'add/add mismatch: {add_item}')
    add_preview = add_item.get('index_preview')
    require(isinstance(add_preview, dict), f'add/add preview missing: {add_item}')
    add_ours = preview_side(add_preview, 'ours')
    add_theirs = preview_side(add_preview, 'theirs')
    add_base = preview_side(add_preview, 'base')
    require(add_ours['status'] == 'text' and add_ours['lines'] == ['ours'], f'add/add ours mismatch: {add_ours}')
    require(add_theirs['status'] == 'text' and add_theirs['lines'] == ['theirs'], f'add/add theirs mismatch: {add_theirs}')
    require(add_base['status'] == 'missing', f'add/add base mismatch: {add_base}')
    invalid_repo, invalid_path = create_invalid_utf8_add_add(root / 'invalid-utf8')
    invalid_item = item_for(payload(invalid_repo, '--file', invalid_path), invalid_path)
    invalid_preview = invalid_item.get('index_preview')
    require(isinstance(invalid_preview, dict), f'invalid UTF-8 preview missing: {invalid_item}')
    invalid_ours = preview_side(invalid_preview, 'ours')
    invalid_theirs = preview_side(invalid_preview, 'theirs')
    require(invalid_ours['status'] == 'text' and invalid_ours['lines'] == ['ours-�'], f'invalid UTF-8 ours mismatch: {invalid_ours}')
    require(invalid_theirs['status'] == 'text' and invalid_theirs['lines'] == ['theirs-�'], f'invalid UTF-8 theirs mismatch: {invalid_theirs}')
    invalid_summary = invoke(invalid_repo)
    require('invalid-\\udcff.txt' in invalid_summary.stdout, f'non-UTF-8 path not escaped safely: {invalid_summary.stdout}')
    results.append({'case': 'add-add', 'status': 'PASS', 'detail': 'index fallback and non-UTF-8 path safe'})

    delete_repo = create_modify_delete(root / 'modify-delete')
    delete_entries = unmerged(delete_repo)
    require(delete_entries == {'f.txt': {1: '100644', 2: '100644'}}, f'modify/delete index mismatch: {delete_entries}')
    deleted_item = item_for(payload(delete_repo, '--file', 'f.txt'), 'f.txt')
    require(deleted_item['stages'] == [1, 2] and deleted_item['conflict_type'] == 'deleted-by-them', f'modify/delete mismatch: {deleted_item}')
    delete_preview = deleted_item.get('index_preview')
    require(isinstance(delete_preview, dict), f'modify/delete preview missing: {deleted_item}')
    delete_ours = preview_side(delete_preview, 'ours')
    delete_base = preview_side(delete_preview, 'base')
    delete_theirs = preview_side(delete_preview, 'theirs')
    require(delete_ours['status'] == 'text' and delete_ours['lines'] == ['ours changed'], f'modify/delete ours mismatch: {delete_ours}')
    require(delete_base['status'] == 'text' and delete_base['lines'] == ['base'], f'modify/delete base mismatch: {delete_base}')
    require(delete_theirs['status'] == 'missing', f'modify/delete theirs mismatch: {delete_theirs}')
    empty_delete_repo = create_modify_delete(root / 'empty-modify-delete', '')
    empty_delete_item = item_for(payload(empty_delete_repo, '--file', 'f.txt'), 'f.txt')
    empty_delete_preview = empty_delete_item.get('index_preview')
    require(isinstance(empty_delete_preview, dict), f'empty modify/delete preview missing: {empty_delete_item}')
    empty_ours = preview_side(empty_delete_preview, 'ours')
    empty_theirs = preview_side(empty_delete_preview, 'theirs')
    require(empty_ours['status'] == 'text' and empty_ours['lines'] == [], f'empty stage lost: {empty_ours}')
    require(empty_theirs['status'] == 'missing', f'deleted stage lost: {empty_theirs}')
    results.append({'case': 'modify-delete', 'status': 'PASS', 'detail': 'deleted side differs from empty stage'})

    binary_repo = create_binary(root / 'binary')
    binary_entries = unmerged(binary_repo)
    require(binary_entries == {'f.bin': {1: '100644', 2: '100644', 3: '100644'}}, f'binary index mismatch: {binary_entries}')
    binary_item = item_for(payload(binary_repo, '--file', 'f.bin'), 'f.bin')
    require(binary_item['stages'] == [1, 2, 3] and binary_item['conflict_type'] == 'index-only', f'binary mismatch: {binary_item}')
    require(binary_item['marker_hunks'] == 0, f'binary hunk mismatch: {binary_item}')
    binary_preview = binary_item.get('index_preview')
    require(isinstance(binary_preview, dict), f'binary preview missing: {binary_item}')
    binary_statuses = {side: preview_side(binary_preview, side)['status'] for side in ('ours', 'base', 'theirs')}
    require(set(binary_statuses.values()) == {'binary'}, f'binary preview mismatch: {binary_statuses}')
    results.append({'case': 'binary', 'status': 'PASS', 'detail': 'index-only binary preview safe'})

    rename_repo = create_rename(root / 'rename')
    rename_entries = unmerged(rename_repo)
    rename_map = {
      path: item_for(payload(rename_repo, '--file', path), path)
      for path in rename_entries
    }
    require(set(rename_map) == set(rename_entries), f'rename paths mismatch: {rename_map.keys()} vs {rename_entries.keys()}')
    for path, stages in rename_entries.items():
      expected_stages = sorted(stages)
      require(rename_map[path]['stages'] == expected_stages, f'rename stages mismatch for {path}: {rename_map[path]}')
      require(rename_map[path]['conflict_type'] == expected_type(expected_stages), f'rename type mismatch for {path}: {rename_map[path]}')
    results.append({'case': 'rename', 'status': 'PASS', 'detail': f'exact paths and stages for {len(rename_map)} entries'})

    submodule_repo = create_submodule(root / 'submodule')
    submodule_entries = unmerged(submodule_repo)
    require(submodule_entries == {'sub': {1: '160000', 2: '160000', 3: '160000'}}, f'submodule index mismatch: {submodule_entries}')
    submodule_item = item_for(payload(submodule_repo, '--file', 'sub'), 'sub')
    require(submodule_item['stages'] == [1, 2, 3] and submodule_item['conflict_type'] == 'index-only', f'submodule mismatch: {submodule_item}')
    submodule_preview = submodule_item.get('index_preview')
    require(isinstance(submodule_preview, dict), f'submodule preview missing: {submodule_item}')
    for side in ('ours', 'base', 'theirs'):
      gitlink = preview_side(submodule_preview, side)
      require(gitlink['status'] == 'gitlink' and gitlink['mode'] == '160000', f'submodule {side} preview mismatch: {gitlink}')
      require(gitlink['commit'] == gitlink['object_id'], f'submodule {side} identity mismatch: {gitlink}')
    (submodule_repo / 'sub').rename(submodule_repo / 'sub-worktree')
    write_text(submodule_repo / 'sub', '<<<<<<< fake-ours\nmust-not-leak-gitlink\n=======\nfake-theirs\n>>>>>>> fake\n')
    replaced_submodule_item = item_for(payload(submodule_repo, '--file', 'sub'), 'sub')
    require(replaced_submodule_item['marker_hunks'] == 0, f'gitlink replacement markers should be ignored: {replaced_submodule_item}')
    require('must-not-leak-gitlink' not in json.dumps(replaced_submodule_item), f'gitlink replacement leaked: {replaced_submodule_item}')
    results.append({'case': 'submodule', 'status': 'PASS', 'detail': 'gitlink identity only despite worktree replacement'})

    outside = invoke(text_repo, '--file', '../outside.txt', expected=2)
    require('outside repository' in outside.stderr, f'outside path message mismatch: {outside.stderr}')
    all_files = invoke(text_repo, '--all', expected=2)
    require('unrecognized arguments: --all' in all_files.stderr, f'all-files mode should be rejected: {all_files.stderr}')
    repeated_file = invoke(text_repo, '--file', 'f.txt', '--file', 'f.txt', expected=2)
    require('--file may be provided only once' in repeated_file.stderr, f'repeated file should be rejected: {repeated_file.stderr}')

    clean_repo = init_repo(root / 'clean')
    write_text(clean_repo / 'clean.txt', 'clean\n')
    commit_all(clean_repo, 'clean')
    clean_file = invoke(clean_repo, '--file', 'clean.txt', expected=2)
    require('conflicted file not found: clean.txt' in clean_file.stderr, f'clean repo file validation missing: {clean_file.stderr}')

    symlink_repo = create_text_conflict(root / 'symlink')
    outside_secret = root / 'outside-secret.txt'
    write_text(outside_secret, '<<<<<<< outside-ours\nmust-not-leak\n=======\noutside-theirs\n>>>>>>> outside\n')
    (symlink_repo / 'f.txt').unlink()
    (symlink_repo / 'f.txt').symlink_to(outside_secret)
    symlink_item = item_for(payload(symlink_repo, '--file', 'f.txt'), 'f.txt')
    symlink_preview = symlink_item.get('index_preview')
    require(isinstance(symlink_preview, dict), f'symlink should use index preview: {symlink_item}')
    require(symlink_item['marker_hunks'] == 0, f'symlink markers should be ignored: {symlink_item}')
    require('must-not-leak' not in json.dumps(symlink_item), f'symlink target leaked: {symlink_item}')

    parent_symlink_repo = create_text_conflict(root / 'parent-symlink', relative_path='dir/f.txt')
    outside_parent = root / 'outside-parent'
    write_text(outside_parent / 'f.txt', '<<<<<<< parent-ours\nmust-not-leak-parent\n=======\nparent-theirs\n>>>>>>> parent\n')
    (parent_symlink_repo / 'dir' / 'f.txt').unlink()
    (parent_symlink_repo / 'dir').rmdir()
    (parent_symlink_repo / 'dir').symlink_to(outside_parent, target_is_directory=True)
    parent_symlink_item = item_for(payload(parent_symlink_repo, '--file', 'dir/f.txt'), 'dir/f.txt')
    parent_symlink_preview = parent_symlink_item.get('index_preview')
    require(isinstance(parent_symlink_preview, dict), f'parent symlink should use index preview: {parent_symlink_item}')
    require(parent_symlink_item['marker_hunks'] == 0, f'parent symlink markers should be ignored: {parent_symlink_item}')
    require('must-not-leak-parent' not in json.dumps(parent_symlink_item), f'parent symlink target leaked: {parent_symlink_item}')

    missing_repo = init_repo(root / 'missing-object')
    write_text(missing_repo / 'base.txt', 'base\n')
    commit_all(missing_repo, 'base')
    object_format = git(missing_repo, 'rev-parse', '--show-object-format').stdout.strip()
    object_length = 64 if object_format == 'sha256' else 40
    missing_ours = '1' * object_length
    missing_theirs = '2' * object_length
    index_input = f'100644 {missing_ours} 2\tmissing.txt\n100644 {missing_theirs} 3\tmissing.txt\n'
    index_result = subprocess.run(
      ['git', 'update-index', '--info-only', '--index-info'],
      cwd=missing_repo,
      input=index_input,
      capture_output=True,
      text=True,
      check=False,
    )
    require(index_result.returncode == 0, f'missing object index setup failed: {index_result.stderr}')
    git(missing_repo, 'config', 'extensions.partialClone', 'origin')
    git(missing_repo, 'config', 'remote.origin.promisor', 'true')
    git(missing_repo, 'config', 'remote.origin.partialclonefilter', 'blob:none')
    git(missing_repo, 'config', 'remote.origin.url', f'file://{root / "absent-remote"}')
    transport_tripwire = root / 'transport-tripwire.sh'
    transport_sentinel = root / 'transport-called'
    write_text(transport_tripwire, '#!/bin/sh\nprintf called > "$TRIPWIRE_SENTINEL"\nexit 1\n')
    transport_tripwire.chmod(0o755)
    git(missing_repo, 'config', 'remote.origin.uploadpack', str(transport_tripwire))
    objects_before = {path.relative_to(missing_repo) for path in (missing_repo / '.git' / 'objects').rglob('*') if path.is_file()}
    prior_sentinel = os.environ.get('TRIPWIRE_SENTINEL')
    os.environ['TRIPWIRE_SENTINEL'] = str(transport_sentinel)
    try:
      missing_item = item_for(payload(missing_repo, '--file', 'missing.txt'), 'missing.txt')
    finally:
      if prior_sentinel is None:
        os.environ.pop('TRIPWIRE_SENTINEL', None)
      else:
        os.environ['TRIPWIRE_SENTINEL'] = prior_sentinel
    objects_after = {path.relative_to(missing_repo) for path in (missing_repo / '.git' / 'objects').rglob('*') if path.is_file()}
    missing_preview = missing_item.get('index_preview')
    require(isinstance(missing_preview, dict), f'missing object preview absent: {missing_item}')
    require(preview_side(missing_preview, 'ours')['status'] == 'unavailable', f'missing ours should be unavailable: {missing_preview}')
    require(preview_side(missing_preview, 'theirs')['status'] == 'unavailable', f'missing theirs should be unavailable: {missing_preview}')
    require(not transport_sentinel.exists(), 'missing object preview invoked partial-clone transport')
    require(objects_after == objects_before, f'missing object probe mutated object store: {objects_before} -> {objects_after}')
    results.append({'case': 'outside-path', 'status': 'PASS', 'detail': 'containment, symlink, local-only missing object safe'})

    long_repo = create_text_conflict(root / 'long', long=True)
    truncated = invoke(long_repo, '--file', 'f.txt', '--max-lines', '5')
    require('more lines omitted' in truncated.stdout, 'truncation marker missing')
    results.append({'case': 'truncation', 'status': 'PASS', 'detail': 'omission marker emitted'})

    malformed_repo = create_text_conflict(root / 'malformed')
    write_text(malformed_repo / 'f.txt', '<<<<<<< ours\nunterminated\n')
    malformed_item = item_for(payload(malformed_repo, '--file', 'f.txt'), 'f.txt')
    require(malformed_item['parse_error'] == 'unterminated conflict starting at line 1', f'malformed parse_error mismatch: {malformed_item}')
    require('hunks' not in malformed_item and isinstance(malformed_item.get('index_preview'), dict), f'malformed detail shape mismatch: {malformed_item}')
    results.append({'case': 'unterminated-marker', 'status': 'PASS', 'detail': str(malformed_item['parse_error'])})

  return results


if __name__ == '__main__':
  output = run_tests()
  print(json.dumps({'total': len(output), 'passed': sum(1 for item in output if item['status'] == 'PASS'), 'results': output}, indent=2))
