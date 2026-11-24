#!/usr/bin/env node

import { handleHook } from "../src/hooks.mjs";

const VALID_VENDORS = new Set(["claude", "codex"]);
const EVENT_NAMES = {
  precompact: "PreCompact",
  postcompact: "PostCompact",
  sessionstart: "SessionStart"
};

const parseArguments = (args) => {
  if (args.length !== 4) {
    return null;
  }
  const values = {};
  for (let index = 0; index < args.length; index += 2) {
    const flag = args[index];
    if ((flag !== "--vendor" && flag !== "--managed-id") || values[flag] != null) {
      return null;
    }
    values[flag] = args[index + 1];
  }
  return {
    vendor: values["--vendor"],
    managedId: values["--managed-id"]
  };
};

const DEFAULT_MAX_STDIN_BYTES = 16 * 1024 * 1024;

const resolveMaxStdinBytes = () => {
  const parsed = Number(process.env.COMPACT_GUARD_MAX_STDIN_BYTES);
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : DEFAULT_MAX_STDIN_BYTES;
};

const readInput = async () => {
  const maxBytes = resolveMaxStdinBytes();
  const chunks = [];
  let totalBytes = 0;
  try {
    for await (const chunk of process.stdin) {
      const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
      totalBytes += buffer.length;
      if (totalBytes > maxBytes) {
        process.stdin.destroy();
        return null;
      }
      chunks.push(buffer);
    }
  } catch {
    return null;
  }
  let input;
  try {
    input = JSON.parse(Buffer.concat(chunks, totalBytes).toString("utf8"));
  } catch {
    return null;
  }
  return input !== null && typeof input === "object" && !Array.isArray(input)
    ? input
    : null;
};

const fixedFailure = (errorCode) => {
  process.stderr.write(errorCode);
  process.exitCode = 1;
};

const args = parseArguments(process.argv.slice(2));
if (!args || !VALID_VENDORS.has(args.vendor)) {
  fixedFailure("compact_guard_invalid_arguments");
} else {
  const marker = args.managedId?.match(
    /^compact-guard\/v1\/(claude|codex)\/(precompact|postcompact|sessionstart)$/u
  );
  if (!marker || marker[1] !== args.vendor) {
    fixedFailure("compact_guard_managed_id_mismatch");
  } else {
    let input = null;
    try {
      input = await readInput();
    } catch {
      input = null;
    }
    if (!input) {
      fixedFailure("compact_guard_invalid_input");
    } else if (input.hook_event_name !== EVENT_NAMES[marker[2]]) {
      fixedFailure("compact_guard_event_mismatch");
    } else {
      try {
        const result = await handleHook({ vendor: args.vendor, input, env: process.env });
        if (result.stdout.length > 0) {
          process.stdout.write(result.stdout);
        }
        if (result.stderr.length > 0) {
          process.stderr.write(result.stderr);
        }
        process.exitCode = result.exitCode;
      } catch {
        fixedFailure("compact_guard_hook_failed");
      }
    }
  }
}
