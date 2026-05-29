/** JSON-RPC 2.0 envelopes used by the bridge. */

export interface JsonRpcRequest<P = unknown> {
  jsonrpc: "2.0";
  id: number;
  method: string;
  params?: P;
}

export interface JsonRpcSuccess<R = unknown> {
  jsonrpc: "2.0";
  id: number | null;
  result: R;
}

export interface JsonRpcErrorEnvelope {
  jsonrpc: "2.0";
  id: number | null;
  error: {
    code: number;
    message: string;
    data?: unknown;
  };
}

export type JsonRpcResponse<R = unknown> = JsonRpcSuccess<R> | JsonRpcErrorEnvelope;

export function isErrorEnvelope<R>(resp: JsonRpcResponse<R>): resp is JsonRpcErrorEnvelope {
  return "error" in resp;
}
