import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

export function compose(manifestPath, role, expectedTask) {
  if (role !== 'implement') throw new Error('Unknown role');
  const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'));
  if (!expectedTask || manifest.task !== expectedTask) throw new Error('Task mismatch');
  if (!Array.isArray(manifest.materials)) throw new Error('Missing materials');
  const selected = manifest.materials.filter(item => item.roles?.includes(role));
  if (!selected.length) throw new Error('No materials for role');
  const root = dirname(resolve(manifestPath));
  const sections = selected.map(item => {
    const file = resolve(root, item.file);
    const body = readFileSync(file, 'utf8');
    if (!body.trim()) throw new Error(`Empty material: ${item.file}`);
    return `## 材料：${file}\n\n${body}\n`;
  });
  return `# 派工材料\n\n任務：${manifest.task}\n角色：${role}\n\n${sections.join('\n')}`;
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  try {
    process.stdout.write(compose(...process.argv.slice(2)));
  } catch (error) {
    process.stderr.write(`${JSON.stringify({ error: error.message })}\n`);
    process.exitCode = 1;
  }
}
