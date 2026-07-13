import type { BaseChatModel } from "@langchain/core/language_models/chat_models";
import type { LlmHandle } from "../llm/factory.js";

interface InvokeLike {
  invoke: (...args: unknown[]) => Promise<unknown>;
}

/**
 * Put every invoke derived from one chat model behind a shared FIFO gate.
 *
 * LangGraph fans agents out inside a layer.  The Qwen 35B sndr preset has
 * canonical/max concurrency 1, so queueing only at the vLLM server would leave
 * many long-lived HTTP requests exposed to client timeouts.  The proxy also
 * wraps bindTools/withStructuredOutput derivatives so there is one gate for the
 * complete graph and for Autoresearch mutation calls.
 */
export function serializeLlmHandle(handle: LlmHandle): LlmHandle {
  const gate = new SerialGate();
  return { ...handle, llm: wrapRunnable(handle.llm, gate) as BaseChatModel };
}

class SerialGate {
  private tail: Promise<void> = Promise.resolve();

  run<T>(task: () => Promise<T>): Promise<T> {
    const result = this.tail.then(task, task);
    this.tail = result.then(
      () => undefined,
      () => undefined,
    );
    return result;
  }
}

function wrapRunnable<T extends object>(target: T, gate: SerialGate): T {
  return new Proxy(target, {
    get(current, property, receiver) {
      const value = Reflect.get(current, property, receiver);
      if (property === "invoke" && typeof value === "function") {
        return (...args: unknown[]) =>
          gate.run(() =>
            Promise.resolve(
              Reflect.apply(value, current, args) as ReturnType<InvokeLike["invoke"]>,
            ),
          );
      }
      if (
        ["bind", "bindTools", "withConfig", "withStructuredOutput"].includes(String(property)) &&
        typeof value === "function"
      ) {
        return (...args: unknown[]) => {
          const derived = Reflect.apply(value, current, args) as unknown;
          return derived && typeof derived === "object"
            ? wrapRunnable(derived as object, gate)
            : derived;
        };
      }
      return typeof value === "function" ? value.bind(current) : value;
    },
  });
}
