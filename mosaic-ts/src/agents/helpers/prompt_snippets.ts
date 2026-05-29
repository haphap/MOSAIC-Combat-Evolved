/**
 * Generic prompt-snippet helpers reused across the 25-agent surface.
 *
 * Extracted from ETFAgents' ``ts/src/agents/prompts/shared.ts`` so
 * ``helpers/tool_report_chain.ts`` does not have to depend on the prompts
 * directory (which carries ETF-specific instrument context we are not
 * porting). New shared snippets land here as we wire each agent.
 */

/**
 * Imperative anti-process-narration line. Appended to system messages to
 * suppress preambles like "Now let me ...", "接下来我将 ..." that bleed into
 * the visible report. Mirrors
 * ``etfagents.report_prompt_utils.get_no_process_narration_instruction``.
 */
export function getNoProcessNarrationInstruction(): string {
  return (
    " Do NOT begin your reply with process narration such as 'Now let me', 'Next', " +
    "'I will', 'I can now', '现在我来', '接下来', '下面', '我将', '我可以开始', or any " +
    "status update describing what you are about to do. Begin immediately with the " +
    "report's opening overview paragraph."
  );
}
