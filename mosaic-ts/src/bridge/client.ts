/**
 * Newline-delimited JSON-RPC 2.0 client over a Python subprocess's stdio.
 *
 * Lifecycle:
 *   const client = new BridgeClient();
 *   await client.start();
 *   const result = await client.call("tools.list", {});
 *   await client.close();
 *
 * One in-flight request per id; multiple `call()`s can be issued concurrently
 * since the Python side processes them serially and each gets a unique id.
 */

import { type ChildProcessByStdio, spawn } from "node:child_process";
import { once } from "node:events";
import { createInterface, type Interface } from "node:readline";
import type { Readable, Writable } from "node:stream";
import { BridgeStartupError, BridgeTransportError, RpcError } from "./errors.js";
import type { JsonRpcRequest, JsonRpcResponse } from "./protocol.js";
import { isErrorEnvelope } from "./protocol.js";
import { type ResolvedPython, resolvePython } from "./python.js";

export interface BridgeClientOptions {
  /** Override the resolved Python interpreter and repo root. */
  python?: ResolvedPython;
  /** Extra env vars to merge into the subprocess environment. */
  env?: Readonly<Record<string, string | undefined>>;
  /** Per-call timeout in milliseconds (default 60_000). */
  defaultTimeoutMs?: number;
  /** Forward stderr from the bridge to this process's stderr (default false). */
  inheritStderr?: boolean;
}

interface PendingCall {
  resolve: (value: unknown) => void;
  reject: (reason: unknown) => void;
  method: string;
  timer: NodeJS.Timeout | null;
}

type SpawnedChild = ChildProcessByStdio<Writable, Readable, Readable>;

export class BridgeClient {
  private readonly python: ResolvedPython;
  private readonly env: NodeJS.ProcessEnv;
  private readonly defaultTimeoutMs: number;
  private readonly inheritStderr: boolean;

  private child: SpawnedChild | null = null;
  private stdoutReader: Interface | null = null;
  private nextId = 1;
  private readonly pending = new Map<number, PendingCall>();
  private startError: Error | null = null;
  private exited = false;
  private stderrBuffer = "";

  constructor(options: BridgeClientOptions = {}) {
    this.python = options.python ?? resolvePython();
    this.defaultTimeoutMs = options.defaultTimeoutMs ?? 60_000;
    this.inheritStderr = options.inheritStderr ?? false;
    this.env = { ...process.env, ...(options.env ?? {}) } as NodeJS.ProcessEnv;
  }

  /** Spawn the bridge process and prepare stdout reading. Idempotent. */
  async start(): Promise<void> {
    if (this.child) {
      return;
    }
    if (this.startError) {
      throw this.startError;
    }

    let child: SpawnedChild;
    try {
      child = spawn(this.python.python, ["-m", "mosaic.bridge"], {
        cwd: this.python.repoRoot,
        env: this.env,
        stdio: ["pipe", "pipe", "pipe"],
      }) as SpawnedChild;
    } catch (err) {
      const error = new BridgeStartupError(
        `Failed to spawn ${this.python.python}: ${(err as Error).message}`,
        err,
      );
      this.startError = error;
      throw error;
    }

    this.child = child;

    child.on("error", (err) => {
      const error = new BridgeStartupError(`Bridge process error: ${err.message}`, err);
      this.startError = error;
      this.failPending(error);
    });

    child.on("exit", (code, signal) => {
      this.exited = true;
      const reason = new BridgeTransportError(
        `Bridge process exited (code=${code}, signal=${signal}). stderr tail:\n${this.stderrBuffer.slice(-1000)}`,
      );
      this.failPending(reason);
    });

    child.stderr.setEncoding("utf-8");
    child.stderr.on("data", (chunk: string) => {
      this.stderrBuffer += chunk;
      // Cap to avoid unbounded growth on a long-lived process.
      if (this.stderrBuffer.length > 64_000) {
        this.stderrBuffer = this.stderrBuffer.slice(-32_000);
      }
      if (this.inheritStderr) {
        process.stderr.write(chunk);
      }
    });

    child.stdout.setEncoding("utf-8");
    this.stdoutReader = createInterface({ input: child.stdout, crlfDelay: Infinity });
    this.stdoutReader.on("line", (line) => this.handleLine(line));
    this.stdoutReader.on("close", () => {
      // stdout closed without exit yet — just wait for exit handler.
    });
  }

