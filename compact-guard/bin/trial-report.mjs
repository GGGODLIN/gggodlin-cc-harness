#!/usr/bin/env node

import { readFile } from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";
import { summarizeAudit } from "../src/trial-report.mjs";

const parseArguments = (args) => {
  if (args.length === 0) {
    return null;
  }
  if (args.length === 2 && args[0] === "--audit" && args[1].length > 0) {
    return args[1];
  }
  throw new TypeError("invalid_arguments");
};

const defaultAuditPath = () => {
  const override = process.env.COMPACT_GUARD_HOME;
  const stateDir = typeof override === "string" && override.length > 0
    ? override
    : join(homedir(), ".compact-guard");
  return join(stateDir, "audit.jsonl");
};

const readRows = async (auditPath) => {
  let raw;
  try {
    raw = await readFile(auditPath, "utf8");
  } catch (error) {
    if (error?.code === "ENOENT") {
      return [];
    }
    throw error;
  }
  return raw
    .split("\n")
    .filter((line) => line.trim().length > 0)
    .map((line) => {
      try {
        return JSON.parse(line);
      } catch {
        return null;
      }
    });
};

try {
  const configuredPath = parseArguments(process.argv.slice(2));
  const summary = summarizeAudit(await readRows(configuredPath ?? defaultAuditPath()));
  process.stdout.write(`${JSON.stringify(summary)}\n`);
} catch {
  process.stderr.write("compact_guard_trial_report_failed");
  process.exitCode = 1;
}
