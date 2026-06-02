/**
 * JSON-RPC error codes for the MOSAIC bridge.
 * Mirrors `mosaic/bridge/protocol.py`.
 */

import { redactSensitiveText, redactSensitiveValue } from "../security/redaction.js";

// Standard JSON-RPC 2.0
export const PARSE_ERROR = -32700;
export const INVALID_REQUEST = -32600;
export const METHOD_NOT_FOUND = -32601;
export const INVALID_PARAMS = -32602;
export const INTERNAL_ERROR = -32603;

// Server-defined (-32000..-32099)
export const TOOL_EXECUTION_ERROR = -32001;
export const BACKTEST_REJECTED = -32002;
export const DATA_VENDOR_UNAVAILABLE = -32003;
export const CONFIG_ERROR = -32010;
export const PAPER_ERROR = -32020;
export const BACKTEST_ERROR = -32030;
// Reserved for later phases (Plan §6.2):
export const SCORECARD_ERROR = -32040; // Phase 3
export const AUTORESEARCH_ERROR = -32050; // Phase 4
export const PRISM_ERROR = -32060; // Phase 5
export const JANUS_ERROR = -32070; // Phase 6
export const MIROFISH_ERROR = -32080; // Phase 7

/** Thrown when the bridge returns a `{"error": ...}` envelope. */
export class RpcError extends Error {
  override readonly name = "RpcError";
  readonly code: number;
  readonly data: unknown;
  readonly method: string;

  constructor(
    method: string,
    code: number,
    message: string,
    data: unknown = undefined,
    cause?: unknown,
  ) {
    super(
      `${method} failed [${code}]: ${redactSensitiveText(message)}`,
      cause !== undefined ? { cause } : undefined,
    );
    this.method = method;
    this.code = code;
    this.data = redactSensitiveValue(data);
  }
}

/** Thrown when the bridge subprocess cannot be located or started. */
export class BridgeStartupError extends Error {
  override readonly name = "BridgeStartupError";

  constructor(message: string, cause?: unknown) {
    super(message, cause !== undefined ? { cause } : undefined);
  }
}

/** Thrown when a request times out or the bridge dies mid-call. */
export class BridgeTransportError extends Error {
  override readonly name = "BridgeTransportError";

  constructor(message: string, cause?: unknown) {
    super(message, cause !== undefined ? { cause } : undefined);
  }
}