  /**
   * Issue one JSON-RPC call. Resolves with the `result`, rejects with
   * RpcError for `{error}` envelopes or BridgeTransportError on death/timeout.
   */
  async call<R = unknown, P = unknown>(
    method: string,
    params?: P,
    options: { timeoutMs?: number } = {},
  ): Promise<R> {
    if (!this.child) {
      await this.start();
    }
    if (this.exited) {
      throw new BridgeTransportError(
        `Bridge process is no longer running. stderr tail:\n${this.stderrBuffer.slice(-1000)}`,
      );
    }
    const child = this.child;
    if (!child) {
      throw new BridgeTransportError("Bridge process not started");
    }

    const id = this.nextId++;
    const request: JsonRpcRequest<P> = { jsonrpc: "2.0", id, method };
    if (params !== undefined) {
      request.params = params;
    }

    const timeoutMs = options.timeoutMs ?? this.defaultTimeoutMs;

    return new Promise<R>((resolve, reject) => {
      const timer =
        timeoutMs > 0
          ? setTimeout(() => {
              this.pending.delete(id);
              reject(
                new BridgeTransportError(`Bridge call ${method} timed out after ${timeoutMs}ms`),
              );
            }, timeoutMs)
          : null;

      this.pending.set(id, {
        method,
        resolve: resolve as (value: unknown) => void,
        reject,
        timer,
      });

      const line = `${JSON.stringify(request)}\n`;
      child.stdin.write(line, "utf-8", (err) => {
        if (err) {
          this.pending.delete(id);
          if (timer) clearTimeout(timer);
          reject(new BridgeTransportError(`Failed to write request: ${err.message}`, err));
        }
      });
    });
  }

  /** Gracefully close stdin and wait for exit. */
  async close(): Promise<void> {
    if (!this.child || this.exited) {
      return;
    }
    this.child.stdin.end();
    try {
      await once(this.child, "exit");
    } catch {
      // exit handler already ran
    }
    if (this.stdoutReader) {
      this.stdoutReader.close();
    }
  }

  /** Captured stderr (for surfacing import/runtime errors to the user). */
  get stderrTail(): string {
    return this.stderrBuffer;
  }

  // -------------------------------------------------------- internals

  private handleLine(line: string): void {
    if (!line.trim()) {
      return;
    }
    let response: JsonRpcResponse;
    try {
      response = JSON.parse(line) as JsonRpcResponse;
    } catch (err) {
      // Server should never emit garbage on stdout; surface to all pending.
      this.failPending(
        new BridgeTransportError(
          `Bridge emitted non-JSON line: ${line.slice(0, 200)} (${(err as Error).message})`,
          err,
        ),
      );
      return;
    }
    const id = response.id;
    if (typeof id !== "number") {
      // Parse-error responses from the server may carry id=null. We can't
      // correlate those to a pending call, so fail everything pending.
      if (isErrorEnvelope(response)) {
        this.failPending(
          new BridgeTransportError(`Bridge protocol error (no id): ${response.error.message}`),
        );
      }
      return;
    }
    const pending = this.pending.get(id);
    if (!pending) {
      return;
    }
    this.pending.delete(id);
    if (pending.timer) {
      clearTimeout(pending.timer);
    }
    if (isErrorEnvelope(response)) {
      const { code, message, data } = response.error;
      pending.reject(new RpcError(pending.method, code, message, data));
    } else {
      pending.resolve(response.result);
    }
  }

  private failPending(reason: Error): void {
    const pendings = Array.from(this.pending.values());
    this.pending.clear();
    for (const p of pendings) {
      if (p.timer) clearTimeout(p.timer);
      p.reject(reason);
    }
  }
}
