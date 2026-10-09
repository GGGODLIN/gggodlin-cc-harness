#!/usr/bin/env node

import { homedir } from "node:os"
import { dirname, resolve } from "node:path"
import { fileURLToPath } from "node:url"
import { install, uninstall } from "../src/install.mjs"

const args = process.argv.slice(2)
const projectDir = resolve(dirname(fileURLToPath(import.meta.url)), "..")
const operation = args[0] === "--uninstall" ? "uninstall" : "install"
const validArguments = args.length === 1 && (args[0] === "--install" || args[0] === "--uninstall")

if (!validArguments) {
  console.error(JSON.stringify({ operation: "unknown", status: "failed", errorCode: "INVALID_ARGUMENTS" }))
  process.exitCode = 1
} else {
  try {
    const report = operation === "uninstall"
      ? await uninstall({ homeDir: homedir(), projectDir })
      : await install({ homeDir: homedir(), projectDir })
    console.log(JSON.stringify(report))
    if (report.status === "failed" || report.status === "partial") {
      process.exitCode = 1
    }
  } catch {
    console.error(JSON.stringify({ operation, status: "failed", errorCode: "UNEXPECTED_ERROR" }))
    process.exitCode = 1
  }
}
