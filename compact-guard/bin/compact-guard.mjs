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

const readInput = async () => {
  let raw = "";
  process.stdin.setEncoding("utf8");
  for await (const chunk of process.stdin) {
    raw += chunk;
  }
  let input;
  try {
    input = JSON.parse(raw);
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
    const input = await readInput();
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
